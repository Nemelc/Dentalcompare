#!/usr/bin/env python3
"""DentalCompare - collecte GACD depuis zéro avec Playwright.

Navigation dans un vrai navigateur Chromium/Chrome. Aucun contournement de CAPTCHA,
challenge, login ou limitation d'accès. Le programme s'arrête proprement si une
protection est détectée.

La progression est stockée dans SQLite sur disque et peut reprendre après arrêt.
Aucune donnée des anciens scripts GACD n'est réutilisée.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = "https://www.gacd.fr/"
ORIGIN = "https://www.gacd.fr"
PRODUCT_MARKER = re.compile(r"Réf\.?\s*GACD\s*:", re.I)
CHALLENGE = re.compile(
    r"captcha|verify you are human|vérifiez que vous êtes humain|access denied|"
    r"attention required|security check|checking your browser|just a moment",
    re.I,
)
BAD_PATH = re.compile(
    r"/(customer|checkout|cart|catalogsearch|search|contact|mentions|conditions|"
    r"privacy|cookies|newsletter|login|account|wishlist)(/|$)",
    re.I,
)
LISTING_HINTS = (
    ".product-item-link[href]",
    "a.product-item-link[href]",
    "a.result[href]",
    ".products a[href]",
    ".product-items a[href]",
    "[class*='product'] a[href]",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(v) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def valid_ref(v: str) -> str:
    v = clean(v).strip("|:;,.()[]{}")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/\-]{1,60}", v, re.I):
        return ""
    if v.lower() in {"nom", "name", "r", "ref", "reference", "référence"}:
        return ""
    return v


def price_float(text: str):
    m = re.search(r"([0-9][0-9\s\u00a0\u202f]*[,.][0-9]{2})\s*€", text)
    if not m:
        return None
    try:
        return float(re.sub(r"[\s\u00a0\u202f]", "", m.group(1)).replace(",", "."))
    except ValueError:
        return None


def normalize_url(href: str, base: str) -> str:
    if not href:
        return ""
    try:
        u = urljoin(base, href)
        u, _ = urldefrag(u)
        p = urlparse(u)
        if p.scheme not in {"http", "https"} or p.netloc.lower() != "www.gacd.fr":
            return ""
        if BAD_PATH.search(p.path):
            return ""
        # Élimine les paramètres de tracking, garde pagination utile.
        return u
    except Exception:
        return ""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS queue(
                url TEXT PRIMARY KEY,
                kind TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'pending',
                depth INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                updated_at TEXT
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS products(
                merchant_reference TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                manufacturer_reference TEXT,
                ean TEXT,
                name TEXT,
                brand TEXT,
                category TEXT,
                variant TEXT,
                packaging TEXT,
                price_eur REAL,
                availability TEXT,
                image_url TEXT,
                captured_at TEXT NOT NULL
            )
        """)
        self.db.commit()

    def seed(self, url: str, depth: int = 0, kind: str = "seed"):
        self.db.execute(
            "INSERT OR IGNORE INTO queue(url,kind,status,depth,updated_at) VALUES(?,?,?,?,?)",
            (url, kind, "pending", depth, now_iso()),
        )
        self.db.commit()

    def add_urls(self, urls, depth: int, kind: str = "discovered"):
        self.db.executemany(
            "INSERT OR IGNORE INTO queue(url,kind,status,depth,updated_at) VALUES(?,?,?,?,?)",
            [(u, kind, "pending", depth, now_iso()) for u in urls if u],
        )
        self.db.commit()

    def next_url(self, max_depth: int):
        row = self.db.execute(
            "SELECT url,depth FROM queue WHERE status='pending' AND depth<=? ORDER BY depth,url LIMIT 1",
            (max_depth,),
        ).fetchone()
        return row if row else None

    def mark(self, url: str, status: str, kind: str | None = None, error: str | None = None):
        if kind:
            self.db.execute(
                "UPDATE queue SET status=?,kind=?,error=?,updated_at=? WHERE url=?",
                (status, kind, error, now_iso(), url),
            )
        else:
            self.db.execute(
                "UPDATE queue SET status=?,error=?,updated_at=? WHERE url=?",
                (status, error, now_iso(), url),
            )
        self.db.commit()

    def upsert_products(self, rows):
        self.db.executemany("""
            INSERT INTO products(
                merchant_reference,source_url,manufacturer_reference,ean,name,brand,
                category,variant,packaging,price_eur,availability,image_url,captured_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(merchant_reference) DO UPDATE SET
                source_url=excluded.source_url,
                manufacturer_reference=COALESCE(excluded.manufacturer_reference,products.manufacturer_reference),
                ean=COALESCE(excluded.ean,products.ean),
                name=COALESCE(NULLIF(excluded.name,''),products.name),
                brand=COALESCE(excluded.brand,products.brand),
                category=COALESCE(excluded.category,products.category),
                variant=COALESCE(excluded.variant,products.variant),
                packaging=COALESCE(excluded.packaging,products.packaging),
                price_eur=COALESCE(excluded.price_eur,products.price_eur),
                availability=COALESCE(excluded.availability,products.availability),
                image_url=COALESCE(excluded.image_url,products.image_url),
                captured_at=excluded.captured_at
        """, [(
            r["merchant_reference"], r["source_url"], r.get("manufacturer_reference"),
            r.get("ean"), r.get("name"), r.get("brand"), r.get("category"),
            r.get("variant"), r.get("packaging"), r.get("price_eur"),
            r.get("availability"), r.get("image_url"), r["captured_at"]
        ) for r in rows])
        self.db.commit()

    def stats(self):
        q = dict(self.db.execute("SELECT status,COUNT(*) FROM queue GROUP BY status").fetchall())
        p = self.db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        return q, p

    def all_products(self):
        cols = [x[1] for x in self.db.execute("PRAGMA table_info(products)").fetchall()]
        return [dict(zip(cols, row)) for row in self.db.execute("SELECT * FROM products ORDER BY merchant_reference")]


