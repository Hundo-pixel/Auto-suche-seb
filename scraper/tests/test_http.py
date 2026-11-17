"""PoliteClient: robots.txt, Block-Erkennung, Retries – ohne echtes Netz (httpx.MockTransport)."""
import httpx
import pytest

from autosuche.config import load_config
from autosuche.http import BlockedError, DisallowedError, PoliteClient


def make_client(handler):
    cfg = load_config()
    cfg = {**cfg, "scraper": {**cfg["scraper"], "min_delay_s": 0, "jitter_s": 0, "image_delay_s": 0,
                              "backoff_base_s": 0.01, "max_retries": 2}}
    return PoliteClient(cfg, transport=httpx.MockTransport(handler))


ROBOTS = "User-agent: *\nDisallow: /angebote/\nDisallow: /lst?\n"
BIG = "<html>" + "x" * 30000 + "</html>"


def test_robots_disallow_blocks_request():
    calls = []

    def h(req):
        calls.append(req.url.path)
        return httpx.Response(200, text=ROBOTS if req.url.path == "/robots.txt" else BIG)

    c = make_client(h)
    with pytest.raises(DisallowedError):
        c.get("https://example.org/angebote/123")
    with pytest.raises(DisallowedError):
        c.get("https://example.org/lst?sort=age")
    assert c.get("https://example.org/lst/bmw?sort=age").status_code == 200
    assert "/angebote/123" not in calls          # verbotene URL wurde nie abgerufen


def test_403_raises_blocked():
    def h(req):
        return httpx.Response(200, text="") if req.url.path == "/robots.txt" else httpx.Response(403, text="nope")

    with pytest.raises(BlockedError):
        make_client(h).get("https://example.org/x")


def test_captcha_page_raises_blocked():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html>Please solve the captcha</html>")

    with pytest.raises(BlockedError):
        make_client(h).get("https://example.org/x")


def test_retry_on_503_then_success():
    n = {"x": 0}

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        n["x"] += 1
        return httpx.Response(503) if n["x"] < 3 else httpx.Response(200, text=BIG)

    c = make_client(h)
    assert c.get("https://example.org/x").status_code == 200
    assert n["x"] == 3


def test_unreadable_robots_is_treated_as_disallow():
    def h(req):
        return httpx.Response(500) if req.url.path == "/robots.txt" else httpx.Response(200, text=BIG)

    with pytest.raises(DisallowedError):
        make_client(h).get("https://example.org/x")


def test_blocked_host_is_not_contacted_again():
    calls = []

    def h(req):
        calls.append(req.url.path)
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(403)

    c = make_client(h)
    with pytest.raises(BlockedError):
        c.get("https://example.org/a")
    with pytest.raises(BlockedError):
        c.get("https://example.org/b")
    assert "/b" not in calls
