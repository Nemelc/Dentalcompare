import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, unquote

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MEGA_HOSTS = {"megadental.fr", "www.megadental.fr"}
REF_RE = re.compile(r"-(\d{2,5}-\d{2,5})\.html$", re.I)


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def title_from_url(url):
    path = unquote(urlparse(url).path)
    slug = Path(path).name
    slug = re.sub(r"\.html$", "", slug, flags=re.I)
    slug = REF_RE.sub("", slug + ".html")[:-5] if REF_RE.search(slug + ".html") else slug
    slug = re.sub(r"[-_]+", " ", slug)
    slug = clean(slug)
    if not slug:
        return "Produit Mega Dental"
    # Capitalisation légère sans casser les acronymes déjà présents.
    words = []
    for word in slug.split():
        if word.isupper() and len(word) <= 6:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def merchant_ref_from_url(url):
    m = REF_RE.search(urlparse(url).path)
    return m.group(1) if m else None


def parse_sitemap(path, priority="1.0"):
    root = ET.parse(path).getroot()
    out = []
    for node in root.findall("sm:url", NS):
        loc_node = node.find("sm:loc", NS)
        if loc_node is None or not loc_node.text:
            continue
        url = loc_node.text.strip()
        parsed = urlparse(url)
        if parsed.hostname not in MEGA_HOSTS or not parsed.path.lower().endswith(".html"):
            continue
        if priority is not None:
            p_node = node.find("sm:priority", NS)
            p_value = clean(p_node.text if p_node is not None else "")
            if p_value != priority:
                continue
        out.append(url)
    return out


def load_checkpoint(path):
    rich = {}
    if not path:
        return rich
    p = Path(path)
    if not p.exists():
        return rich
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        url = obj.get("source_url")
        if url:
            rich[url] = obj
    return rich


def merge_product(base, richer):
    if not richer:
        return base
    merged = dict(base)
    # Une valeur réellement collectée prime sur la valeur dérivée du sitemap.
    for key, value in richer.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    merged["source_url"] = base["source_url"]
    merged["merchant"] = "Mega Dental"
    merged["catalog_source"] = "sitemap+checkpoint"
    return merged


def main():
    ap = argparse.ArgumentParser(
        description="Construit le catalogue Mega Dental depuis les sitemaps locaux, sans ouvrir les fiches produits."
    )
    ap.add_argument("sitemaps", nargs="+", help="Un ou plusieurs fichiers sitemap XML Mega Dental")
    ap.add_argument("--output", default="data/mega_catalog_sitemap.json")
    ap.add_argument("--checkpoint", default="data/mega_bulk_checkpoint.jsonl")
    ap.add_argument("--priority", default="1.0", help="Priorité sitemap à conserver; utiliser 'all' pour tout garder")
    args = ap.parse_args()

    urls = []
    for source in args.sitemaps:
        found = parse_sitemap(source, None if args.priority.lower() == "all" else args.priority)
        print(f"{Path(source).name}: {len(found)} URL produit(s)")
        urls.extend(found)

    urls = list(dict.fromkeys(urls))
    checkpoint = load_checkpoint(args.checkpoint)

    products = []
    enriched = 0
    with_ref = 0
    for url in urls:
        merchant_ref = merchant_ref_from_url(url)
        if merchant_ref:
            with_ref += 1
        base = {
            "merchant": "Mega Dental",
            "merchant_reference": merchant_ref,
            "manufacturer_reference": None,
            "ean": None,
            "name": title_from_url(url),
            "brand": None,
            "category": None,
            "variant": None,
            "packaging": None,
            "price_eur": None,
            "availability": None,
            "image_url": None,
            "source_url": url,
            "captured_at": utc_now(),
            "catalog_source": "sitemap",
        }
        richer = checkpoint.get(url)
        if richer:
            enriched += 1
        products.append(merge_product(base, richer))

    payload = {
        "source": "mega_dental_sitemap_catalog_v1",
        "captured_at": utc_now(),
        "sitemap_files": [str(Path(x)) for x in args.sitemaps],
        "priority_filter": args.priority,
        "total_products": len(products),
        "merchant_reference_from_url": with_ref,
        "enriched_from_checkpoint": enriched,
        "products": products,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Catalogue créé: {out}")
    print(f"Produits: {len(products)}")
    print(f"Références Mega déduites de l'URL: {with_ref}")
    print(f"Produits enrichis avec le checkpoint existant: {enriched}")
    print("Aucune fiche produit n'a été ouverte par ce script.")


if __name__ == "__main__":
    main()
