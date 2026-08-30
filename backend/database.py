import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from models import MerchantProduct
from matcher import compare
from normalize import normalize_reference, normalize_brand
from config import AUTO_MATCH_THRESHOLD, REVIEW_MATCH_THRESHOLD

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_name TEXT NOT NULL,
  brand TEXT,
  manufacturer_reference TEXT,
  ean TEXT,
  category TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_mref ON products(manufacturer_reference);
CREATE INDEX IF NOT EXISTS idx_product_ean ON products(ean);

CREATE TABLE IF NOT EXISTS merchant_products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  merchant TEXT NOT NULL,
  merchant_reference TEXT,
  manufacturer_reference TEXT,
  ean TEXT,
  name TEXT NOT NULL,
  brand TEXT,
  source_category TEXT,
  variant TEXT,
  packaging TEXT,
  url TEXT NOT NULL,
  image_url TEXT,
  availability TEXT,
  attributes_json TEXT,
  last_seen_at TEXT NOT NULL,
  UNIQUE(merchant, merchant_reference),
  UNIQUE(merchant, url, name)
);

CREATE TABLE IF NOT EXISTS offers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  merchant_product_id INTEGER NOT NULL REFERENCES merchant_products(id),
  price REAL,
  currency TEXT NOT NULL DEFAULT 'EUR',
  availability TEXT,
  scraped_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offer_mp_time ON offers(merchant_product_id, scraped_at DESC);

CREATE TABLE IF NOT EXISTS match_review (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  merchant TEXT NOT NULL,
  merchant_reference TEXT,
  candidate_product_id INTEGER,
  score REAL NOT NULL,
  reasons TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
);
"""


class Database:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def find_existing_product(self, p: MerchantProduct):
        cur = self.conn.cursor()
        ean = normalize_reference(p.ean)
        mref = normalize_reference(p.manufacturer_reference)
        if ean:
            row = cur.execute("SELECT * FROM products WHERE ean=? LIMIT 1", (ean,)).fetchone()
            if row: return row, 1.0, "ean"
        if mref:
            rows = cur.execute("SELECT * FROM products WHERE manufacturer_reference=?", (mref,)).fetchall()
            if len(rows) == 1: return rows[0], .99, "manufacturer_reference"

        # Candidate shortlist: same normalized brand when possible, otherwise recent catalog.
        rows = cur.execute("SELECT * FROM products ORDER BY id DESC LIMIT 3000").fetchall()
        best = None
        for row in rows:
            candidate = MerchantProduct(
                merchant="DentalCompare", url="", name=row["canonical_name"],
                manufacturer_reference=row["manufacturer_reference"], ean=row["ean"], brand=row["brand"]
            )
            result = compare(p, candidate, AUTO_MATCH_THRESHOLD, REVIEW_MATCH_THRESHOLD)
            if best is None or result.score > best[1].score:
                best = (row, result)
        if best:
            return best[0], best[1].score, best[1]
        return None, 0.0, None

    def ingest(self, p: MerchantProduct):
        now = self._now()
        # Update existing merchant SKU first.
        row = None
        if p.merchant_reference:
            row = self.conn.execute(
                "SELECT * FROM merchant_products WHERE merchant=? AND merchant_reference=?",
                (p.merchant, p.merchant_reference)
            ).fetchone()
        if not row:
            row = self.conn.execute(
                "SELECT * FROM merchant_products WHERE merchant=? AND url=? AND name=?",
                (p.merchant, p.url, p.name)
            ).fetchone()

        if row:
            product_id = row["product_id"]
            mp_id = row["id"]
            self.conn.execute("""UPDATE merchant_products SET manufacturer_reference=?, ean=?, name=?, brand=?,
                source_category=?, variant=?, packaging=?, image_url=?, availability=?, attributes_json=?, last_seen_at=? WHERE id=?""",
                (normalize_reference(p.manufacturer_reference) or None, normalize_reference(p.ean) or None,
                 p.name, p.brand, p.category, p.variant, p.packaging, p.image_url, p.availability,
                 json.dumps(p.attributes, ensure_ascii=False), now, mp_id))
        else:
            candidate, score, why = self.find_existing_product(p)
            auto = False
            if candidate:
                if why in ("ean", "manufacturer_reference"):
                    auto = True
                elif getattr(why, "decision", None) == "auto_match":
                    auto = True

            if auto:
                product_id = candidate["id"]
            else:
                cur = self.conn.execute("""INSERT INTO products(canonical_name,brand,manufacturer_reference,ean,category,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)""", (p.name, p.brand, normalize_reference(p.manufacturer_reference) or None,
                    normalize_reference(p.ean) or None, None, now, now))
                product_id = cur.lastrowid
                if candidate and getattr(why, "decision", None) == "review":
                    self.conn.execute("""INSERT INTO match_review(merchant,merchant_reference,candidate_product_id,score,reasons,payload_json,created_at)
                        VALUES(?,?,?,?,?,?,?)""", (p.merchant, p.merchant_reference, candidate["id"], score,
                        json.dumps(why.reasons, ensure_ascii=False), json.dumps(p.__dict__, ensure_ascii=False), now))

            cur = self.conn.execute("""INSERT INTO merchant_products(product_id,merchant,merchant_reference,manufacturer_reference,ean,name,brand,
                source_category,variant,packaging,url,image_url,availability,attributes_json,last_seen_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (product_id,p.merchant,p.merchant_reference,
                normalize_reference(p.manufacturer_reference) or None, normalize_reference(p.ean) or None,p.name,p.brand,p.category,
                p.variant,p.packaging,p.url,p.image_url,p.availability,json.dumps(p.attributes,ensure_ascii=False),now))
            mp_id = cur.lastrowid

        self.conn.execute("INSERT INTO offers(merchant_product_id,price,currency,availability,scraped_at) VALUES(?,?,?,?,?)",
                          (mp_id,p.price,p.currency,p.availability,now))
        self.conn.commit()
        return product_id
