import argparse
from config import DB_PATH, EXPORT_PATH
from database import Database
from frontend import export_frontend
from gacd import GACDScraper
from mega_dental import MegaDentalScraper

SCRAPERS = {"gacd": GACDScraper, "mega": MegaDentalScraper}


def scrape(merchant: str, limit=None):
    db = Database(DB_PATH)
    scraper = SCRAPERS[merchant]()
    urls = scraper.discover_product_urls()
    if limit:
        urls = urls[:limit]
    print(f"{merchant}: {len(urls)} URLs à traiter")
    ok = errors = 0
    for i, url in enumerate(urls, 1):
        try:
            html = scraper.get(url).text
            products = scraper.parse_product(url, html)
            for p in products:
                db.ingest(p)
            ok += 1
            print(f"[{i}/{len(urls)}] OK {url} -> {len(products)} SKU")
        except Exception as exc:
            errors += 1
            print(f"[{i}/{len(urls)}] ERROR {url}: {exc}")
    return ok, errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scrape", "export"])
    ap.add_argument("--merchant", choices=SCRAPERS.keys())
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    if args.command == "scrape":
        if not args.merchant:
            ap.error("--merchant est requis pour scrape")
        print(scrape(args.merchant, args.limit))
    else:
        db = Database(DB_PATH)
        n = export_frontend(db.conn, EXPORT_PATH)
        print(f"Exporté: {n} produits -> {EXPORT_PATH}")

if __name__ == "__main__":
    main()
