import io
import re
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import requests
from warcio.archiveiterator import ArchiveIterator

from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class GACDScraper(BaseScraper):
    """
    Source GACD via Common Crawl.

    Important:
    - ce scraper ne télécharge PAS les fiches depuis gacd.fr ;
    - il interroge l'index public Common Crawl ;
    - il lit ensuite la copie archivée de la page depuis data.commoncrawl.org.

    Les prix peuvent donc être plus anciens que les prix actuellement affichés
    sur GACD. Le timestamp de la copie est conservé dans attributes.
    """

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    CC_COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
    CC_DATA_URL = "https://data.commoncrawl.org/"
    MAX_COLLECTIONS_TO_TRY = 8
    INDEX_PAGE_SIZE = 100

    def __init__(self, delay=0.25):
        super().__init__(delay=delay)
        self._records = {}
        # Session séparée : elle parle uniquement à Common Crawl.
        self.archive_session = requests.Session()
        self.archive_session.headers.update({
            "User-Agent": "DentalCompare/0.2 (+catalog research)",
            "Accept": "application/json,text/plain,*/*",
        })

    def robots_allowed(self, url: str) -> bool:
        """
        Pas utilisé pour GACD : aucune requête n'est envoyée vers gacd.fr.
        Les requêtes sont faites uniquement à Common Crawl.
        """
        host = urlparse(url).netloc.lower()
        return host.endswith("commoncrawl.org")

    def _collections(self):
        response = self.archive_session.get(
            self.CC_COLLECTIONS_URL,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return [
            item["id"]
            for item in data
            if isinstance(item, dict) and item.get("id")
        ][: self.MAX_COLLECTIONS_TO_TRY]

    def _query_collection(self, collection: str):
        endpoint = f"https://index.commoncrawl.org/{collection}-index"
        params = {
            "url": "www.gacd.fr/*.html",
            "output": "json",
            "filter": ["status:200", "mime:text/html"],
            "pageSize": self.INDEX_PAGE_SIZE,
            "page": 0,
        }

        response = self.archive_session.get(
            endpoint,
            params=params,
            timeout=60,
        )
        response.raise_for_status()

        records = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = response.json() if response.text.startswith("[") else None
            except Exception:
                item = None
            if item is not None:
                if isinstance(item, list):
                    records.extend(x for x in item if isinstance(x, dict))
                break

            try:
                import json
                row = json.loads(line)
            except Exception:
                continue

            original = row.get("url", "")
            if (
                original.startswith(("https://www.gacd.fr/", "http://www.gacd.fr/"))
                and original.lower().endswith(".html")
                and row.get("filename")
                and row.get("offset")
                and row.get("length")
            ):
                records.append(row)

        return records

    def discover_product_urls(self):
        """
        Cherche des pages GACD déjà archivées publiquement.
        On essaie plusieurs collections récentes jusqu'à trouver des fiches.
        """
        self._records = {}
        last_error = None

        for collection in self._collections():
            try:
                records = self._query_collection(collection)
            except Exception as exc:
                last_error = exc
                continue

            for row in records:
                original = row.get("url")
                if not original:
                    continue
                # Préférer la capture la plus récente si doublon dans la page d'index.
                previous = self._records.get(original)
                if not previous or row.get("timestamp", "") > previous.get("timestamp", ""):
                    row["_collection"] = collection
                    self._records[original] = row

            if self._records:
                print(
                    f"GACD/Common Crawl: {len(self._records)} pages trouvées "
                    f"dans {collection}"
                )
                break

        if not self._records:
            if last_error:
                raise RuntimeError(
                    f"Aucune page GACD trouvée dans Common Crawl. "
                    f"Dernière erreur: {last_error}"
                )
            raise RuntimeError("Aucune page GACD trouvée dans Common Crawl.")

        return sorted(self._records.keys())

    def _fetch_warc_html(self, row: dict):
        filename = row["filename"]
        offset = int(row["offset"])
        length = int(row["length"])

        warc_url = self.CC_DATA_URL + filename
        headers = {
            "Range": f"bytes={offset}-{offset + length - 1}"
        }

        time.sleep(self.delay)
        response = self.archive_session.get(
            warc_url,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()

        for record in ArchiveIterator(io.BytesIO(response.content)):
            if record.rec_type != "response":
                continue

            raw = record.content_stream().read()
            content_type = (
                record.http_headers.get_header("Content-Type")
                if record.http_headers
                else ""
            ) or ""

            charset = "utf-8"
            match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
            if match:
                charset = match.group(1)

            try:
                return raw.decode(charset, errors="replace")
            except LookupError:
                return raw.decode("utf-8", errors="replace")

        raise RuntimeError("La capture Common Crawl ne contient pas de réponse HTML.")

    def get(self, url: str):
        """
        Retourne un objet compatible avec BaseScraper.get(), mais le HTML
        provient de Common Crawl et non de GACD.
        """
        row = self._records.get(url)
        if not row:
            raise KeyError(f"Capture Common Crawl introuvable pour {url}")

        html = self._fetch_warc_html(row)
        return SimpleNamespace(
            text=html,
            status_code=200,
            url=url,
            archive_timestamp=row.get("timestamp"),
        )

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
            url.startswith(("https://www.gacd.fr/", "http://www.gacd.fr/"))
            and url.lower().endswith(".html")
            and not any(x in url for x in blocked)
        )

    @staticmethod
    def _variant_name(segment: str, gacd_match, mref_match):
        if not mref_match:
            return ""
        candidate = segment[gacd_match.end():mref_match.start()]
        candidate = clean_text(candidate)

        # Retire les attributs GACD qui suivent souvent le nom de variante.
        attribute_labels = [
            "TEINTE", "COULEUR", "DIMENSION", "DIAMETRE-DIMENSION",
            "DIAMÈTRE-DIMENSION", "LONGUEUR", "N°", "MORS", "PRISE",
            "PARFUM", "TAILLE", "EPAISSEUR", "ÉPAISSEUR", "TYPE",
            "MODELE", "MODÈLE", "GRAIN", "ISO", "CONDITIONNEMENT",
            "QUANTITE", "QUANTITÉ", "ESPACEMENT",
        ]
        labels = "|".join(re.escape(x) for x in attribute_labels)
        candidate = re.split(
            rf"\b(?:{labels})\s*:",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]

        return clean_text(candidate.strip(" :-|"))

    def _parse_text_variants(self, page_text: str, title: str, brand: str, url: str):
        """
        Fallback robuste basé sur le texte visible de la copie archivée.
        Les variantes GACD sont généralement structurées ainsi :
        Réf. GACD -> nom -> attributs -> Réf. Fabricant -> stock -> prix.
        """
        markers = list(re.finditer(
            r"Réf\.?\s*GACD\s*:?\s*([A-Z0-9-]+)",
            page_text,
            re.I,
        ))
        products = []

        for index, gacd_match in enumerate(markers):
            start = gacd_match.start()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(page_text)
            segment = page_text[start:end]

            mref = re.search(
                r"Réf\.?\s*Fabricant\s*:?\s*([^\s€|]+)",
                segment,
                re.I,
            )
            # La référence générique en haut de page n'a souvent pas de vraie réf fabricant.
            if not mref:
                continue

            name = self._variant_name(segment, gacd_match, mref) or title

            after_ref = segment[mref.end():]
            stock_match = re.search(
                r"(En stock|Sur commande|En réapprovisionnement|"
                r"Arrêté|Indisponible|Rupture)",
                after_ref,
                re.I,
            )

            # Prend le premier prix après la référence fabricant.
            price_match = re.search(
                r"\d[\d\s\u202f.]*(?:,\d{1,2})?\s*€",
                after_ref,
            )
            price = parse_price(price_match.group(0)) if price_match else None

            record = self._records.get(url, {})
            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=name,
                    merchant_reference=gacd_match.group(1),
                    manufacturer_reference=mref.group(1),
                    brand=brand,
                    price=price,
                    availability=normalize_stock(
                        stock_match.group(1) if stock_match else None
                    ),
                    attributes={
                        "source": "common_crawl",
                        "archive_timestamp": record.get("timestamp"),
                        "common_crawl_collection": record.get("_collection"),
                    },
                )
            )

        return products

    def parse_product(self, url: str, html: str):
        soup = self.soup(html)
        h1 = soup.find("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
        page_text = clean_text(soup.get_text(" ", strip=True))

        brand = None
        for obj in self.json_ld(soup):
            obj_type = obj.get("@type")
            if obj_type == "Product" or (
                isinstance(obj_type, list) and "Product" in obj_type
            ):
                b = obj.get("brand")
                if isinstance(b, dict):
                    brand = b.get("name")
                elif isinstance(b, str):
                    brand = b
                if not title:
                    title = clean_text(obj.get("name"))

        # D'abord tenter les blocs DOM.
        products = []
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
                r"Réf\.?\s*Fabricant\s*:?\s*([^\s€|]+)",
                txt,
                re.I,
            )
            if not (gacd and mref):
                continue

            price_match = re.search(
                r"\d[\d\s\u202f.]*(?:,\d{1,2})?\s*€",
                txt[mref.end():],
            )
            stock_match = re.search(
                r"(En stock|Sur commande|En réapprovisionnement|"
                r"Arrêté|Indisponible|Rupture)",
                txt,
                re.I,
            )

            record = self._records.get(url, {})
            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=title or clean_text(txt[:gacd.start()]),
                    merchant_reference=gacd.group(1),
                    manufacturer_reference=mref.group(1),
                    brand=brand,
                    price=parse_price(price_match.group(0)) if price_match else None,
                    availability=normalize_stock(
                        stock_match.group(1) if stock_match else None
                    ),
                    attributes={
                        "source": "common_crawl",
                        "archive_timestamp": record.get("timestamp"),
                        "common_crawl_collection": record.get("_collection"),
                    },
                )
            )

        if not products:
            products = self._parse_text_variants(page_text, title, brand, url)

        # Déduplication par référence GACD + référence fabricant.
        unique = {}
        for product in products:
            key = (
                product.merchant_reference,
                product.manufacturer_reference,
            )
            unique[key] = product

        return list(unique.values())
