"""CLI: Scrapen -> SQLite -> Bildanalyse -> JSON-Export.

Beispiele:
  python -m autosuche.run                       # alle aktivierten Quellen + Export
  python -m autosuche.run --sources autoscout24 # nur eine Quelle
  python -m autosuche.run --export-only         # nur JSON neu erzeugen
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .adapters import ADAPTERS
from .config import REPO_DIR, SCRAPER_DIR, load_config
from .db import DB
from .export import export
from .http import BlockedError, DisallowedError, FetchError, PoliteClient, TimeBudgetExceeded
from .images import analyze_images

log = logging.getLogger("autosuche")


def run_source(name: str, cfg: dict, db: DB, state: dict, deadline: float) -> None:
    adapter_cls = ADAPTERS[name]
    # Nach einer Sperre pausiert die Quelle (höflich, kein Dauerklopfen)
    until = state.get(f"{name}.blocked_until")
    if until and datetime.now(timezone.utc).isoformat() < until:
        msg = f"pausiert nach Sperre bis {until[:16].replace('T', ' ')} UTC"
        log.warning("[%s] %s", name, msg)
        db.log_run(name, "blocked", msg)
        db.commit()
        return
    client = PoliteClient(cfg, deadline=deadline)
    adapter = adapter_cls(client, cfg, state)
    found = new = details = 0
    status, message = "ok", ""
    try:
        makes = adapter.discover_makes()
        seen: dict[str, object] = {}
        for l in adapter.iter_search(makes):
            if l.uid in seen:
                continue
            seen[l.uid] = l
            try:
                is_new, _ = db.upsert(l)
            except Exception as e:  # noqa: BLE001 – ein kaputtes Inserat darf die Quelle nicht stoppen
                log.warning("%s: Inserat %s übersprungen (%s)", name, l.url, e)
                continue
            found += 1
            new += int(is_new)
        for mk in makes:
            db.save_taxonomy(name, mk.make, mk.slug, mk.models, mk.model_groups)
        db.commit()

        # Detailseiten: zuerst neue Inserate, begrenzt pro Lauf
        max_details = int(adapter.scfg.get("max_details_per_run", 50))
        todo = [l for l in seen.values() if db.needs_detail(l.uid, l.price)]
        for l in todo:
            if details >= max_details:
                break
            try:
                adapter.fetch_detail(l)
                db.upsert(l)
                if not l.extra.get("detail_blocked_by_robots"):
                    details += 1  # nur echte Seitenabrufe zählen gegen das Limit
            except (DisallowedError, BlockedError):
                raise
            except FetchError as e:
                log.info("%s: Detail %s übersprungen: %s", name, l.url, e)
            except (ValueError, KeyError, TypeError) as e:
                log.warning("%s: Detailseite %s nicht parsebar (%s) – Struktur geändert?", name, l.url, e)
            if details % 10 == 0:
                db.commit()
        db.commit()

        message = f"{found} Inserate gefunden, {new} neu, {details} Detailseiten"
    except DisallowedError as e:
        status, message = "disallowed", f"robots.txt verbietet Zugriff: {e}"
        log.error("QUELLE ÜBERSPRUNGEN [%s]: %s", name, message)
    except BlockedError as e:
        status, message = "blocked", f"Quelle blockiert uns: {e}"
        pause_h = float(cfg["scraper"].get("pause_after_block_hours", 12))
        state[f"{name}.blocked_until"] = (datetime.now(timezone.utc) + timedelta(hours=pause_h)).replace(
            microsecond=0).isoformat()
        log.error("QUELLE BLOCKIERT [%s]: %s – Pause %.0f h, andere Quellen laufen weiter", name, e, pause_h)
    except TimeBudgetExceeded:
        status = "partial"
        message = f"Zeitbudget erschöpft: {found} gefunden, {new} neu, {details} Detailseiten"
        log.warning("%s: %s", name, message)
    except Exception as e:  # noqa: BLE001 – eine kaputte Quelle darf den Lauf nicht beenden
        status, message = "error", f"{type(e).__name__}: {e}"
        log.exception("Fehler in Quelle %s – andere Quellen laufen weiter", name)
    finally:
        db.commit()
        db.log_run(name, status, message, found, new)
        db.save_state(state)
        db.commit()
        log.info("[%s] %s – %s | HTTP: %s", name, status.upper(), message, client.stats)
        client.close()


def run_image_analysis(cfg: dict, db: DB, deadline: float, thumbs: Path) -> None:
    """Thumbnail, pHash, Bildqualität, Innenraum – für alle Quellen, neueste Inserate zuerst."""
    client = PoliteClient(cfg, deadline=deadline)
    n_img = int(cfg["scraper"]["images_per_listing_for_analysis"])
    limit = int(cfg["scraper"].get("max_image_analyses_per_run", 400))
    hours = int(cfg["scraper"]["stale_after_hours"])
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
    rows = db.conn.execute(
        "SELECT uid, source, data FROM listings WHERE analysis IS NULL AND detail_at IS NOT NULL "
        "AND last_seen >= ? ORDER BY first_seen DESC LIMIT ?", (since, limit)
    ).fetchall()
    done = 0
    try:
        for row in rows:
            d = json.loads(row["data"])
            a = analyze_images(client, row["uid"], row["source"], d.get("images") or [], d.get("thumb_source") or "",
                               thumbs, n_img, d.get("extra"))
            db.set_analysis(row["uid"], a)
            done += 1
            if done % 10 == 0:
                db.commit()
    except TimeBudgetExceeded:
        log.warning("Bildanalyse: Zeitbudget erschöpft – Rest folgt im nächsten Lauf")
    finally:
        db.commit()
        client.close()
    log.info("Bildanalyse: %d von %d offenen Inseraten analysiert | HTTP: %s", done, len(rows), client.stats)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gebrauchtwagen-Scraper")
    ap.add_argument("--config")
    ap.add_argument("--db", default=str(SCRAPER_DIR / "var" / "autosuche.sqlite"))
    ap.add_argument("--out", default=str(REPO_DIR / "web" / "data"))
    ap.add_argument("--sources", help="Kommagetrennt, z. B. autoscout24,kleinanzeigen")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config(args.config)
    db = DB(args.db)
    out = Path(args.out)
    thumbs = out / "thumbs"

    if not args.export_only:
        state = db.load_state()
        names = [n for n in (args.sources.split(",") if args.sources else ADAPTERS)
                 if cfg.get("sources", {}).get(n, {}).get("enabled", False)]
        total = float(cfg["scraper"]["max_runtime_min"]) * 60
        start = time.monotonic()
        scrape_budget = total * float(cfg["scraper"].get("scrape_share", 0.6))
        for i, name in enumerate(names):
            remaining = scrape_budget - (time.monotonic() - start)
            share = max(remaining / (len(names) - i), 30)
            log.info("=== Quelle %s (Zeitbudget %.0f s) ===", name, share)
            run_source(name, cfg, db, state, time.monotonic() + share)
        log.info("=== Bildanalyse (Rest-Budget %.0f s) ===", total - (time.monotonic() - start))
        run_image_analysis(cfg, db, start + total, thumbs)

    export(db, cfg, out, thumbs_src=thumbs)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
