"""SQLite-Speicher: Inserate, Preisverlauf, Taxonomie (Marken/Modelle), Laufprotokoll, Zustand."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    data TEXT NOT NULL,              -- Listing als JSON
    price INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    detail_at TEXT,
    analysis TEXT,                   -- Bildanalyse/Hashes als JSON
    analysis_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_listings_last_seen ON listings(last_seen);
CREATE TABLE IF NOT EXISTS price_history (
    uid TEXT NOT NULL,
    ts TEXT NOT NULL,
    price INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ph_uid ON price_history(uid);
CREATE TABLE IF NOT EXISTS taxonomy (
    source TEXT NOT NULL,
    make TEXT NOT NULL,
    slug TEXT,
    models TEXT,                     -- JSON-Liste
    groups TEXT,                     -- JSON {Einzelmodell: Baureihe}
    updated TEXT,
    PRIMARY KEY (source, make)
);
CREATE TABLE IF NOT EXISTS runs (
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,            -- ok / blocked / disallowed / error / partial
    message TEXT,
    found INTEGER,
    new INTEGER
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # einfache Migrationen für ältere Datenbanken
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(taxonomy)")}
        if "groups" not in cols:
            self.conn.execute("ALTER TABLE taxonomy ADD COLUMN groups TEXT")

    # ------------------------------------------------------------ listings
    def get(self, uid: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM listings WHERE uid=?", (uid,)).fetchone()

    def upsert(self, l: Listing, ts: str | None = None) -> tuple[bool, bool]:
        """Speichert ein Inserat. Rückgabe: (neu?, Preis geändert?)."""
        ts = ts or now_iso()
        l.sanitize()
        row = self.get(l.uid)
        if row is None:
            self.conn.execute(
                "INSERT INTO listings(uid, source, source_id, data, price, first_seen, last_seen, detail_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (l.uid, l.source, l.source_id, json.dumps(l.to_dict(), ensure_ascii=False), l.price, ts, ts,
                 ts if l.detail_loaded else None),
            )
            if l.price:
                self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (l.uid, ts, l.price))
            return True, False
        old = json.loads(row["data"])
        merged = self._merge(old, l)
        changed = bool(l.price) and l.price != row["price"]
        self.conn.execute(
            "UPDATE listings SET data=?, price=?, last_seen=?, detail_at=COALESCE(?, detail_at) WHERE uid=?",
            (json.dumps(merged, ensure_ascii=False), l.price or row["price"], ts,
             ts if l.detail_loaded else None, l.uid),
        )
        if changed:
            self.conn.execute("INSERT INTO price_history VALUES (?,?,?)", (l.uid, ts, l.price))
        return False, changed

    @staticmethod
    def _merge(old: dict, new: Listing) -> dict:
        """Neue Werte überschreiben alte – aber leere Felder der Liste löschen keine Detaildaten."""
        nd = new.to_dict()
        out = dict(old)
        for k, v in nd.items():
            if v in (None, "", [], {}):
                continue
            if k == "accident" and v == "unknown" and old.get("accident") not in (None, "unknown"):
                continue
            if k == "images" and not new.detail_loaded and len(old.get("images") or []) > len(v):
                continue
            if k == "image_count" and not new.detail_loaded and (old.get("image_count") or 0) > v:
                continue
            if k == "extra":
                out["extra"] = {**(old.get("extra") or {}), **v}
                continue
            if k == "detail_loaded" and not v:
                continue
            out[k] = v
        return out

    def needs_detail(self, uid: str, price: int | None) -> bool:
        row = self.get(uid)
        if row is None or row["detail_at"] is None:
            return True
        return False

    def set_analysis(self, uid: str, analysis: dict) -> None:
        self.conn.execute("UPDATE listings SET analysis=?, analysis_at=? WHERE uid=?",
                          (json.dumps(analysis), now_iso(), uid))

    def active(self, since_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM listings WHERE last_seen >= ?", (since_iso,)).fetchall()

    def price_history(self, uid: str) -> list[tuple[str, int]]:
        return [(r["ts"], r["price"]) for r in
                self.conn.execute("SELECT ts, price FROM price_history WHERE uid=? ORDER BY ts", (uid,))]

    # ------------------------------------------------------------ taxonomy
    def save_taxonomy(self, source: str, make: str, slug: str, models: list[str],
                      groups: dict[str, str] | None = None) -> None:
        row = self.conn.execute("SELECT models, groups FROM taxonomy WHERE source=? AND make=?",
                                (source, make)).fetchone()
        old = set(json.loads(row["models"])) if row and row["models"] else set()
        old_groups = json.loads(row["groups"]) if row and row["groups"] else {}
        self.conn.execute(
            "INSERT OR REPLACE INTO taxonomy(source, make, slug, models, groups, updated) VALUES (?,?,?,?,?,?)",
            (source, make, slug, json.dumps(sorted(old | set(models)), ensure_ascii=False),
             json.dumps({**old_groups, **(groups or {})}, ensure_ascii=False), now_iso()),
        )

    def model_group_map(self) -> dict[str, dict[str, str]]:
        """{make_key: {model_key(Einzelmodell): Baureihe}} aus allen Taxonomien."""
        from .textparse import make_key, model_key
        out: dict[str, dict[str, str]] = {}
        for r in self.taxonomy():
            for m, g in json.loads(r["groups"] or "{}").items():
                out.setdefault(make_key(r["make"]), {})[model_key("", m)] = g
        return out

    def taxonomy(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM taxonomy").fetchall()

    # ------------------------------------------------------------ runs/state
    def log_run(self, source: str, status: str, message: str, found: int = 0, new: int = 0) -> None:
        self.conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (now_iso(), source, status, message, found, new))

    def last_runs(self) -> dict[str, dict]:
        out = {}
        for r in self.conn.execute("SELECT * FROM runs ORDER BY ts"):
            out[r["source"]] = dict(r)
        return out

    def load_state(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.conn.execute("SELECT * FROM state")}

    def save_state(self, state: dict) -> None:
        for k, v in state.items():
            self.conn.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (k, json.dumps(v)))

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
