import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.megadental.fr"
BRANDS_INDEX = BASE + "/brands/toutes-les-marques"
UA = "Mozilla/5.0 (compatible; DentalCompare/1.0; +https://github.com/Nemelc/Dentalcompare)"
PRICE_RE = re.compile(r"(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[,.]\d{2})?)\s*€")
REF_RE = re.compile(r"\bRéf\.?\s*[:.]?\s*([A-Za-z0-9._/-]+)", re.I)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def money(s):
    if not s:
        return None
    m = PRICE_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def canonical(url):
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k == "p"]
    return urlunparse((p.scheme or "https", p.netloc or "www.megadental.fr", p.path, "", urlencode(q), ""))


def get(session, url, timeout=25):
    r = session.get(url, timeout=timeout, allow_redirects=True)
    if r.status_code in (403, 429):
        raise RuntimeError(f"Protection HTTP {r.status_code} sur {url}")
    r.raise_for_status()
    return r.text


def brand_urls(session):
    html = get(session, BRANDS_INDEX)
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select('a[href*="/brands/"]'):
        u = urljoin(BASE, a.get("href"))
        path = urlparse(u).path.rstrip("/")
        if path == "/brands/toutes-les-marques" or path == "/brands":
            continue
        if path.startswith("/brands/"):
            out.append(canonical(u))
    return list(dict.fromkeys(out))


def product_cards(soup):
    cards = soup.select("li.product-item, .product-item, .products-grid .item, .product-item-info")
    # Évite les doublons imbriqués: garder seulement les éléments contenant un lien produit.
    return [c for c in cards if c.select_one("a.product-item-link, a[href$='.html']")]


def parse_card(card, brand_hint=None):
    link = card.select_one("a.product-item-link") or card.select_one("a[href$='.html']")
    if not link:
        return None
    url = canonical(urljoin(BASE, link.get("href")))
    if urlparse(url).netloc not in {"megadental.fr", "www.megadental.fr"}:
        return None

    name = clean(link.get_text(" ", strip=True))
    text = clean(card.get_text(" ", strip=True))
    if not name:
        return None

    ref = None
    m = REF_RE.search(text)
    if m:
        ref = m.group(1).strip(".,;:")

    price = None
    el = card.select_one("[data-price-amount]")
    if el:
        try:
            price = float(el.get("data-price-amount"))
        except Exception:
            pass
    if price is None:
        price = money(text)

    brand = brand_hint
    brand_el = card.select_one(".brand, .product-brand, [class*='brand']")
    if brand_el:
        b = clean(brand_el.get_text(" ", strip=True))
        if b:
            brand = b

    img = card.select_one("img")
    image_url = None
    if img:
        image_url = img.get("data-src") or img.get("data-original") or img.get("src")
        if image_url:
            image_url = urljoin(BASE, image_url)

    return {
        "merchant": "Mega Dental",
        "source_url": url,
        "name": name,
        "merchant_reference": ref,
        "manufacturer_reference": None,
        "ean": None,
        "brand": brand,
        "category": None,
        "variant": None,
        "packaging": None,
        "price_eur": price,
        "availability": None,
        "image_url": image_url,
        "catalog_source": "public_brand_listing",
    }


def brand_name_from_page(soup, url):
    h1 = soup.select_one("h1")
    txt = clean(h1.get_text(" ", strip=True) if h1 else "")
    m = re.search(r"marque\s*:\s*(.+)$", txt, re.I)
    if m:
        return clean(m.group(1))
    return urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ").upper()


def next_page(soup, current_url):
    nxt = soup.select_one("a.action.next, a.next, .pages-item-next a")
    if nxt and nxt.get("href"):
        u = canonical(urljoin(BASE, nxt.get("href")))
        if urlparse(u).path == urlparse(current_url).path:
            return u
    return None


def merge_catalog(catalog_path, listing_products, output_path):
    payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    products = payload.get("products", [])
    by_url = {canonical(p.get("source_url", "")): p for p in products if p.get("source_url")}
    by_ref = {str(p.get("merchant_reference")): p for p in products if p.get("merchant_reference")}
    matched = 0

    for item in listing_products:
        target = by_url.get(canonical(item["source_url"]))
        if target is None and item.get("merchant_reference"):
            target = by_ref.get(str(item["merchant_reference"]))
        if target is None:
            continue
        changed = False
        for k, v in item.items():
            if v not in (None, "", [], {}) and (target.get(k) in (None, "", [], {}) or k in {"name", "price_eur", "brand", "image_url"}):
                target[k] = v
                changed = True
        if changed:
            target["catalog_source"] = "sitemap+public_brand_listing"
            matched += 1

    payload["listing_enriched_products"] = matched
    payload["listing_records_collected"] = len(listing_products)
    payload["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return matched


def main():
    ap = argparse.ArgumentParser(description="Enrichit le catalogue Mega Dental via les pages publiques de marques, sans ouvrir les fiches produit.")
    ap.add_argument("--catalog", default="data/mega_catalog_sitemap.json")
    ap.add_argument("--output", default="data/mega_catalog_enriched.json")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--brand-limit", type=int, default=0, help="0 = toutes les marques")
    ap.add_argument("--page-limit", type=int, default=100)
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})

    brands = brand_urls(s)
    if args.brand_limit:
        brands = brands[: args.brand_limit]
    print(f"Marques publiques découvertes: {len(brands)}")

    collected = {}
    pages = 0
    for i, brand_url in enumerate(brands, 1):
        url = brand_url
        seen = set()
        while url and url not in seen and len(seen) < args.page_limit:
            seen.add(url)
            html = get(s, url)
            soup = BeautifulSoup(html, "lxml")
            brand = brand_name_from_page(soup, brand_url)
            cards = product_cards(soup)
            for card in cards:
                p = parse_card(card, brand)
                if p:
                    collected[canonical(p["source_url"])] = p
            pages += 1
            print(f"[{i}/{len(brands)}] {brand} - page {len(seen)}: {len(cards)} produit(s), total unique {len(collected)}")
            url = next_page(soup, url)
            if url:
                time.sleep(args.delay)
        time.sleep(args.delay)

    out_list = Path("data/mega_brand_listing_records.json")
    out_list.parent.mkdir(parents=True, exist_ok=True)
    out_list.write_text(json.dumps({"products": list(collected.values())}, ensure_ascii=False, indent=2), encoding="utf-8")
    matched = merge_catalog(args.catalog, list(collected.values()), args.output)

    print(f"Pages de listing lues: {pages}")
    print(f"Produits uniques collectés sur listings: {len(collected)}")
    print(f"Produits du catalogue enrichis: {matched}")
    print(f"Catalogue enrichi créé: {args.output}")
    print("Aucune fiche produit individuelle n'a été ouverte.")


if __name__ == "__main__":
    main()
