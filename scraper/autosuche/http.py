"""Höflicher HTTP-Client: robots.txt, Rate-Limits pro Host, Retries, Block-Erkennung.

Grundsätze:
* Jede URL wird vor dem Abruf gegen die robots.txt des Hosts geprüft (Protego,
  unterstützt Wildcards wie Google). Ist ein Pfad verboten, wird NICHT abgerufen.
* Pro Host gilt ein Mindestabstand (plus Zufalls-Jitter); ein Crawl-delay aus der
  robots.txt wird respektiert, falls er größer ist.
* 429/5xx/Timeouts werden mit exponentiellem Backoff wiederholt (Retry-After wird beachtet).
* 401/403 oder erkennbare Captcha-/Bot-Schutz-Seiten -> BlockedError. Es wird
  bewusst NICHT versucht, solche Schutzmaßnahmen zu umgehen.
"""
from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urlsplit

import httpx
from protego import Protego

log = logging.getLogger("autosuche.http")

BLOCK_MARKERS = re.compile(
    r"captcha|cf-challenge|challenge-platform|px-captcha|datadome|"
    r"access denied|zugriff verweigert|ungewöhnliche aktivität|unusual traffic|are you a robot",
    re.I,
)


class FetchError(Exception):
    pass


class DisallowedError(FetchError):
    """robots.txt verbietet diese URL."""


class BlockedError(FetchError):
    """Quelle blockiert uns (403, Captcha, Bot-Schutz)."""


class TimeBudgetExceeded(FetchError):
    pass


class PoliteClient:
    def __init__(self, cfg: dict, deadline: float | None = None, transport: httpx.BaseTransport | None = None):
        sc = cfg["scraper"]
        self.ua = sc["user_agent"]
        self.min_delay = float(sc["min_delay_s"])
        self.jitter = float(sc["jitter_s"])
        self.image_delay = float(sc["image_delay_s"])
        self.max_retries = int(sc["max_retries"])
        self.backoff = float(sc["backoff_base_s"])
        self.deadline = deadline
        self._robots: dict[str, Protego | None] = {}
        self._last: dict[str, float] = {}
        self.stats = {"requests": 0, "errors": 0, "disallowed": 0, "blocked": 0}
        self.client = httpx.Client(
            headers={
                "User-Agent": self.ua,
                "Accept-Language": "de-DE,de;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,image/webp,*/*;q=0.8",
            },
            timeout=float(sc["timeout_s"]),
            follow_redirects=True,
            transport=transport,
        )

    # ---------------------------------------------------------------- robots
    def _robots_for(self, url: str) -> Protego | None:
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            try:
                r = self.client.get(host + "/robots.txt")
                self.stats["requests"] += 1
                if r.status_code == 200:
                    self._robots[host] = Protego.parse(r.text)
                elif r.status_code in (401, 403):
                    # Konservativ: robots.txt nicht lesbar wegen Sperre -> alles verboten
                    log.warning("robots.txt von %s liefert %s -> behandle Host als gesperrt", host, r.status_code)
                    self._robots[host] = Protego.parse("User-agent: *\nDisallow: /")
                elif 400 <= r.status_code < 500:
                    self._robots[host] = None  # keine robots.txt -> erlaubt
                else:
                    self._robots[host] = Protego.parse("User-agent: *\nDisallow: /")
            except httpx.HTTPError as e:
                log.warning("robots.txt von %s nicht abrufbar (%s) -> Host übersprungen", host, e)
                self._robots[host] = Protego.parse("User-agent: *\nDisallow: /")
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return True if rp is None else rp.can_fetch(url, self.ua)

    def _crawl_delay(self, url: str) -> float:
        rp = self._robots_for(url)
        if rp is None:
            return 0.0
        d = rp.crawl_delay(self.ua)
        return float(d) if d else 0.0

    # ---------------------------------------------------------------- pacing
    def _wait(self, url: str, kind: str) -> None:
        host = urlsplit(url).netloc
        base = self.image_delay if kind == "image" else max(self.min_delay, self._crawl_delay(url))
        delay = base + (random.uniform(0, self.jitter) if kind != "image" else 0)
        elapsed = time.monotonic() - self._last.get(host, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last[host] = time.monotonic()

    def _check_deadline(self) -> None:
        if self.deadline and time.monotonic() > self.deadline:
            raise TimeBudgetExceeded("Laufzeitbudget erschöpft")

    # ---------------------------------------------------------------- fetch
    def get(self, url: str, kind: str = "page") -> httpx.Response:
        self._check_deadline()
        if not self.allowed(url):
            self.stats["disallowed"] += 1
            raise DisallowedError(f"robots.txt verbietet {url}")
        attempt = 0
        while True:
            self._wait(url, kind)
            attempt += 1
            try:
                r = self.client.get(url)
                self.stats["requests"] += 1
            except httpx.HTTPError as e:
                self.stats["errors"] += 1
                if attempt > self.max_retries:
                    raise FetchError(f"{url}: {e}") from e
                self._sleep_backoff(attempt, None)
                continue

            if r.status_code in (401, 403):
                self.stats["blocked"] += 1
                raise BlockedError(f"HTTP {r.status_code} für {url}")
            if r.status_code == 429 or r.status_code >= 500:
                self.stats["errors"] += 1
                if attempt > self.max_retries:
                    if r.status_code == 429:
                        self.stats["blocked"] += 1
                        raise BlockedError(f"Dauerhaft HTTP 429 (Rate-Limit) für {url}")
                    raise FetchError(f"HTTP {r.status_code} für {url}")
                self._sleep_backoff(attempt, r.headers.get("Retry-After"))
                continue
            if r.status_code == 404 or r.status_code == 410:
                raise FetchError(f"HTTP {r.status_code} für {url}")
            if kind == "page" and r.status_code == 200 and len(r.content) < 20000:
                # Kleine Seiten mit Captcha-Hinweisen sind fast immer Bot-Schutz-Seiten
                if BLOCK_MARKERS.search(r.text[:20000]):
                    self.stats["blocked"] += 1
                    raise BlockedError(f"Bot-Schutz/Captcha-Seite erkannt bei {url}")
            r.raise_for_status()
            return r

    def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        wait = self.backoff * (2 ** (attempt - 1)) + random.uniform(0, 1)
        if retry_after and retry_after.isdigit():
            wait = max(wait, min(float(retry_after), 300))
        log.info("Warte %.1fs vor Wiederholung (Versuch %d)", wait, attempt)
        time.sleep(wait)

    def close(self) -> None:
        self.client.close()
