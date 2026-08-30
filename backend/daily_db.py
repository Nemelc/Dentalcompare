import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "daily_catalog.sqlite3"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS products (
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
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        price_eur REAL,
        availability TEXT,
        source TEXT NOT NULL,
        FOREIGN KEY(product_id) REFERENCES products(id)
    );

    CREATE INDEX IF NOT EXISTS idx_products_merchant_ref
        ON products(merchant, merchant_reference);

    CREATE INDEX IF NOT EXISTS idx_products_manufacturer_ref
        ON products(manufacturer_reference);
    """)
    con.commit()
    con.close()


def upsert_product(row, source="seed_import"):
    init_db()
    con = connect()
    cur = con.cursor()
    now = now_utc()

    merchant = (row.get("merchant") or "").strip()
    merchant_reference = (row.get("merchant_reference") or "").strip() or None
    manufacturer_reference = (row.get("manufacturer_reference") or "").strip() or None
    brand = (row.get("brand") or "").strip() or None
    name = (row.get("name") or "").strip()
    variant = (row.get("variant") or "").strip() or None
    source_url = (row.get("source_url") or "").strip()
    price = row.get("price_eur")
    availability = (row.get("availability") or "").strip() or None

    if not merchant:
        raise ValueError("merchant manquant")
    if not name:
        raise ValueError("name manquant")
    if not source_url:
        raise ValueError("source_url manquante")

    existing = None

    if merchant_reference:
        existing = cur.execute("""
            SELECT * FROM products
            WHERE merchant = ? AND merchant_reference = ?
            LIMIT 1
        """, (merchant, merchant_reference)).fetchone()

    if existing is None and manufacturer_reference:
        existing = cur.execute("""
            SELECT * FROM products
            WHERE merchant = ?
              AND manufacturer_reference = ?
              AND source_url = ?
            LIMIT 1
        """, (merchant, manufacturer_reference, source_url)).fetchone()

    if existing is None:
        existing = cur.execute("""
            SELECT * FROM products
            WHERE merchant = ?
              AND source_url = ?
              AND name = ?
              AND COALESCE(variant, '') = COALESCE(?, '')
            LIMIT 1
        """, (merchant, source_url, name, variant)).fetchone()

    if existing is None:
        cur.execute("""
            INSERT INTO products (
                merchant, merchant_reference, manufacturer_reference,
                brand, name, variant, source_url,
                current_price_eur, current_availability,
                first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            merchant, merchant_reference, manufacturer_reference,
            brand, name, variant, source_url,
            price, availability, now, now
        ))
        product_id = cur.lastrowid
        changed = True
    else:
        product_id = existing["id"]
        changed = (
            existing["current_price_eur"] != price
            or existing["current_availability"] != availability
        )
        cur.execute("""
            UPDATE products
            SET manufacturer_reference = ?,
                brand = ?,
                name = ?,
                variant = ?,
                source_url = ?,
                current_price_eur = ?,
                current_availability = ?,
                last_seen_at = ?
            WHERE id = ?
        """, (
            manufacturer_reference, brand, name, variant, source_url,
            price, availability, now, product_id
        ))

    if changed:
        cur.execute("""
            INSERT INTO history (
                product_id, observed_at, price_eur, availability, source
            )
            VALUES (?, ?, ?, ?, ?)
        """, (product_id, now, price, availability, source))

    con.commit()
    con.close()
    return product_id, changed
