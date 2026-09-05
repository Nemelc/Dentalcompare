import argparse
import json
from pathlib import Path


def load_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"products": data}
    if not isinstance(data, dict):
        raise ValueError(f"Format JSON invalide: {path}")
    return data


def score(product):
    keys = (
        "merchant_reference", "manufacturer_reference", "ean", "brand",
        "category", "variant", "packaging", "price_eur", "availability",
        "image_url", "name",
    )
    return sum(1 for k in keys if product.get(k) not in (None, "", [], {}))


def merge(base, richer):
    out = dict(base)
    for k, v in richer.items():
        if v not in (None, "", [], {}):
            out[k] = v
    out["source_url"] = base.get("source_url") or richer.get("source_url")
    out["merchant"] = "Mega Dental"
    return out


def main():
    ap = argparse.ArgumentParser(description="Fusionne une capture de listings Mega Dental avec le catalogue sitemap.")
    ap.add_argument("capture", help="JSON créé par browser_mega_all_brands_capture.js ou browser_mega_listing_capture.js")
    ap.add_argument("--catalog", default="data/mega_catalog_sitemap.json")
    ap.add_argument("--output", default="data/mega_catalog_enriched.json")
    args = ap.parse_args()

    catalog = load_json(args.catalog)
    capture = load_json(args.capture)
    base_products = catalog.get("products", [])
    captured = capture.get("products", [])

    by_url = {p.get("source_url"): p for p in base_products if p.get("source_url")}
    best_capture = {}
    for p in captured:
        url = p.get("source_url")
        if not url:
            continue
        old = best_capture.get(url)
        if old is None or score(p) >= score(old):
            best_capture[url] = p

    enriched = 0
    added = 0
    for url, p in best_capture.items():
        if url in by_url:
            by_url[url] = merge(by_url[url], p)
            enriched += 1
        else:
            by_url[url] = p
            added += 1

    products = sorted(by_url.values(), key=lambda p: (p.get("name") or "").casefold())
    payload = dict(catalog)
    payload["source"] = "mega_dental_sitemap_plus_listing_capture_v1"
    payload["products"] = products
    payload["total_products"] = len(products)
    payload["listing_capture_file"] = str(Path(args.capture))
    payload["enriched_from_listing_capture"] = enriched
    payload["added_from_listing_capture"] = added

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with_price = sum(1 for p in products if p.get("price_eur") is not None)
    with_brand = sum(1 for p in products if p.get("brand"))
    with_ref = sum(1 for p in products if p.get("merchant_reference"))
    with_image = sum(1 for p in products if p.get("image_url"))
    print(f"Catalogue de base: {len(base_products)}")
    print(f"Produits dans la capture: {len(captured)}")
    print(f"Produits enrichis: {enriched}")
    print(f"Produits ajoutés hors sitemap: {added}")
    print(f"Total final: {len(products)}")
    print(f"Avec référence Mega: {with_ref}")
    print(f"Avec marque: {with_brand}")
    print(f"Avec prix: {with_price}")
    print(f"Avec image URL: {with_image}")
    print(f"Catalogue enrichi créé: {out}")


if __name__ == "__main__":
    main()
