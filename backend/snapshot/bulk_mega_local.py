import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MEGA_HOSTS = {"www.megadental.fr", "megadental.fr"}
CHALLENGE_MARKERS = [
    "just a moment",
    "checking your browser",
    "verify you are human",
    "cf-chl-",
    "challenges.cloudflare.com",
    "captcha",
]


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_price(text):
    if not text:
        return None
    m = re.search(r"(\d{1,5}(?:[ .\u202f]\d{3})*[,.]\d{2})\s*€", clean(text))
    if not m:
        return None
    raw = re.sub(r"[ .\u202f]", "", m.group(1)).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def load_urls(path):
    urls = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        u = line.strip()
        if not u or u.startswith("#"):
            continue
        parsed = urlparse(u)
        if parsed.hostname not in MEGA_HOSTS:
            continue
        urls.append(u)
    return list(dict.fromkeys(urls))


def load_done(jsonl_path):
    done = set()
    p = Path(jsonl_path)
    if not p.exists():
        return done
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
            if obj.get("source_url"):
                done.add(obj["source_url"])
        except Exception:
            pass
    return done


def is_challenge(page):
    try:
        title = clean(page.title()).lower()
        html = page.content().lower()
    except Exception:
        return True
    haystack = title + "\n" + html[:200000]
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


