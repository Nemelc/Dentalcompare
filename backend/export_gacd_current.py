import json
from pathlib import Path

from database_v2 import connect, init_db

OUT = Path(__file__).parent / "data" / "gacd_current.json"


def main():
    init_db()
    con = connect()

    rows = con.execute("""
        SELECT
            merchant,
            merchant_reference,
            manufacturer_reference,
            brand,
            name,
            variant,
            source_url,
            current_price_eur AS price_eur,
            current_availability AS availability,
            last_seen_at
        FROM merchant_products
        WHERE merchant = 'GACD'
        ORDER BY brand, name, variant
    """).fetchall()

    payload = [dict(r) for r in rows]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"{len(payload)} produits GACD exportés vers {OUT}")
    con.close()


if __name__ == "__main__":
    main()
