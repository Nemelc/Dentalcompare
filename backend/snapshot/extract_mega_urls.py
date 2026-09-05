import argparse
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

BASE = "https://www.megadental.fr/"
SKIP_PARTS = (
    "/customer/", "/checkout/", "/catalogsearch/", "/contact", "/sitemap",
    "/brands", "/marques", "/media/", "/static/", "/catalog/category/",
)


def is_product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.hostname not in {"www.megadental.fr", "megadental.fr"}:
        return False
    path = p.path.lower()
    if any(part in path for part in SKIP_PARTS):
        return False
    if not path.endswith(".html"):
        return False
    return True


def extract_from_text(text):
    urls = set()

    # XML sitemap <loc> entries or plain URLs.
    for m in re.finditer(r"https?://(?:www\.)?megadental\.fr/[^\s<>'\"]+", text, re.I):
        url = m.group(0).replace("&amp;", "&").strip()
        if is_product_url(url):
            urls.add(url)

    # HTML links from a saved sitemap/category page.
    soup = BeautifulSoup(text, "html.parser")
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if is_product_url(url):
            urls.add(url)

    return sorted(urls)


def main():
    ap = argparse.ArgumentParser(description="Extrait les URL produit Mega Dental d'un sitemap/page HTML sauvegardé localement.")
    ap.add_argument("source", help="Fichier XML/HTML/TXT sauvegardé depuis le navigateur")
    ap.add_argument("--output", default="data/mega_urls.txt")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        raise SystemExit(f"Fichier introuvable: {src}")

    text = src.read_text(encoding="utf-8", errors="ignore")
    urls = extract_from_text(text)
    if not urls:
        raise SystemExit("Aucune URL produit Mega Dental détectée dans ce fichier.")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"{len(urls)} URL(s) produit écrite(s) dans {out}")


if __name__ == "__main__":
    main()