async def page_is_challenge(page) -> bool:
    try:
        title = await page.title()
        text = (await page.locator("body").inner_text(timeout=5000))[:5000]
        return bool(CHALLENGE.search(title + " " + text))
    except Exception:
        return False


async def extract_links(page) -> tuple[set[str], set[str]]:
    current = page.url
    product_links: set[str] = set()
    all_links: set[str] = set()
    for sel in LISTING_HINTS:
        try:
            hrefs = await page.locator(sel).evaluate_all("els => els.map(e => e.href || e.getAttribute('href')).filter(Boolean)")
            for href in hrefs:
                u = normalize_url(href, current)
                if u:
                    product_links.add(u)
        except Exception:
            pass
    try:
        hrefs = await page.locator("a[href]").evaluate_all("els => els.map(e => e.href || e.getAttribute('href')).filter(Boolean)")
        for href in hrefs:
            u = normalize_url(href, current)
            if u:
                all_links.add(u)
    except Exception:
        pass
    return product_links, all_links


async def extract_product(page, url: str) -> list[dict]:
    body = await page.locator("body").inner_text(timeout=15000)
    if not PRODUCT_MARKER.search(body):
        return []

    try:
        h1 = clean(await page.locator("h1").first.inner_text(timeout=3000))
    except Exception:
        h1 = "Produit GACD"

    brand = None
    for sel in ("[itemprop='brand']", ".product-brand", ".brand", "[class*='manufacturer']"):
        try:
            t = clean(await page.locator(sel).first.inner_text(timeout=1000))
            if t:
                brand = t
                break
        except Exception:
            pass

    category = None
    try:
        crumbs = [clean(x) for x in await page.locator(".breadcrumbs a,.breadcrumbs strong,.breadcrumb a,.breadcrumb li").all_inner_texts()]
        crumbs = [x for x in crumbs if x and x.lower() not in {"accueil", "home"}]
        category = " > ".join(dict.fromkeys(crumbs)) or None
    except Exception:
        pass

    image = None
    for sel, attr in (("meta[property='og:image']", "content"), (".gallery-placeholder img", "src"), ("img[itemprop='image']", "src")):
        try:
            v = await page.locator(sel).first.get_attribute(attr, timeout=1000)
            if v:
                image = urljoin(url, v)
                break
        except Exception:
            pass

    matches = list(PRODUCT_MARKER.finditer(body))
    rows = []
    seen = set()
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(body), start + 3500)
        seg = body[start:end]
        lines = [clean(x) for x in seg.splitlines() if clean(x)]
        if not lines:
            continue
        ref = valid_ref(lines[0].split()[0])
        if not ref or ref in seen:
            continue
        seen.add(ref)

        mfr = ""
        mm = re.search(r"Réf\.?\s*Fabricant\s*:\s*([^\s\r\n|]+)", seg, re.I)
        if mm:
            mfr = valid_ref(mm.group(1))

        ean = None
        em = re.search(r"\b(?:EAN|GTIN)\s*:?\s*(\d{8,14})\b", seg, re.I)
        if em:
            ean = em.group(1)

        availability = None
        sm = re.search(r"\b(En stock|Sur commande|En réapprovisionnement(?:\s+Disponible sous \d+ jours)?|Indisponible|Arrêté|Rupture de stock)\b", seg, re.I)
        if sm:
            availability = clean(sm.group(1))

        variant = None
        for line in lines[1:]:
            if re.search(r"Réf\.?\s*Fabricant", line, re.I):
                break
            if re.match(r"^(En stock|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture|Ajouter|Prix|Qté|Quantité)\b", line, re.I):
                continue
            if re.match(r"^[0-9\s,.]+\s*€", line):
                continue
            if len(line) > 2:
                variant = line
                break

        name = variant or h1
        rows.append({
            "merchant_reference": ref,
            "source_url": url,
            "manufacturer_reference": mfr or None,
            "ean": ean,
            "name": name,
            "brand": brand,
            "category": category,
            "variant": variant if variant and variant != h1 else None,
            "packaging": None,
            "price_eur": price_float(seg),
            "availability": availability,
            "image_url": image,
            "captured_at": now_iso(),
        })
    return rows


