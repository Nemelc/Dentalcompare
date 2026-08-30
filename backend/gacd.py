import re
from urllib.parse import urljoin

from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class GACDScraper(BaseScraper):
    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    def discover_product_urls(self):
        """URLs de test réelles GACD pour valider le scraper."""
        return [
            "https://www.gacd.fr/tooth-mousse-tubes-10-chapeau.html",
            "https://www.gacd.fr/tub-a-materiaux-chapeau.html",
        ]

    @staticmethod
    def _looks_product(url: str) -> bool:
        blocked = (
            "/centre-aide/",
            "/qui-sommes-nous/",
            "/catalogsearch/",
            "/customer/",
            "/checkout/",
        )
        return (
            url.startswith("https://www.gacd.fr/")
            and url.endswith((".html", ".htm"))
            and not any(x in url for x in blocked)
        )

    def parse_product(self, url: str, html: str):
        soup = self.soup(html)

        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")

        page_text = clean_text(soup.get_text(" ", strip=True))

        brand = None

        # Recherche des données structurées Product / JSON-LD
        for obj in self.json_ld(soup):
            if obj.get("@type") == "Product":
                b = obj.get("brand")

                if isinstance(b, dict):
                    brand = b.get("name")
                elif isinstance(b, str):
                    brand = b

                if not title:
                    title = clean_text(obj.get("name"))

        products = []

        # Recherche des différentes variantes présentes sur la fiche
        blocks = soup.select(
            "tr, .product-item, .variant, "
            "[class*='variant'], [class*='swatch']"
        )

        for block in blocks:
            txt = clean_text(block.get_text(" ", strip=True))

            if "Réf" not in txt or "Fabricant" not in txt:
                continue

            gacd = re.search(
                r"Réf\.?\s*GACD\s*:?\s*([A-Z0-9-]+)",
                txt,
                re.I,
            )

            mref = re.search(
                r"Réf\.?\s*Fabricant\s*:?\s*([^\s€]+)",
                txt,
                re.I,
            )

            if not (gacd or mref):
                continue

            price_matches = re.findall(
                r"\d[\d\s\u202f]*(?:,\d{1,2})?\s*€",
                txt,
            )

            price = (
                parse_price(price_matches[0])
                if price_matches
                else None
            )

            stock_match = re.search(
                r"(En stock|Sur commande|"
                r"En réapprovisionnement|Arrêté)",
                txt,
                re.I,
            )

            name = re.sub(
                r"Réf\..*$",
                "",
                txt,
                flags=re.I,
            ).strip() or title

            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=name,
                    merchant_reference=(
                        gacd.group(1) if gacd else None
                    ),
                    manufacturer_reference=(
                        mref.group(1) if mref else None
                    ),
                    brand=brand,
                    price=price,
                    availability=normalize_stock(
                        stock_match.group(1)
                        if stock_match
                        else None
                    ),
                )
            )

        if products:
            # Suppression des doublons
            unique = {}

            for product in products:
                key = (
                    product.merchant_reference,
                    product.manufacturer_reference,
                    product.name,
                )
                unique[key] = product

            return list(unique.values())

        # Cas d'une fiche ne contenant qu'une seule référence
        gacd = re.search(
            r"Référence\s+GACD\s*:?\s*([A-Z0-9-]+)",
            page_text,
            re.I,
        )

        mref = re.search(
            r"Référence\s+fabricant\s*:?\s*([^\s€]+)",
            page_text,
            re.I,
        )

        price = None

        if "€" in page_text:
            euro_position = page_text.find("€")

            price = parse_price(
                page_text[
                    max(0, euro_position - 25):
                    euro_position + 1
                ]
            )

        return [
            MerchantProduct(
                merchant=self.merchant,
                url=url,
                name=title,
                price=price,
                merchant_reference=(
                    gacd.group(1) if gacd else None
                ),
                manufacturer_reference=(
                    mref.group(1) if mref else None
                ),
                brand=brand,
            )
        ]
