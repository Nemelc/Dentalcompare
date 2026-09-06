import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote

CATEGORY_RULES = [
    ("Endodontie", ["endodont", "canalaire", "gutta", "lime", "apex", "endo"]),
    ("Restauration", ["restauration", "composite", "adhes", "bond", "ciment", "matrice", "coffrage", "fond de cavite"]),
    ("Empreinte & Prothèse", ["empreinte", "silicone", "alginate", "retraction", "prothese", "resine", "platre", "laboratoire"]),
    ("Chirurgie & Implantologie", ["implant", "chirurg", "suture", "greffe", "osteot", "elevation", "bistouri"]),
    ("Anesthésie", ["anesth", "aiguille dentaire", "carpule"]),
    ("Prophylaxie", ["prophyl", "polissage", "aeropol", "fluor", "brossette"]),
    ("Hygiène & Stérilisation", ["desinfection", "steril", "autoclave", "thermodesinfect", "hygiene", "nettoy", "lingette"]),
    ("Instrumentation", ["instrument", "fraise", "contre-angle", "turbine", "insert", "detartreur", "ultrason"]),
    ("Radiologie & Numérique", ["radiograph", "rvg", "scanner", "cbct", "camera", "numerique", "cfao", "imprimante 3d"]),
    ("Équipement", ["equipement", "fauteuil", "aspiration", "compresseur", "mobilier", "lampe", "moteur"]),
    ("Consommables", ["gant", "masque", "champ", "canule", "gobelet", "rouleau", "sachet"]),
    ("Blanchiment", ["blanch", "opalescence", "white class"]),
]

INVALID_REFS = {"", ".", "-", "--", "n/a", "na", "n.c.", "nc", "n/c", "s/o", "aucun", "divers"}


def norm(value):
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_ref(value):
    if value is None:
        return None
    s = str(value).strip()
    return None if not s or s.lower() in INVALID_REFS else s


def dental_category(product):
    hay = norm(" ".join(str(product.get(k) or "") for k in ("category", "name", "brand")))
    for label, keys in CATEGORY_RULES:
        if any(k in hay for k in keys):
            return label
    category = str(product.get("category") or "")
    if category:
        first = category.split(">")[0].strip()
        if first:
            return first
    return "Autres"


def canonical_url(url):
    return unquote(str(url or "")).rstrip("/").lower()


def main():
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/mega_catalog_final.json")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/mega_catalog_test.json")
    report_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("data/mega_qc_report.json")

    payload = json.loads(source.read_text(encoding="utf-8"))
    products = payload.get("products", [])

    by_ean = defaultdict(list)
    by_mref = defaultdict(list)
    by_url = defaultdict(list)
    by_merchant_ref = defaultdict(list)
    category_counts = Counter()

    prepared = []
    for idx, raw in enumerate(products):
        p = dict(raw)
        p["id"] = f"mega-{idx+1}"
        p["manufacturer_reference"] = clean_ref(p.get("manufacturer_reference"))
        p["ean"] = clean_ref(p.get("ean"))
        p["merchant_reference"] = clean_ref(p.get("merchant_reference"))
        p["dental_category"] = dental_category(p)
        category_counts[p["dental_category"]] += 1

        flags = []
        if p.get("price_eur") is None: flags.append("missing_price")
        if not p.get("image_url"): flags.append("missing_image")
        if not p.get("brand"): flags.append("missing_brand")
        if not p.get("category"): flags.append("missing_category")
        if not p.get("merchant_reference"): flags.append("missing_merchant_reference")
        if not p.get("manufacturer_reference") and not p.get("ean"): flags.append("weak_matching_identifiers")
        if "destockage" in norm(p.get("category")): flags.append("destockage_review")
        p["qc_flags"] = flags
        prepared.append(p)

        if p.get("ean"): by_ean[norm(p["ean"])].append(idx)
        if p.get("manufacturer_reference") and p.get("brand"):
            by_mref[(norm(p["brand"]), norm(p["manufacturer_reference"]))].append(idx)
        if p.get("merchant_reference"): by_merchant_ref[norm(p["merchant_reference"])].append(idx)
        if p.get("source_url"): by_url[canonical_url(p["source_url"])].append(idx)

    duplicate_groups = []
    def add_groups(kind, groups):
        for key, ids in groups.items():
            if key and len(ids) > 1:
                duplicate_groups.append({"kind": kind, "key": str(key), "product_indexes": ids, "count": len(ids)})
                for i in ids:
                    prepared[i]["qc_flags"].append(f"duplicate_{kind}")

    add_groups("ean", by_ean)
    add_groups("manufacturer_reference", by_mref)
    add_groups("merchant_reference", by_merchant_ref)
    add_groups("url", by_url)

    report = {
        "source": source.name,
        "total_products": len(prepared),
        "with_price": sum(p.get("price_eur") is not None for p in prepared),
        "with_image": sum(bool(p.get("image_url")) for p in prepared),
        "with_brand": sum(bool(p.get("brand")) for p in prepared),
        "with_category": sum(bool(p.get("category")) for p in prepared),
        "with_merchant_reference": sum(bool(p.get("merchant_reference")) for p in prepared),
        "with_manufacturer_reference": sum(bool(p.get("manufacturer_reference")) for p in prepared),
        "with_ean": sum(bool(p.get("ean")) for p in prepared),
        "dental_categories": dict(category_counts.most_common()),
        "duplicate_groups": duplicate_groups,
        "products_with_qc_flags": sum(bool(p["qc_flags"]) for p in prepared),
    }

    result = {
        "source": "dentalcompare_mega_test_catalog_v1",
        "total_products": len(prepared),
        "categories": list(category_counts.keys()),
        "products": prepared,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Produits préparés: {len(prepared)}")
    print(f"Avec prix: {report['with_price']}")
    print(f"Avec image: {report['with_image']}")
    print(f"Catégories DentalCompare: {len(category_counts)}")
    print(f"Groupes de doublons à contrôler: {len(duplicate_groups)}")
    print(f"Catalogue test: {output}")
    print(f"Rapport QC: {report_path}")


if __name__ == "__main__":
    main()
