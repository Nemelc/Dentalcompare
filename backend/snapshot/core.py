from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "catalog_snapshots.sqlite3"

@dataclass
class Offer:
    merchant: str
    source_url: str
    name: str
    merchant_reference: Optional[str] = None
    manufacturer_reference: Optional[str] = None
    ean: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    packaging: Optional[str] = None
    price_eur: Optional[float] = None
    availability: Optional[str] = None
    image_url: Optional[str] = None
    captured_at: Optional[str] = None

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS snapshot_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        source_mode TEXT NOT NULL,
        item_count INTEGER NOT NULL DEFAULT 0,
        notes TEXT
    );
    CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        merchant TEXT NOT NULL,
        source_url TEXT NOT NULL,
        name TEXT NOT NULL,
        merchant_reference TEXT,
        manufacturer_reference TEXT,
        ean TEXT,
        brand TEXT,
        category TEXT,
        variant TEXT,
        packaging TEXT,
        price_eur REAL,
        availability TEXT,
        image_url TEXT,
        captured_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES snapshot_runs(id)
    );
    CREATE INDEX IF NOT EXISTS idx_offers_run ON offers(run_id);
    CREATE INDEX IF NOT EXISTS idx_offers_mref ON offers(merchant, merchant_reference);
    CREATE INDEX IF NOT EXISTS idx_offers_fref ON offers(manufacturer_reference);
    CREATE INDEX IF NOT EXISTS idx_offers_ean ON offers(ean);
    """)
    con.commit(); con.close()

def begin_run(merchant: str, source_mode: str, notes: str = "") -> int:
    init_db(); con = connect()
    cur = con.execute("INSERT INTO snapshot_runs(merchant, started_at, source_mode, notes) VALUES(?,?,?,?)", (merchant, now(), source_mode, notes))
    run_id = cur.lastrowid
    con.commit(); con.close(); return run_id

def save_offers(run_id: int, offers: list[Offer]):
    con = connect()
    for o in offers:
        con.execute("""INSERT INTO offers(run_id,merchant,source_url,name,merchant_reference,manufacturer_reference,ean,brand,category,variant,packaging,price_eur,availability,image_url,captured_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id,o.merchant,o.source_url,o.name,o.merchant_reference,o.manufacturer_reference,o.ean,o.brand,o.category,o.variant,o.packaging,o.price_eur,o.availability,o.image_url,o.captured_at or now()))
    con.commit(); con.close()

def finish_run(run_id: int):
    con = connect()
    count = con.execute("SELECT COUNT(*) c FROM offers WHERE run_id=?", (run_id,)).fetchone()["c"]
    con.execute("UPDATE snapshot_runs SET finished_at=?, item_count=? WHERE id=?", (now(), count, run_id))
    con.commit(); con.close(); return count

def latest_run_id(merchant: str) -> Optional[int]:
    con = connect()
    row = con.execute("SELECT id FROM snapshot_runs WHERE merchant=? AND finished_at IS NOT NULL ORDER BY finished_at DESC,id DESC LIMIT 1", (merchant,)).fetchone()
    con.close(); return row["id"] if row else None

def latest_offers(merchant: str) -> list[dict]:
    run_id = latest_run_id(merchant)
    if run_id is None: return []
    con = connect(); rows = con.execute("SELECT * FROM offers WHERE run_id=? ORDER BY id", (run_id,)).fetchall(); con.close()
    return [dict(r) for r in rows]