def export(store: Store, json_path: Path, csv_path: Path):
    rows = store.all_products()
    payload = {
        "source": "gacd_playwright_fresh_v1",
        "captured_at": now_iso(),
        "total_products": len(rows),
        "products": [{"merchant": "GACD", **r} for r in rows],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["merchant","merchant_reference","manufacturer_reference","ean","name","brand","category","variant","packaging","price_eur","availability","image_url","source_url","captured_at"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({"merchant":"GACD", **r})
    print(f"[GACD] Export : {len(rows)} références -> {json_path} + {csv_path}", flush=True)


async def run(args):
    data_dir = Path(args.data_dir)
    store = Store(data_dir / "gacd_playwright.sqlite3")
    # Départ totalement neuf : aucune URL des anciens collecteurs n'est utilisée.
    if args.fresh:
        store.db.execute("DELETE FROM queue")
        store.db.execute("DELETE FROM products")
        store.db.commit()
        print("[GACD] Base Playwright remise à zéro.", flush=True)

    store.seed(BASE, 0, "seed")
    for u in (
        ORIGIN + "/catalogue.html",
        ORIGIN + "/produits.html",
        ORIGIN + "/sitemap.html",
        ORIGIN + "/plan-du-site.html",
    ):
        store.seed(u, 0, "seed")

    profile = data_dir / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=args.headless,
            channel="chrome" if args.chrome else None,
            viewport={"width": 1440, "height": 1000},
            locale="fr-FR",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(args.timeout_ms)
        processed = 0
        try:
            while processed < args.max_pages:
                nxt = store.next_url(args.max_depth)
                if not nxt:
                    break
                url, depth = nxt
                try:
                    print(f"[GACD] {processed+1} | profondeur {depth} | {url}", flush=True)
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=args.nav_timeout_ms)
                    if resp and resp.status in (403, 429):
                        raise RuntimeError(f"PROTECTION_HTTP_{resp.status}")
                    await page.wait_for_timeout(args.settle_ms)
                    if await page_is_challenge(page):
                        raise RuntimeError("PROTECTION_CHALLENGE")

                    rows = await extract_product(page, url)
                    product_links, all_links = await extract_links(page)
                    if rows:
                        store.upsert_products(rows)
                        store.mark(url, "done", "product")
                        print(f"[GACD]   -> {len(rows)} référence(s) extraite(s)", flush=True)
                    else:
                        store.mark(url, "done", "listing")

                    # Les liens ressemblant à des produits passent en priorité à la profondeur suivante.
                    store.add_urls(product_links, min(depth + 1, args.max_depth), "product_candidate")
                    if depth < args.max_depth:
                        # Crawl large uniquement pour découvrir le catalogue de zéro.
                        useful = set()
                        for u in all_links:
                            path = urlparse(u).path.lower()
                            if any(x in path for x in ("dentaire", "produit", "catalog", "instrument", "endodont", "implant", "empreinte", "composite", "hygiene", "stéril", "steril", "prothese", "orthodont", "chirurg", ".html")):
                                useful.add(u)
                        store.add_urls(useful, depth + 1, "discovered")

                    processed += 1
                    if processed % 25 == 0:
                        q, pc = store.stats()
                        print(f"[GACD] État : {pc} références | file {q}", flush=True)
                        export(store, Path(args.output_json), Path(args.output_csv))
                    await page.wait_for_timeout(args.delay_ms)

                except PlaywrightTimeoutError as e:
                    store.mark(url, "error", error="TIMEOUT")
                    print(f"[GACD] Timeout : {url}", flush=True)
                    processed += 1
                except Exception as e:
                    msg = str(e)
                    store.mark(url, "error", error=msg[:500])
                    if "PROTECTION_" in msg:
                        print(f"[GACD] Protection détectée ({msg}). Arrêt propre, aucune tentative de contournement.", flush=True)
                        break
                    print(f"[GACD] Erreur : {url} -> {msg}", flush=True)
                    processed += 1
        finally:
            export(store, Path(args.output_json), Path(args.output_csv))
            q, pc = store.stats()
            print(f"[GACD] Fin : {pc} références | file {q}", flush=True)
            await context.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="backend/snapshot/data/gacd_playwright")
    ap.add_argument("--output-json", default="backend/snapshot/data/gacd_playwright_catalog.json")
    ap.add_argument("--output-csv", default="backend/snapshot/data/gacd_playwright_catalog.csv")
    ap.add_argument("--max-pages", type=int, default=20000)
    ap.add_argument("--max-depth", type=int, default=5)
    ap.add_argument("--delay-ms", type=int, default=650)
    ap.add_argument("--settle-ms", type=int, default=650)
    ap.add_argument("--timeout-ms", type=int, default=12000)
    ap.add_argument("--nav-timeout-ms", type=int, default=25000)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--chrome", action="store_true", help="Utilise Google Chrome installé au lieu du Chromium Playwright")
    ap.add_argument("--fresh", action="store_true", help="Efface uniquement la nouvelle base Playwright et repart de zéro")
    args = ap.parse_args()
    try:
        return asyncio.run(run(args)) or 0
    except KeyboardInterrupt:
        print("\n[GACD] Arrêt demandé. La progression sur disque est conservée.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
