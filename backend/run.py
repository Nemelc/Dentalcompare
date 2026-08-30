import argparse

from config import DB_PATH, EXPORT_PATH
from database import Database
from frontend import export_frontend
from gacd import GACDScraper
from mega_dental import MegaDentalScraper

SCRAPERS = {
    "gacd": GACDScraper,
    "mega": MegaDentalScraper,
    "mega_dental": MegaDentalScraper,
}


def scrape(merchant: str, limit=None):
    db = Database(DB_PATH)
    scraper = SCRAPERS[merchant]()

    urls = scraper.discover_product_urls()
    if limit:
        urls = urls[:limit]

    print(f"{merchant}: {len(urls)} URLs à traiter")

    ok = 0
    errors = 0
    sku_total = 0

    for i, url in enumerate(urls, 1):
        try:
            html = scraper.get(url).text
            products = scraper.parse_product(url, html)

            if not products:
                print(f"[{i}/{len(urls)}] VIDE {url} -> 0 SKU")
                continue

            for product in products:
                db.ingest(product)

            ok += 1
            sku_total += len(products)
            print(
                f"[{i}/{len(urls)}] OK {url} "
                f"-> {len(products)} SKU"
            )

        except Exception as exc:
            errors += 1
            print(
                f"[{i}/{len(urls)}] ERROR {url}: "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        f"Résultat: {ok} pages OK, "
        f"{sku_total} SKU, {errors} erreurs"
    )

    # Un workflow ne doit plus apparaître vert si aucune donnée n'a été récupérée.
    if sku_total == 0:
        raise SystemExit(
            "Aucun SKU récupéré : le test est considéré comme échoué."
        )

    return ok, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["scrape", "export"])
    parser.add_argument(
        "--merchant",
        choices=SCRAPERS.keys(),
    )
    parser.add_argument("--limit", type=int)

    args = parser.parse_args()

    if args.command == "scrape":
        if not args.merchant:
            parser.error("--merchant est requis pour scrape")
        scrape(args.merchant, args.limit)

    else:
        db = Database(DB_PATH)
        count = export_frontend(db.conn, EXPORT_PATH)
        print(
            f"Exporté: {count} produits -> {EXPORT_PATH}"
        )


if __name__ == "__main__":
    main()
