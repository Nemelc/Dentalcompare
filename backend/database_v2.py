
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent / "data" / "dentalcompare.sqlite3"


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _columns(con, table_name):
    return {
        row["name"]
        for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _add_missing_columns(con):
    """
    Met à niveau une ancienne base DentalCompare sans supprimer les données.
    SQLite ne modifie pas une table existante avec CREATE TABLE IF NOT EXISTS,
    donc on ajoute ici les colonnes apparues dans la version quotidienne.
    """
    cols = _columns(con, "merchant_products")

    additions = {
        "merchant": "TEXT",
        "merchant_reference": "TEXT",
        "manufacturer_reference": "TEXT",
        "brand": "TEXT",
        "name": "TEXT",
        "variant": "TEXT",
        "source_url": "TEXT",
        "current_price_eur": "REAL",
        "current_availability": "TEXT",
        "first_seen_at": "TEXT",
        "last_seen_at": "TEXT",
    }

    for column, sql_type in additions.items():
        if column not in cols:
            con.execute(
                f"ALTER TABLE merchant_products ADD COLUMN {column} {sql_type}"
            )


def init_db():
    con = connect()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS merchant_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant TEXT,
            merchant_reference TEXT,
            manufacturer_reference TEXT,
            brand TEXT,
            name TEXT,
            variant TEXT,
            source_url TEXT,
            current_price_eur REAL,
            current_availability TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT
        )
    """)

    _add_missing_columns(con)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS offer_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_product_id INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            price_eur REAL,
            availability TEXT,
            source TEXT NOT NULL,
            FOREIGN KEY (merchant_product_id)
                REFERENCES merchant_products(id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mp_mref
        ON merchant_products(manufacturer_reference)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_mp_source
        ON merchant_products(merchant, source_url)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_history_product_time
        ON offer_history(merchant_product_id, observed_at)
    """)

    con.commit()
    con.close()


def upsert_product(row, source="seed_import"):
    init_db()

    con = connect()
    cur = con.cursor()
    now = utcnow()

    merchant = (row.get("merchant") or "").strip()
    source_url = (row.get("source_url") or "").strip()
    merchant_reference = (row.get("merchant_reference") or "").strip() or None
    manufacturer_reference = (
        (row.get("manufacturer_reference") or "").strip() or None
    )

    # Recherche prioritaire par référence marchand.
    existing = None

    if merchant_reference:
        existing = cur.execute("""
            SELECT *
            FROM merchant_products
            WHERE merchant = ?
              AND merchant_reference = ?
            ORDER BY id
            LIMIT 1
        """, (merchant, merchant_reference)).fetchone()

    # À défaut, référence fabricant + URL source.
    if existing is None and manufacturer_reference:
        existing = cur.execute("""
            SELECT *
            FROM merchant_products
            WHERE merchant = ?
              AND manufacturer_reference = ?
              AND COALESCE(source_url, '') = ?
            ORDER BY id
            LIMIT 1
        """, (
            merchant,
            manufacturer_reference,
            source_url,
        )).fetchone()

    # Dernier filet : URL + nom + variante.
    if existing is None:
        existing = cur.execute("""
            SELECT *
            FROM merchant_products
            WHERE merchant = ?
              AND COALESCE(source_url, '') = ?
              AND COALESCE(name, '') = ?
              AND COALESCE(variant, '') = ?
            ORDER BY id
            LIMIT 1
        """, (
            merchant,
            source_url,
            row.get("name") or "",
            row.get("variant") or "",
        )).fetchone()

    new_price = row.get("price_eur")
    new_availability = row.get("availability")

    if existing is None:
        cur.execute("""
            INSERT INTO merchant_products (
                merchant,
                merchant_reference,
                manufacturer_reference,
                brand,
                name,
                variant,
                source_url,
                current_price_eur,
                current_availability,
                first_seen_at,
                last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            merchant,
            merchant_reference,
            manufacturer_reference,
            row.get("brand"),
            row.get("name"),
            row.get("variant"),
            source_url,
            new_price,
            new_availability,
            now,
            now,
        ))
        product_id = cur.lastrowid
        changed = True

    else:
        product_id = existing["id"]

        changed = (
            existing["current_price_eur"] != new_price
            or existing["current_availability"] != new_availability
        )

        first_seen = existing["first_seen_at"] or now

        cur.execute("""
            UPDATE merchant_products
            SET merchant = ?,
                merchant_reference = ?,
                manufacturer_reference = ?,
                brand = ?,
                name = ?,
                variant = ?,
                source_url = ?,
                current_price_eur = ?,
                current_availability = ?,
                first_seen_at = ?,
                last_seen_at = ?
            WHERE id = ?
        """, (
            merchant,
            merchant_reference,
            manufacturer_reference,
            row.get("brand"),
            row.get("name"),
            row.get("variant"),
            source_url,
            new_price,
            new_availability,
            first_seen,
            now,
            product_id,
        ))

    if changed:
        cur.execute("""
            INSERT INTO offer_history (
                merchant_product_id,
                observed_at,
                price_eur,
                availability,
                source
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            product_id,
            now,
            new_price,
            new_availability,
            source,
        ))

    con.commit()
    con.close()
    return product_id, changed
