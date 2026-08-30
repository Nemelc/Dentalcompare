import csv
import re
import sys
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from daily_db import upsert_product

USER_AGENT = "DentalCompareBot/1.0 (+public-price-monitor; respectful-robots)"
CSV_PATH = Path(__file__).parent / "data" / "catalogue_gacd_seed.csv"
TIMEOUT = 20
DELAY_SECONDS = 2.0

PRICE_RE = re.compile(r"(\d{1,4}(?:[ .]\d{3})*[,.]\d{2})\s*€")
GACD_REF_RE = re.compile(r"Réf\.\s*GACD\s*:\s*([A-Z0-9-]+)", re.I)
FAB_REF_RE = re.compile(r"Réf\.\s*Fabricant\s*:\s*([A-Z0-9+._/-]+)", re.I)

STOCK_WORDS = (
    "En stock",
    "Sur commande",
    "En réapprovisionnement",
    "Arrêté",
)


def robots_allows(url):
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)

    try:
        rp.read()
    except Exception as exc:
        print(f"[SKIP] robots.txt illisible pour {url}: {exc}")
        return False

    return rp.can_fetch(USER_AGENT, url)


def clean_price(value):
    return float(value.replace(" ", "").replace(".", "").replace(",", "."))


def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text("\n", strip=True)


def split_variant_blocks(text):
    # Les pages GACD présentent chaque variante à partir de "Réf. GACD:".
    starts = [m.start() for m in re.finditer(r"Réf\.\s*GACD\s*:", text, flags=re.I)]
    blocks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[start:end])
    return blocks


def parse_variants(html):
    text = page_text(html)
    variants = {}

    for block in split_variant_blocks(text):
        m_ref = GACD_REF_RE.search(block)
        if not m_ref:
            continue

        merchant_ref = m_ref.group(1).strip()

        m_fab = FAB_REF_RE.search(block)
        manufacturer_ref = m_fab.group(1).strip() if m_fab else None

        stock = None
        for word in STOCK_WORDS:
            if word.lower() in block.lower():
                stock = word
                break

        prices = PRICE_RE.findall(block)
        price = clean_price(prices[0]) if prices else None

        variants[merchant_ref] = {
            "manufacturer_reference": manufacturer_ref,
            "price_eur": price,
            "availability": stock,
        }

    return variants


def load_seed():
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_seed_price(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def main():
    rows = load_seed()

    by_url = {}
    for row in rows:
        by_url.setdefault(row["source_url"], []).append(row)

    checked_urls = 0
    refreshed_rows = 0
    skipped_urls = 0
    failed_urls = 0

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    for url, seed_rows in by_url.items():
        print(f"\n=== {url}")

        if not robots_allows(url):
            print("[SKIP] accès automatisé non autorisé ou robots.txt indisponible.")
            skipped_urls += 1
            continue

        try:
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
        except Exception as exc:
            print(f"[ERREUR] téléchargement impossible: {exc}")
            failed_urls += 1
            continue

        checked_urls += 1
        parsed = parse_variants(response.text)

        if not parsed:
            print("[ERREUR] aucune variante reconnue sur la page.")
            failed_urls += 1
            continue

        print(f"{len(parsed)} variante(s) reconnue(s).")

        for row in seed_rows:
            ref = (row.get("merchant_reference") or "").strip()
            live = parsed.get(ref)

            if live is None:
                print(f"[ABSENT] {ref} non retrouvé dans la page.")
                continue

            new_row = dict(row)
            new_row["price_eur"] = live["price_eur"]
            new_row["availability"] = live["availability"]

            if live["manufacturer_reference"]:
                new_row["manufacturer_reference"] = live["manufacturer_reference"]

            _, changed = upsert_product(new_row, source="gacd_public_page")
            refreshed_rows += 1

            status = "CHANGÉ" if changed else "identique"
            print(
                f"[OK] {ref} | {live['price_eur']} € | "
                f"{live['availability']} | {status}"
            )

        time.sleep(DELAY_SECONDS)

    print("\n===== RÉSUMÉ =====")
    print(f"URL lues : {checked_urls}")
    print(f"URL ignorées : {skipped_urls}")
    print(f"URL en erreur : {failed_urls}")
    print(f"Références rafraîchies : {refreshed_rows}")

    # Le test doit rester informatif : un bloc robots n'est pas une erreur
    # et ne doit jamais être contourné.
    if checked_urls == 0:
        print(
            "\nAucune URL GACD n'a pu être lue automatiquement. "
            "Le système conserve les données existantes sans les modifier."
        )


if __name__ == "__main__":
    main()
