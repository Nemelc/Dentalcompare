import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MEGA_HOSTS = {"www.megadental.fr", "megadental.fr"}


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


def valid_plain_value(value):
    value = clean(value)
    if not value or len(value) > 100:
        return None
    low = value.lower()
    if any(ch in value for ch in "{}[];"):
        return None
    if any(x in low for x in ["function", "type_id", "writerecentlyviewed", "require(", "datalayer"]):
        return None
    return value


def valid_reference(value):
    value = valid_plain_value(value)
    if not value or len(value) > 60:
        return None
    if re.fullmatch(r"(?:S/?O|N/?A|N\.A\.|NC|N/C|Non renseigné|Aucun|DIVERS)", value, re.I):
        return None
    return value


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


def is_real_challenge(page, status=None):
    if status in (403, 429):
        return True
    try:
        title = clean(page.title()).lower()
        body = clean(page.locator("body").inner_text()).lower()
        normal_product = page.locator("h1").count() > 0 and page.locator(
            '.product-info-main, [data-price-type="finalPrice"], .price-box'
        ).count() > 0
    except Exception:
        return True

    title_signals = [
        "just a moment...",
        "just a moment",
        "checking your browser",
        "attention required",
    ]
    body_signals = [
        "checking your browser",
        "verify you are human",
        "performing security verification",
        "enable javascript and cookies to continue",
    ]

    challenged = title in title_signals or any(body.startswith(x) for x in body_signals)
    if normal_product:
        return False
    return challenged


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


def value_near_label(page, labels):
    labels_low = [x.lower() for x in labels]
    selectors = [
        "tr",
        ".product.attribute",
        ".additional-attributes-wrapper tr",
        "dl > div",
        ".product-info-main li",
        ".product-info-main p",
    ]
    for sel in selectors:
        try:
            for el in page.query_selector_all(sel):
                txt = clean(el.inner_text())
                low = txt.lower()
                matched = next((lab for lab in labels_low if low.startswith(lab)), None)
                if not matched:
                    continue
                for child_sel in [".value", "td:last-child", "dd", "[data-th]"]:
                    child = el.query_selector(child_sel)
                    if child:
                        val = clean(child.inner_text())
                        if val and val.lower() not in labels_low:
                            return val
                val = re.sub(r"^\s*" + re.escape(matched) + r"\s*:?\s*", "", txt, flags=re.I)
                if val:
                    return val
        except Exception:
            pass
    return None


def read_jsonld_product(page):
    result = {"sku": None, "mpn": None, "gtin": None, "brand": None, "image": None}
    try:
        queue = []
        for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
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
            typ = obj.get("@type")
            is_product = typ == "Product" or (isinstance(typ, list) and "Product" in typ)
            if not is_product:
                continue
            result["sku"] = result["sku"] or valid_reference(str(obj.get("sku") or ""))
            result["mpn"] = result["mpn"] or valid_reference(str(obj.get("mpn") or ""))
            for key in ["gtin13", "gtin14", "gtin12", "gtin8", "gtin"]:
                g = re.sub(r"\D", "", str(obj.get(key) or ""))
                if 8 <= len(g) <= 14:
                    result["gtin"] = result["gtin"] or g
            b = obj.get("brand")
            if b and not result["brand"]:
                if isinstance(b, dict):
                    result["brand"] = valid_plain_value(str(b.get("name") or ""))
                else:
                    result["brand"] = valid_plain_value(str(b))
            im = obj.get("image")
            if im and not result["image"]:
                result["image"] = im[0] if isinstance(im, list) and im else im
            break
    except Exception:
        pass
    return result


def extract_product(page):
    body_text = clean(page.locator("body").inner_text())
    title = clean(page.locator("h1").first.inner_text()) if page.locator("h1").count() else clean(page.title())
    jsonld = read_jsonld_product(page)

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

    merchant_reference = valid_reference(first_text(page, [
        '[itemprop="sku"]',
        '.product.attribute.sku .value',
        '.product-info-main .sku .value',
        '.product-info-stock-sku .sku .value',
    ]))
    if not merchant_reference:
        try:
            el = page.query_selector('[data-product-sku]')
            if el:
                merchant_reference = valid_reference(el.get_attribute('data-product-sku') or "")
        except Exception:
            pass
    merchant_reference = merchant_reference or jsonld["sku"] or valid_reference(value_near_label(page, [
        "Référence Mega Dental", "Réf. Mega Dental", "Réf Mega Dental", "SKU"
    ]))

    manufacturer_reference = jsonld["mpn"] or valid_reference(value_near_label(page, [
        "MPN", "Référence fabricant", "Réf. fabricant", "Réf fabricant", "Code fabricant"
    ]))

    ean = jsonld["gtin"]
    if not ean:
        raw_ean = value_near_label(page, ["EAN", "GTIN", "EAN13", "GTIN13"])
        digits = re.sub(r"\D", "", raw_ean or "")
        if 8 <= len(digits) <= 14:
            ean = digits

    availability = None
    m = re.search(r"\b(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture de stock|Indisponible)\b", body_text, re.I)
    if m:
        availability = m.group(1)

    brand = jsonld["brand"] or valid_plain_value(value_near_label(page, ["Fournisseur", "Marque", "Fabricant"]))

    image = jsonld["image"]
    if not image:
        try:
            image = page.locator('meta[property="og:image"]').get_attribute("content")
        except Exception:
            pass

    crumbs = []
    try:
        seen = set()
        for txt in page.locator('.breadcrumbs a, .breadcrumbs li, nav[aria-label*="breadcrumb" i] a').all_text_contents():
            t = clean(txt)
            if t and t not in seen:
                seen.add(t)
                crumbs.append(t)
    except Exception:
        pass
    category = " > ".join(crumbs[1:-1]) if len(crumbs) >= 3 else None

    return {
        "merchant": "Mega Dental",
        "merchant_reference": merchant_reference,
        "manufacturer_reference": manufacturer_reference,
        "ean": ean,
        "name": title,
        "brand": brand,
        "category": category,
        "price_eur": price,
        "availability": availability,
        "image_url": image,
        "source_url": page.url,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def write_final(jsonl_path, output_path):
    products = []
    p = Path(jsonl_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                products.append(json.loads(line))
            except Exception:
                pass
    payload = {
        "source": "mega_dental_bulk_local_v2",
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

                    if is_real_challenge(page, status):
                        print(f"[{global_index}/{len(urls)}] PROTECTION réelle détectée (HTTP {status}) sur {url}. Arrêt sans contournement.")
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
