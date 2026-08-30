import csv
import sys
from pathlib import Path

from daily_db import init_db, upsert_product

DEFAULT_CSV = Path(__file__).parent / "data" / "catalogue_gacd_seed.csv"


def parse_float(value):
    if value is None:
        return None
    value = str(value).strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV

    if not csv_path.exists():
        raise SystemExit(f"CSV introuvable : {csv_path}")

    init_db()

    total = 0
    changed = 0

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            row["price_eur"] = parse_float(row.get("price_eur"))
            _, was_changed = upsert_product(row, source="seed_import")
            changed += int(was_changed)

    print(f"{total} lignes importées.")
    print(f"{changed} création(s)/changement(s) enregistrés.")


if __name__ == "__main__":
    main()
