#!/usr/bin/env python3
"""Fast public catalogue collector for Dental Good Deal.

Uses ordinary public HTML only: no login, browser automation, CAPTCHA handling or
access-control circumvention. Discovery and product reads are concurrent, with
conservative retries for transient network/5xx failures. 403/429/challenge
responses stop the run immediately.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
import threading
import time
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
    "Indisponible", "Arrêté", "Rupture de stock"
)
CHALLENGE_MARKERS = ("captcha", "cloudflare", "access denied", "verify you are human")
UA = "Mozilla/5.0 (compatible; DentalCompareCatalog/1.1; public catalogue refresh)"
_tls = threading.local()


class AccessBlocked(RuntimeError):
    pass


def session() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9", "Connection": "keep-alive"})
        adapter = requests.adapters.HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=0)
        s.mount("https://", adapter)
        _tls.s = s
    return s


def get(url: str, timeout: int = 18, retries: int = 2) -> requests.Response:
    last = None
    for attempt in range(retries + 1):
        try:
            r = session().get(url, timeout=timeout)
            text_l = (r.text[:10000] if r.text else "").lower()
            if r.status_code in (403, 429) or any(x in text_l for x in CHALLENGE_MARKERS):
                raise AccessBlocked(f"HTTP {r.status_code} / challenge on {url}")
            if r.status_code >= 500 and attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except AccessBlocked:
            raise
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            last = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (403, 429):
                raise AccessBlocked(f"HTTP {status} on {url}") from e
            if attempt < retries and (status is None or status >= 500):
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last or RuntimeError(url)


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def price_float(s: str | None):
    if not s:
        return None
    try:
        return float(s.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _discover_page(page: int) -> tuple[int, set[str]]:
    r = get(LISTING.format(page=page))
    return page, {urljoin(BASE, m.group(0)) for m in ARTICLE_RE.finditer(r.text)}


def discover(max_pages: int = 220, workers: int = 8) -> list[str]:
    """Discover public family URLs quickly. Pages after the catalogue end simply add none."""
    urls: set[str] = set()
    blocked = threading.Event()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_discover_page, p): p for p in range(1, max_pages + 1)}
        done = 0
        for fut in cf.as_completed(futs):
            p = futs[fut]
            try:
                _, found = fut.result()
                urls.update(found)
                done += 1
                if done % 20 == 0 or found:
                    print(f"[DGD] découverte {done}/{max_pages}: {len(urls)} familles", flush=True)
            except AccessBlocked:
                blocked.set()
                for f in futs: f.cancel()
                raise
            except requests.HTTPError as e:
                if getattr(e.response, "status_code", None) != 404:
                    print(f"[DGD] listing {p}: {e}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[DGD] listing {p}: {e}", file=sys.stderr, flush=True)
    return sorted(urls)


def image_candidates(soup: BeautifulSoup):
    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if src:
            imgs.append((" ".join([str(img.get("alt") or ""), str(src)]), urljoin(BASE, src)))
    og = soup.find("meta", attrs={"property": "og:image"})
    og_url = urljoin(BASE, og["content"]) if og and og.get("content") else None
    fallback = next((u for _, u in imgs if not any(x in u.lower() for x in ("logo", "sprite", "icon"))), None)
    return imgs, og_url, fallback


def best_image(imgs, og_url, fallback, ref: str):
    return next((u for hay, u in imgs if ref in hay), None) or og_url or fallback


def parse_page(url: str) -> list[dict]:
    r = get(url)
    soup = BeautifulSoup(r.text, "lxml")
    h = soup.find("h1") or soup.find("title")
    title = clean(h.get_text(" ", strip=True) if h else "")
    crumbs = [clean(x.get_text(" ", strip=True)) for x in soup.select(".breadcrumb a, #breadcrumb a, nav[aria-label*=breadcrumb] a")]
    category = " > ".join(x for x in crumbs if x and x.lower() != "accueil")
    meta_brand = soup.find("meta", attrs={"itemprop": "brand"})
    brand = clean(meta_brand.get("content")) if meta_brand else ""
    imgs, og_url, fallback = image_candidates(soup)

    page_text = clean(soup.get_text(" ", strip=True))
    matches = list(REF_RE.finditer(page_text))
    out, seen = [], set()
    captured = datetime.now(timezone.utc).isoformat()
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
        variant = seg[m.end() - start:]
        variant = re.split(r"Réf\s+fabri(?:quant|cant)|ajouter au|En stock|Bientôt disponible|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture de stock|\d{1,5}[,.]\d{2}\s*€", variant, maxsplit=1, flags=re.I)[0]
        variant = clean(variant)
        out.append({
            "merchant": "Dental Good Deal", "url": url, "name": title, "price": price,
            "currency": "EUR", "merchant_reference": ref, "manufacturer_reference": mfr,
            "ean": "", "brand": brand, "category": category, "variant": variant,
            "packaging": "", "image_url": best_image(imgs, og_url, fallback, ref),
            "availability": stock, "captured_at": captured,
        })
    return out


def collect(urls: list[str], workers: int = 12, limit: int | None = None) -> tuple[list[dict], list[dict]]:
    if limit:
        urls = urls[:limit]
    products, errors = [], []
    blocked = threading.Event()
    def one(url):
        if blocked.is_set(): return []
        try: return parse_page(url)
        except AccessBlocked:
            blocked.set(); raise
    started = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, u): u for u in urls}
        for n, fut in enumerate(cf.as_completed(futs), 1):
            u = futs[fut]
            try:
                rows = fut.result(); products.extend(rows)
                if n % 25 == 0 or len(rows) >= 20:
                    rate = n / max((time.time()-started)/60, .01)
                    print(f"[DGD] {n}/{len(urls)} — {len(products)} variantes — {rate:.0f} pages/min", flush=True)
            except Exception as e:
                errors.append({"url": u, "error": str(e)})
                print(f"[DGD] ERREUR {u}: {e}", file=sys.stderr, flush=True)
            if blocked.is_set():
                for f in futs: f.cancel()
                break
    return products, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--discover-workers", type=int, default=8)
    ap.add_argument("--max-pages", type=int, default=220)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--urls-file", default=None)
    ap.add_argument("--urls-out", default="backend/snapshot/data/dgd_product_urls.json")
    ap.add_argument("--output", default="backend/snapshot/data/dental_good_deal_catalog.json")
    ap.add_argument("--discover-only", action="store_true")
    args = ap.parse_args()

    if args.urls_file and Path(args.urls_file).exists():
        urls = json.loads(Path(args.urls_file).read_text(encoding="utf-8"))
        print(f"[DGD] {len(urls)} URL réutilisées", flush=True)
    else:
        urls = discover(args.max_pages, args.discover_workers)
    Path(args.urls_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.urls_out).write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DGD] découverte terminée: {len(urls)} familles", flush=True)
    if args.discover_only:
        return 0

    products, errors = collect(urls, workers=args.workers, limit=args.limit)
    payload = {
        "source": "dental_good_deal_public_fast_v2",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "product_pages_discovered": len(urls),
        "product_pages_attempted": min(len(urls), args.limit) if args.limit else len(urls),
        "total_products": len(products), "errors": errors, "products": products,
    }
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DGD] TERMINE: {len(products)} variantes, {len(errors)} erreurs -> {out}")
    if any("403" in e["error"] or "429" in e["error"] or "challenge" in e["error"].lower() for e in errors):
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
