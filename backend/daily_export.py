import json
from pathlib import Path

from daily_db import connect, init_db

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
            first_seen_at,
            last_seen_at
        FROM products
        WHERE merchant = 'GACD'
        ORDER BY brand, name, variant
    """).fetchall()

    data = [dict(r) for r in rows]
    OUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"{len(data)} produits GACD exportés vers {OUT}")
    con.close()


if __name__ == "__main__":
    main()
