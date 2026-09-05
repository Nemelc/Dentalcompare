import re
from urllib.parse import urljoin
from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class MegaDentalScraper(BaseScraper):
    merchant = "Mega Dental"
    base_url = "https://www.megadental.fr"

    def discover_product_urls(self):
        # Le robots.txt de Mega Dental déclare explicitement ce sitemap XML.
        # Les anciennes routes /sitemap et /sitemap/products renvoient 403 depuis GitHub Actions.
        candidates = [
            "/media/sitemap/sitemap_14.xml",
            "/sitemap.xml",
            "/sitemap_index.xml",
        ]
        urls = set()

        for path in candidates:
            try:
                r = self.get(urljoin(self.base_url, path))
            except Exception:
                continue

            soup = self.soup(r.text)
            locs = [x.get_text(strip=True) for x in soup.find_all("loc")]

            if locs:
                for loc in locs:
                    if self._looks_product(loc):
                        urls.add(loc)
                    elif loc.endswith(".xml"):
                        try:
                            child = self.soup(self.get(loc).text)
                            for node in child.find_all("loc"):
                                child_url = node.get_text(strip=True)
                                if self._looks_product(child_url):
                                    urls.add(child_url)
                        except Exception:
                            pass

        return sorted(urls)

    @staticmethod
    def _looks_product(url: str) -> bool:
        blocked = (
            "/brands/",
            "/categories/",
            "/sitemap",
            "/contact",
            "/account",
            "/cart",
            "/media/",
            "/static/",
        )
        return (
            url.startswith("https://www.megadental.fr/")
            and not url.endswith(".xml")
            and not any(x in url for x in blocked)
        )

    def parse_product(self, url: str, html: str):
        soup = self.soup(html)
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
        page_text = clean_text(soup.get_text(" ", strip=True))
        brand = image_url = ean = None
        offer_price = None
        availability = None

        for obj in self.json_ld(soup):
            if obj.get("@type") != "Product":
                continue
            title = title or clean_text(obj.get("name"))
            b = obj.get("brand")
            brand = (b.get("name") if isinstance(b, dict) else b) or brand
            image = obj.get("image")
            image_url = (image[0] if isinstance(image, list) and image else image) or image_url
            ean = obj.get("gtin13") or obj.get("gtin") or obj.get("gtin14") or ean
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offer_price = parse_price(str(offers.get("price"))) or offer_price
                availability = normalize_stock(str(offers.get("availability"))) or availability

        merchant_ref = None
        for pat in [
            r"\bRéf\.?\s*:?\s*([A-Z0-9][A-Z0-9._/-]+)",
            r"\bReference\s*:?\s*([A-Z0-9][A-Z0-9._/-]+)",
        ]:
            m = re.search(pat, page_text, re.I)
            if m:
                merchant_ref = m.group(1)
                break

        mref = None
        m = re.search(
            r"(?:Réf(?:érence)?\s+fabricant|Code\s+fabricant)\s*:?\s*([A-Z0-9._+/-]+)",
            page_text,
            re.I,
        )
        if m:
            mref = m.group(1)

        if offer_price is None:
            prices = re.findall(r"\d[\d\s\u202f]*(?:,\d{1,2})?\s*€", page_text)
            offer_price = parse_price(prices[0]) if prices else None

        stock_match = re.search(
            r"(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture|Indisponible)",
            page_text,
            re.I,
        )
        availability = availability or normalize_stock(stock_match.group(1) if stock_match else None)

        return [MerchantProduct(
            merchant=self.merchant,
            url=url,
            name=title,
            price=offer_price,
            merchant_reference=merchant_ref,
            manufacturer_reference=mref,
            brand=brand,
            ean=ean,
            image_url=image_url,
            availability=availability,
        )]