def first_text(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                value = clean(el.inner_text() or el.get_attribute("content") or "")
                if value:
                    return value
        except Exception:
            pass
    return None


def extract_product(page):
    body_text = clean(page.locator("body").inner_text())
    title = clean(page.locator("h1").first.inner_text()) if page.locator("h1").count() else clean(page.title())

    price = None
    for sel in [
        '[itemprop="price"]',
        '[data-price-type="finalPrice"] .price',
        '.special-price .price',
        '.price-box .price-final_price .price',
        '.price-box .price',
    ]:
        try:
            el = page.query_selector(sel)
            if not el:
                continue
            attr = el.get_attribute("content") or el.get_attribute("data-price-amount")
            if attr and re.fullmatch(r"\d+(?:\.\d+)?", attr):
                price = float(attr)
                break
            price = parse_price(el.inner_text())
            if price is not None:
                break
        except Exception:
            pass

    merchant_reference = first_text(page, [
        '[itemprop="sku"]',
        '.product.attribute.sku .value',
        '.product-info-main .sku .value',
    ])
    if not merchant_reference:
        try:
            el = page.query_selector('[data-product-sku]')
            if el:
                merchant_reference = clean(el.get_attribute('data-product-sku') or "") or None
        except Exception:
            pass

    manufacturer_reference = None
    m = re.search(r"\bMPN\s*:\s*([^|]{1,60})", body_text, re.I)
    if m:
        v = clean(m.group(1))
        v = re.split(r"\b(?:En stock|Disponible|Rupture|Sur commande)\b", v, maxsplit=1, flags=re.I)[0].strip()
        if v and not re.fullmatch(r"(?:S/?O|N/?A|NC|Non renseigné)", v, re.I):
            manufacturer_reference = v
    if not manufacturer_reference:
        m = re.search(r"(?:Réf(?:érence)?\s+fabricant|Code\s+fabricant)\s*:?\s*([A-Z0-9._+/-]+)", body_text, re.I)
        if m:
            manufacturer_reference = m.group(1)

    ean = None
    m = re.search(r"(?:EAN|GTIN)\s*:?\s*(\d{8,14})", body_text, re.I)
    if m:
        ean = m.group(1)

    availability = None
    m = re.search(r"\b(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture de stock|Indisponible)\b", body_text, re.I)
    if m:
        availability = m.group(1)

    brand = None
    image = None
    try:
        nodes = page.locator('script[type="application/ld+json"]').all_text_contents()
        queue = []
        for raw in nodes:
            try:
                parsed = json.loads(raw)
                queue.extend(parsed if isinstance(parsed, list) else [parsed])
            except Exception:
                pass
        while queue:
            obj = queue.pop(0)
            if not isinstance(obj, dict):
                continue
            if isinstance(obj.get("@graph"), list):
                queue.extend(obj["@graph"])
            if obj.get("@type") != "Product":
                continue
            if not brand and obj.get("brand"):
                b = obj["brand"]
                brand = clean(b.get("name", "")) if isinstance(b, dict) else clean(str(b))
            if not image and obj.get("image"):
                im = obj["image"]
                image = im[0] if isinstance(im, list) and im else im
    except Exception:
        pass

    if not brand:
        m = re.search(r"(?:Fournisseur|Marque)\s*:\s*([^|]{1,80})", body_text, re.I)
        if m:
            brand = clean(m.group(1))

    if not image:
        try:
            image = page.locator('meta[property="og:image"]').get_attribute("content")
        except Exception:
            pass

    crumbs = []
    try:
        for txt in page.locator('.breadcrumbs a, .breadcrumbs li, nav[aria-label*="breadcrumb" i] a').all_text_contents():
            t = clean(txt)
            if t and (not crumbs or crumbs[-1] != t):
                crumbs.append(t)
    except Exception:
        pass
    category = " > ".join(crumbs[1:-1]) if len(crumbs) >= 3 else None

    return {
        "merchant": "Mega Dental",
        "merchant_reference": merchant_reference or None,
        "manufacturer_reference": manufacturer_reference,
        "ean": ean,
        "name": title,
        "brand": brand or None,
        "category": category,
        "price_eur": price,
        "availability": availability,
        "image_url": image,
        "source_url": page.url,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def write_final(jsonl_path, output_path):
    products = []
    for line in Path(jsonl_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            products.append(json.loads(line))
        except Exception:
            pass
    payload = {
        "source": "mega_dental_bulk_local_v1",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "products": products,
    }
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(products)


def main():
    ap = argparse.ArgumentParser(description="Collecte locale Mega Dental depuis une liste d'URL déjà obtenue légitimement.")
    ap.add_argument("urls", help="Fichier texte: une URL produit Mega Dental par ligne")
    ap.add_argument("--output", default="data/mega_catalog_latest.json")
    ap.add_argument("--checkpoint", default="data/mega_bulk_checkpoint.jsonl")
    ap.add_argument("--delay", type=float, default=2.5, help="Pause entre pages en secondes")
    ap.add_argument("--limit", type=int, default=0, help="0 = toutes les URL")
    ap.add_argument("--headless", action="store_true", help="Déconseillé pour le premier test")
    args = ap.parse_args()

    urls = load_urls(args.urls)
    if args.limit > 0:
        urls = urls[:args.limit]
    if not urls:
        raise SystemExit("Aucune URL Mega Dental valide trouvée.")

    Path(args.checkpoint).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    done = load_done(args.checkpoint)
    pending = [u for u in urls if u not in done]

    print(f"Mega Dental: {len(urls)} URL(s), {len(done)} déjà faites, {len(pending)} restantes.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(locale="fr-FR")
        page = context.new_page()
        page.set_default_timeout(20000)

        with open(args.checkpoint, "a", encoding="utf-8") as out:
            for i, url in enumerate(pending, start=1):
                global_index = len(done) + i
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    status = resp.status if resp else None
                    page.wait_for_timeout(1200)

                    if status in (403, 429) or is_challenge(page):
                        print(f"[{global_index}/{len(urls)}] PROTECTION détectée sur {url}. Arrêt sans contournement.")
                        break

                    product = extract_product(page)
                    if not product.get("name"):
                        print(f"[{global_index}/{len(urls)}] fiche non reconnue: {url}")
                        continue

                    out.write(json.dumps(product, ensure_ascii=False) + "\n")
                    out.flush()
                    print(f"[{global_index}/{len(urls)}] OK - {product['name']} - {product.get('price_eur')} €")
                except PlaywrightTimeoutError:
                    print(f"[{global_index}/{len(urls)}] TIMEOUT - {url}")
                except KeyboardInterrupt:
                    print("Arrêt demandé. Le checkpoint est conservé.")
                    break
                except Exception as e:
                    print(f"[{global_index}/{len(urls)}] ERREUR - {url} - {e}")

                time.sleep(max(args.delay, 0.5))

        browser.close()

    count = write_final(args.checkpoint, args.output)
    print(f"Catalogue écrit: {args.output} ({count} produit(s)).")
    print("Relancer la même commande reprend automatiquement au dernier produit enregistré.")


if __name__ == "__main__":
    main()
