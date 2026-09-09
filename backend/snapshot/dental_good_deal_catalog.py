#!/usr/bin/env python3
"""Fast public catalogue collector for Dental Good Deal.

No browser/login/circumvention. Discovers product family URLs from the public
promotions pagination, then fetches product pages concurrently and extracts
public variants (DGD reference, manufacturer ref, price, stock, image, etc.).
Stops cleanly on access-control responses (403/429/challenge-like pages).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.dentalgooddeal.com/"
LISTING = BASE + "promotions-page{page}.html"
ARTICLE_RE = re.compile(r"/article_[^\"'#?]+\.html", re.I)
REF_RE = re.compile(r"\bRéf\s+(\d{4,})\b", re.I)
MFR_RE = re.compile(r"Réf\s+fabri(?:quant|cant)\s*[:\s]*([^\s|<>]+)", re.I)
PRICE_RE = re.compile(r"(\d{1,5}(?:[\s\u00a0]\d{3})*[,.]\d{2})\s*€")
STOCK_VALUES = (
    "En stock", "Bientôt disponible", "Sur commande", "En réapprovisionnement",
    "En réapprovisionnement", "Indisponible", "Arrêté", "Rupture de stock"
)
CHALLENGE_MARKERS = ("captcha", "cloudflare", "access denied", "verify you are human")
UA = "Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue refresh)"

_tls = threading.local()


def session() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
        _tls.s = s
    return s


class AccessBlocked(RuntimeError):
    pass


def get(url: str, timeout: int = 20) -> requests.Response:
    r = session().get(url, timeout=timeout)
    text_l = (r.text[:10000] if r.text else "").lower()
    if r.status_code in (403, 429) or any(x in text_l for x in CHALLENGE_MARKERS):
        raise AccessBlocked(f"HTTP {r.status_code} / challenge on {url}")
    r.raise_for_status()
    return r


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def price_float(s: str | None):
    if not s:
        return None
    try:
        return float(s.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def discover(max_pages: int = 220, empty_stop: int = 3) -> list[str]:
    urls: set[str] = set()
    empty = 0
    for page in range(1, max_pages + 1):
        url = LISTING.format(page=page)
        try:
            r = get(url)
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) == 404:
                break
            raise
        found = {urljoin(BASE, m.group(0)) for m in ARTICLE_RE.finditer(r.text)}
        before = len(urls)
        urls.update(found)
        gained = len(urls) - before
        print(f"[DGD] listing {page}: +{gained} familles ({len(urls)} total)", flush=True)
        if not found or gained == 0:
            empty += 1
            if empty >= empty_stop:
                break
        else:
            empty = 0
    return sorted(urls)


def best_image(soup: BeautifulSoup, ref: str) -> str | None:
    # Prefer an image mentioning the actual DGD reference.
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        hay = " ".join([str(img.get("alt") or ""), str(src)])
        if ref in hay:
            return urljoin(BASE, src)
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        return urljoin(BASE, og["content"])
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and not any(x in src.lower() for x in ("logo", "sprite", "icon")):
            return urljoin(BASE, src)
    return None


def parse_page(url: str) -> list[dict]:
    r = get(url)
    soup = BeautifulSoup(r.text, "lxml")
    title = clean((soup.find("h1") or soup.find("title")).get_text(" ", strip=True) if (soup.find("h1") or soup.find("title")) else "")

    crumbs = [clean(x.get_text(" ", strip=True)) for x in soup.select(".breadcrumb a, #breadcrumb a, nav[aria-label*=breadcrumb] a")]
    category = " > ".join(x for x in crumbs if x and x.lower() != "accueil")

    # Brand is often the last word(s) of H1. Preserve a conservative fallback only.
    brand = ""
    meta_brand = soup.find("meta", attrs={"itemprop": "brand"})
    if meta_brand:
        brand = clean(meta_brand.get("content"))

    page_text = clean(soup.get_text(" ", strip=True))
    matches = list(REF_RE.finditer(page_text))
    out: list[dict] = []
    seen: set[str] = set()

    for i, m in enumerate(matches):
        ref = m.group(1)
        if ref in seen:
            continue
        seen.add(ref)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(page_text), start + 1800)
        seg = page_text[start:end]

        mfr_m = MFR_RE.search(seg)
        mfr = clean(mfr_m.group(1)) if mfr_m else ""
        prices = PRICE_RE.findall(seg)
        price = price_float(prices[0]) if prices else None
        stock = next((s for s in STOCK_VALUES if s.lower() in seg.lower()), "")

        # Variant text: between the DGD ref and manufacturer ref / cart / stock / first price.
        variant = seg[m.end() - start:]
        variant = re.split(r"Réf\s+fabri(?:quant|cant)|ajouter au|En stock|Bientôt disponible|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture de stock|\d{1,5}[,.]\d{2}\s*€", variant, maxsplit=1, flags=re.I)[0]
        variant = clean(variant)

        out.append({
            "merchant": "Dental Good Deal",
            "url": url,
            "name": title,
            "price": price,
            "currency": "EUR",
            "merchant_reference": ref,
            "manufacturer_reference": mfr,
            "ean": "",
            "brand": brand,
            "category": category,
            "variant": variant,
            "packaging": "",
            "image_url": best_image(soup, ref),
            "availability": stock,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })
    return out


def collect(urls: list[str], workers: int = 10, limit: int | None = None) -> tuple[list[dict], list[dict]]:
    if limit:
        urls = urls[:limit]
    products: list[dict] = []
    errors: list[dict] = []
    blocked = threading.Event()

    def one(url: str):
        if blocked.is_set():
            return []
        try:
            return parse_page(url)
        except AccessBlocked as e:
            blocked.set()
            raise e

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, u): u for u in urls}
        for n, fut in enumerate(cf.as_completed(futs), 1):
            u = futs[fut]
            try:
                rows = fut.result()
                products.extend(rows)
                print(f"[DGD] {n}/{len(urls)}: +{len(rows)} variantes", flush=True)
            except Exception as e:
                errors.append({"url": u, "error": str(e)})
                print(f"[DGD] ERREUR {u}: {e}", file=sys.stderr, flush=True)
            if blocked.is_set():
                for f in futs:
                    f.cancel()
                break
    return products, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--max-pages", type=int, default=220)
    ap.add_argument("--limit", type=int, default=None, help="test: limit number of product-family pages")
    ap.add_argument("--urls-file", default=None, help="reuse discovered URL JSON list")
    ap.add_argument("--urls-out", default="backend/snapshot/data/dgd_product_urls.json")
    ap.add_argument("--output", default="backend/snapshot/data/dental_good_deal_catalog.json")
    args = ap.parse_args()

    if args.urls_file and Path(args.urls_file).exists():
        urls = json.loads(Path(args.urls_file).read_text(encoding="utf-8"))
        print(f"[DGD] {len(urls)} URL réutilisées", flush=True)
    else:
        urls = discover(args.max_pages)
        Path(args.urls_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.urls_out).write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")

    products, errors = collect(urls, workers=args.workers, limit=args.limit)
    payload = {
        "source": "dental_good_deal_public_fast_v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "product_pages_discovered": len(urls),
        "product_pages_attempted": min(len(urls), args.limit) if args.limit else len(urls),
        "total_products": len(products),
        "errors": errors,
        "products": products,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DGD] TERMINE: {len(products)} variantes, {len(errors)} erreurs -> {out}")
    if any("403" in e["error"] or "429" in e["error"] or "challenge" in e["error"].lower() for e in errors):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
