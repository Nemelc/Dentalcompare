import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "dentalcompare.sqlite3"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = connect()
    cur = con.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS merchant_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant TEXT NOT NULL,
        merchant_reference TEXT,
        manufacturer_reference TEXT,
        brand TEXT,
        name TEXT NOT NULL,
        variant TEXT,
        source_url TEXT NOT NULL,
        current_price_eur REAL,
        current_availability TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        UNIQUE(merchant, source_url, merchant_reference, manufacturer_reference)
    );

    CREATE TABLE IF NOT EXISTS offer_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_product_id INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        price_eur REAL,
        availability TEXT,
        source TEXT NOT NULL,
        FOREIGN KEY (merchant_product_id)
            REFERENCES merchant_products(id)
    );

    CREATE INDEX IF NOT EXISTS idx_mp_mref
        ON merchant_products(manufacturer_reference);

    CREATE INDEX IF NOT EXISTS idx_history_product_time
        ON offer_history(merchant_product_id, observed_at);
    """)

    con.commit()
    con.close()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_product(row, source="seed_import"):
    con = connect()
    cur = con.cursor()
    now = utcnow()

    cur.execute("""
        SELECT * FROM merchant_products
        WHERE merchant = ?
          AND source_url = ?
          AND COALESCE(merchant_reference, '') = COALESCE(?, '')
          AND COALESCE(manufacturer_reference, '') = COALESCE(?, '')
        LIMIT 1
    """, (
        row.get("merchant"),
        row.get("source_url"),
        row.get("merchant_reference"),
        row.get("manufacturer_reference"),
    ))
    existing = cur.fetchone()

    if existing is None:
        cur.execute("""
            INSERT INTO merchant_products (
                merchant, merchant_reference, manufacturer_reference,
                brand, name, variant, source_url,
                current_price_eur, current_availability,
                first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("merchant"),
            row.get("merchant_reference"),
            row.get("manufacturer_reference"),
            row.get("brand"),
            row.get("name"),
            row.get("variant"),
            row.get("source_url"),
            row.get("price_eur"),
            row.get("availability"),
            now, now,
        ))
        product_id = cur.lastrowid
        changed = True
    else:
        product_id = existing["id"]
        changed = (
            existing["current_price_eur"] != row.get("price_eur")
            or existing["current_availability"] != row.get("availability")
        )

        cur.execute("""
            UPDATE merchant_products
            SET brand = ?,
                name = ?,
                variant = ?,
                current_price_eur = ?,
                current_availability = ?,
                last_seen_at = ?
            WHERE id = ?
        """, (
            row.get("brand"),
            row.get("name"),
            row.get("variant"),
            row.get("price_eur"),
            row.get("availability"),
            now,
            product_id,
        ))

    if changed:
        cur.execute("""
            INSERT INTO offer_history (
                merchant_product_id, observed_at,
                price_eur, availability, source
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            product_id,
            now,
            row.get("price_eur"),
            row.get("availability"),
            source,
        ))

    con.commit()
    con.close()
    return product_id, changed
