from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INCOMING = Path(__file__).resolve().parent / "incoming"

BAD_REFS = {"", "nom", "name", "r", "ref", "reference", "none", "null"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def clean_ref(value: Any) -> str | None:
    ref = clean_text(value)
    if ref.lower() in BAD_REFS:
        return None
    return ref or None


def clean_price(value: Any) -> float | None:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n) or n <= 0:
        return None
    return round(n, 2)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def latest(patterns: list[str]) -> Path | None:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(INCOMING.glob(pattern))
    files = [p for p in files if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def extract_products(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        products = payload.get("products")
        if isinstance(products, list):
            return [x for x in products if isinstance(x, dict)]
    raise ValueError("Format JSON non reconnu: aucune liste de produits")


def normalize_product(row: dict[str, Any], merchant: str) -> dict[str, Any] | None:
    name = clean_text(row.get("name"))
    image = clean_text(row.get("image_url") or row.get("image"))
    price = clean_price(row.get("price_eur", row.get("price")))

    # Règle publique: nom + prix valide + image. Le stock est facultatif.
    if not name or price is None or not image:
        return None

    result = {
        "merchant": merchant,
        "merchant_reference": clean_ref(row.get("merchant_reference")),
        "manufacturer_reference": clean_ref(row.get("manufacturer_reference")),
        "ean": clean_ref(row.get("ean")),
        "name": name,
        "brand": clean_text(row.get("brand")) or None,
        "category": clean_text(row.get("category")) or None,
        "variant": clean_text(row.get("variant")) or None,
        "packaging": clean_text(row.get("packaging")) or None,
        "price_eur": price,
        "availability": clean_text(row.get("availability")) or None,
        "image_url": image,
        "source_url": clean_text(row.get("source_url") or row.get("url")) or None,
        "captured_at": clean_text(row.get("captured_at")) or None,
    }
    return result


def dedupe(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for p in products:
        if p.get("merchant_reference"):
            key = (p["merchant"], "merchant_ref", p["merchant_reference"].lower())
        elif p.get("manufacturer_reference"):
            key = (
                p["merchant"],
                "manufacturer_ref",
                p["manufacturer_reference"].lower(),
                (p.get("name") or "").lower(),
            )
        elif p.get("ean"):
            key = (p["merchant"], "ean", p["ean"])
        else:
            key = (
                p["merchant"],
                "fallback",
                (p.get("brand") or "").lower(),
                (p.get("name") or "").lower(),
                p.get("price_eur"),
            )
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def build(path: Path, merchant: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    raw = extract_products(load_json(path))
    normalized = [normalize_product(x, merchant) for x in raw]
    visible = dedupe([x for x in normalized if x is not None])
    stats = {
        "raw": len(raw),
        "visible": len(visible),
        "with_availability": sum(bool(x.get("availability")) for x in visible),
        "with_merchant_reference": sum(bool(x.get("merchant_reference")) for x in visible),
        "with_manufacturer_reference": sum(bool(x.get("manufacturer_reference")) for x in visible),
        "with_ean": sum(bool(x.get("ean")) for x in visible),
    }
    return visible, stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gacd", type=Path)
    parser.add_argument("--mega", type=Path)
    args = parser.parse_args()

    gacd = args.gacd or latest(["gacd_catalog_v5_*.json", "gacd*_raw*.json", "gacd*.json"])
    mega = args.mega or latest(["mega_catalog_final*.json", "mega*_raw*.json", "mega*.json"])

    report: dict[str, Any] = {}

    if gacd:
        products, stats = build(gacd, "GACD")
        save_json(ROOT / "gacd_catalog_visible.json", products)
        report["GACD"] = {"source": str(gacd), **stats}
        print(f"GACD: {stats['visible']} references publiques / {stats['raw']} brutes")
    else:
        print("GACD: aucun nouveau fichier brut, catalogue public conserve")

    if mega:
        products, stats = build(mega, "Mega Dental")
        save_json(ROOT / "mega_catalog_visible_test.json", products)
        report["Mega Dental"] = {"source": str(mega), **stats}
        print(f"Mega Dental: {stats['visible']} references publiques / {stats['raw']} brutes")
    else:
        print("Mega Dental: aucun nouveau fichier brut, catalogue public conserve")

    if not gacd and not mega:
        raise SystemExit("Aucun fichier de capture trouve dans backend/snapshot/incoming")

    save_json(Path(__file__).resolve().parent / "data" / "last_refresh_report.json", report)


if __name__ == "__main__":
    main()
