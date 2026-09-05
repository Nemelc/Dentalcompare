import json
import sys
from pathlib import Path

INVALID_REFS = {
    "", ".", "-", "--", "n/a", "na", "n.c.", "nc", "n/c", "s/o",
    "aucun", "non renseigne", "non renseigné", "divers"
}


def clean_ref(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in INVALID_REFS:
        return None
    if len(value) > 80:
        return None
    return value


def clean_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python merge_mega_product_enrichment.py <mega_product_enrichment.json> "
            "[catalogue_entree.json] [catalogue_sortie.json]"
        )

    enrichment_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("data/mega_catalog_enriched.json")
    output_path = Path(sys.argv[3]) if len(sys.argv) >= 4 else Path("data/mega_catalog_product_enriched.json")

    base = load_json(base_path)
    enrichment = load_json(enrichment_path)

    base_products = base.get("products", base if isinstance(base, list) else [])
    enriched_products = enrichment.get("products", enrichment if isinstance(enrichment, list) else [])

    by_url = {p.get("source_url"): p for p in base_products if p.get("source_url")}

    matched = 0
    manufacturer_refs_added = 0
    eans_added = 0
    images_added = 0
    categories_added = 0
    availability_added = 0
    invalid_manufacturer_refs_ignored = 0

    for incoming in enriched_products:
        url = incoming.get("source_url")
        target = by_url.get(url)
        if not target:
            continue
        matched += 1

        incoming_mref_raw = incoming.get("manufacturer_reference")
        incoming_mref = clean_ref(incoming_mref_raw)
        if incoming_mref_raw is not None and not incoming_mref:
            invalid_manufacturer_refs_ignored += 1

        if incoming_mref and not clean_ref(target.get("manufacturer_reference")):
            target["manufacturer_reference"] = incoming_mref
            manufacturer_refs_added += 1

        incoming_ean = clean_ref(incoming.get("ean"))
        if incoming_ean and not clean_ref(target.get("ean")):
            target["ean"] = incoming_ean
            eans_added += 1

        incoming_merchant_ref = clean_ref(incoming.get("merchant_reference"))
        if incoming_merchant_ref and not clean_ref(target.get("merchant_reference")):
            target["merchant_reference"] = incoming_merchant_ref

        for field, counter_name in [
            ("image_url", "image"),
            ("category", "category"),
            ("availability", "availability"),
            ("brand", None),
        ]:
            value = clean_text(incoming.get(field))
            if value and not clean_text(target.get(field)):
                target[field] = value
                if counter_name == "image": images_added += 1
                elif counter_name == "category": categories_added += 1
                elif counter_name == "availability": availability_added += 1

        target["product_enriched_at"] = incoming.get("captured_at") or enrichment.get("captured_at")

    # Defensive cleanup: never let known placeholder refs survive into matching.
    for p in base_products:
        if p.get("manufacturer_reference") is not None and not clean_ref(p.get("manufacturer_reference")):
            p["manufacturer_reference"] = None

    result = dict(base) if isinstance(base, dict) else {}
    result["products"] = base_products
    result["product_enrichment_source"] = enrichment.get("source") if isinstance(enrichment, dict) else None
    result["product_enrichment_captured_at"] = enrichment.get("captured_at") if isinstance(enrichment, dict) else None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Catalogue de base: {len(base_products)}")
    print(f"Fiches d'enrichissement: {len(enriched_products)}")
    print(f"Fiches rapprochées par URL: {matched}")
    print(f"Références fabricant ajoutées: {manufacturer_refs_added}")
    print(f"EAN ajoutés: {eans_added}")
    print(f"Images ajoutées: {images_added}")
    print(f"Catégories ajoutées: {categories_added}")
    print(f"Disponibilités ajoutées: {availability_added}")
    print(f"Fausses références fabricant ignorées: {invalid_manufacturer_refs_ignored}")
    print(f"Catalogue créé: {output_path}")


if __name__ == "__main__":
    main()
