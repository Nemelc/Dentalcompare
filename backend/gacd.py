
import json
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
    Source GACD via Common Crawl, sans requêter directement les fiches gacd.fr.

    Cette version :
    - essaie plusieurs collections Common Crawl récentes ;
    - réessaie automatiquement en cas de 429/500/502/503/504 ;
    - passe à la collection suivante si une collection reste indisponible ;
    - lit ensuite la copie archivée via data.commoncrawl.org.
    """

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    CC_COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
    CC_DATA_URL = "https://data.commoncrawl.org/"

    # On limite volontairement pour ne pas surcharger l'index.
    MAX_COLLECTIONS_TO_TRY = 12
    INDEX_PAGE_SIZE = 100

    # Retry doux en cas d'indisponibilité temporaire.
    RETRY_STATUS = {429, 500, 502, 503, 504}
    RETRY_DELAYS = (2, 5, 10)

    def __init__(self, delay=0.25):
        super().__init__(delay=delay)
        self._records = {}

        self.archive_session = requests.Session()
        self.archive_session.headers.update({
            "User-Agent": "DentalCompare/0.3 (+catalog research)",
            "Accept": "application/json,text/plain,*/*",
        })

    def robots_allowed(self, url: str) -> bool:
        """
        Pour cette classe, les requêtes vont uniquement vers Common Crawl.
        """
        host = urlparse(url).netloc.lower()
        return host.endswith("commoncrawl.org")

    def _request_with_retry(self, url, *, params=None, headers=None, timeout=60):
        last_error = None

        # Tentative initiale + retries.
        attempts = 1 + len(self.RETRY_DELAYS)

        for attempt in range(attempts):
            try:
                response = self.archive_session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )

                if response.status_code in self.RETRY_STATUS:
                    last_error = RuntimeError(
                        f"HTTP {response.status_code} pour {response.url}"
                    )

                    if attempt < len(self.RETRY_DELAYS):
                        delay = self.RETRY_DELAYS[attempt]
                        print(
                            f"Common Crawl temporairement indisponible "
                            f"(HTTP {response.status_code}) ; nouvel essai dans {delay}s..."
                        )
                        time.sleep(delay)
                        continue

                response.raise_for_status()
                return response

            except requests.RequestException as exc:
                last_error = exc

                if attempt < len(self.RETRY_DELAYS):
                    delay = self.RETRY_DELAYS[attempt]
                    print(
                        f"Erreur réseau Common Crawl ; nouvel essai dans {delay}s..."
                    )
                    time.sleep(delay)
                    continue

                break

        raise RuntimeError(str(last_error) if last_error else "Erreur Common Crawl inconnue")

    def _collections(self):
        """
        Récupère la liste officielle des collections, puis essaie les plus récentes.
        En cas d'échec de collinfo.json, utilise une petite liste de secours.
        """
        try:
            response = self._request_with_retry(
                self.CC_COLLECTIONS_URL,
                timeout=30,
            )
            data = response.json()

            collections = [
                item.get("id")
                for item in data
                if isinstance(item, dict) and item.get("id")
            ]

            if collections:
                return collections[: self.MAX_COLLECTIONS_TO_TRY]

        except Exception as exc:
            print(f"Impossible de lire collinfo.json : {exc}")

        # Liste de secours : si Common Crawl ne permet pas de récupérer collinfo.
        # Les collections inexistantes seront simplement ignorées.
        return [
            "CC-MAIN-2026-30",
            "CC-MAIN-2026-26",
            "CC-MAIN-2026-21",
            "CC-MAIN-2026-16",
            "CC-MAIN-2026-12",
            "CC-MAIN-2026-08",
            "CC-MAIN-2026-04",
            "CC-MAIN-2025-51",
            "CC-MAIN-2025-47",
            "CC-MAIN-2025-43",
            "CC-MAIN-2025-38",
            "CC-MAIN-2025-33",
        ][: self.MAX_COLLECTIONS_TO_TRY]

    def _query_collection(self, collection: str):
        endpoint = f"https://index.commoncrawl.org/{collection}-index"

        # Deux formes de requête : la première est plus stricte, la seconde plus large.
        queries = [
            {
                "url": "www.gacd.fr/*.html",
                "output": "json",
                "filter": ["status:200", "mime:text/html"],
                "pageSize": self.INDEX_PAGE_SIZE,
                "page": 0,
            },
            {
                "url": "gacd.fr/*.html",
                "output": "json",
                "filter": ["status:200", "mime:text/html"],
                "pageSize": self.INDEX_PAGE_SIZE,
                "page": 0,
            },
        ]

        all_records = []

        for params in queries:
            response = self._request_with_retry(
                endpoint,
                params=params,
                timeout=60,
            )

            text = response.text.strip()
            if not text:
                continue

            # Common Crawl renvoie normalement du JSON ligne par ligne.
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue

                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                original = row.get("url", "")

                if not (
                    original.startswith(
                        (
                            "https://www.gacd.fr/",
                            "http://www.gacd.fr/",
                            "https://gacd.fr/",
                            "http://gacd.fr/",
                        )
                    )
                    and original.lower().endswith(".html")
                ):
                    continue

                if not all(
                    row.get(field)
                    for field in ("filename", "offset", "length")
                ):
                    continue

                all_records.append(row)

            if all_records:
                break

        return all_records

    def discover_product_urls(self):
        """
        Cherche des pages GACD archivées dans plusieurs collections récentes.
        """
        self._records = {}
        errors = []

        collections = self._collections()
        print(f"Common Crawl : {len(collections)} collections à essayer")

        for index, collection in enumerate(collections, 1):
            print(
                f"[Common Crawl {index}/{len(collections)}] "
                f"Recherche dans {collection}..."
            )

            try:
                records = self._query_collection(collection)

            except Exception as exc:
                errors.append(f"{collection}: {exc}")
                print(f"{collection} indisponible : {exc}")
                continue

            if not records:
                print(f"{collection}: aucune page GACD trouvée")
                continue

            for row in records:
                original = row.get("url")
                if not original:
                    continue

                previous = self._records.get(original)

                if (
                    not previous
                    or row.get("timestamp", "") > previous.get("timestamp", "")
                ):
                    row["_collection"] = collection
                    self._records[original] = row

            if self._records:
                print(
                    f"GACD/Common Crawl : {len(self._records)} pages trouvées "
                    f"dans {collection}"
                )
                break

        if not self._records:
            details = " | ".join(errors[-4:]) if errors else "aucun résultat"
            raise RuntimeError(
                "Aucune page GACD trouvée après plusieurs collections Common Crawl. "
                f"Détails récents : {details}"
            )

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

        response = self._request_with_retry(
            warc_url,
            headers=headers,
            timeout=60,
        )

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
            match = re.search(
                r"charset=([A-Za-z0-9._-]+)",
                content_type,
                re.I,
            )

            if match:
                charset = match.group(1)

            try:
                return raw.decode(charset, errors="replace")
            except LookupError:
                return raw.decode("utf-8", errors="replace")

        raise RuntimeError(
            "La capture Common Crawl ne contient pas de réponse HTML."
        )

    def get(self, url: str):
        """
        Fournit un objet .text comme requests.Response,
        mais le HTML vient de Common Crawl.
        """
        row = self._records.get(url)

        if not row:
            raise KeyError(
                f"Capture Common Crawl introuvable pour {url}"
            )

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
            url.startswith(
                (
                    "https://www.gacd.fr/",
                    "http://www.gacd.fr/",
                    "https://gacd.fr/",
                    "http://gacd.fr/",
                )
            )
            and url.lower().endswith(".html")
            and not any(x in url for x in blocked)
        )

    @staticmethod
    def _variant_name(segment: str, gacd_match, mref_match):
        if not mref_match:
            return ""

        candidate = segment[
            gacd_match.end():mref_match.start()
        ]

        candidate = clean_text(candidate)

        attribute_labels = [
            "TEINTE",
            "COULEUR",
            "DIMENSION",
            "DIAMETRE-DIMENSION",
            "DIAMÈTRE-DIMENSION",
            "LONGUEUR",
            "N°",
            "MORS",
            "PRISE",
            "PARFUM",
            "TAILLE",
            "EPAISSEUR",
            "ÉPAISSEUR",
            "TYPE",
            "MODELE",
            "MODÈLE",
            "GRAIN",
            "ISO",
            "CONDITIONNEMENT",
            "QUANTITE",
            "QUANTITÉ",
            "ESPACEMENT",
        ]

        labels = "|".join(
            re.escape(x)
            for x in attribute_labels
        )

        candidate = re.split(
            rf"\b(?:{labels})\s*:",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]

        return clean_text(
            candidate.strip(" :-|")
        )

    def _parse_text_variants(
        self,
        page_text: str,
        title: str,
        brand: str,
        url: str,
    ):
        markers = list(
            re.finditer(
                r"Réf\.?\s*GACD\s*:?\s*([A-Z0-9-]+)",
                page_text,
                re.I,
            )
        )

        products = []

        for index, gacd_match in enumerate(markers):
            start = gacd_match.start()

            if index + 1 < len(markers):
                end = markers[index + 1].start()
            else:
                end = len(page_text)

            segment = page_text[start:end]

            mref = re.search(
                r"Réf\.?\s*Fabricant\s*:?\s*([^\s€|]+)",
                segment,
                re.I,
            )

            if not mref:
                continue

            name = (
                self._variant_name(
                    segment,
                    gacd_match,
                    mref,
                )
                or title
            )

            after_ref = segment[mref.end():]

            stock_match = re.search(
                r"(En stock|Sur commande|"
                r"En réapprovisionnement|Arrêté|"
                r"Indisponible|Rupture)",
                after_ref,
                re.I,
            )

            price_match = re.search(
                r"\d[\d\s\u202f.]*(?:,\d{1,2})?\s*€",
                after_ref,
            )

            price = (
                parse_price(price_match.group(0))
                if price_match
                else None
            )

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
                        stock_match.group(1)
                        if stock_match
                        else None
                    ),
                    attributes={
                        "source": "common_crawl",
                        "archive_timestamp": record.get(
                            "timestamp"
                        ),
                        "common_crawl_collection": record.get(
                            "_collection"
                        ),
                    },
                )
            )

        return products

    def parse_product(self, url: str, html: str):
        soup = self.soup(html)

        h1 = soup.find("h1")

        title = clean_text(
            h1.get_text(" ", strip=True)
            if h1
            else ""
        )

        page_text = clean_text(
            soup.get_text(" ", strip=True)
        )

        brand = None

        for obj in self.json_ld(soup):
            obj_type = obj.get("@type")

            if (
                obj_type == "Product"
                or (
                    isinstance(obj_type, list)
                    and "Product" in obj_type
                )
            ):
                b = obj.get("brand")

                if isinstance(b, dict):
                    brand = b.get("name")
                elif isinstance(b, str):
                    brand = b

                if not title:
                    title = clean_text(
                        obj.get("name")
                    )

        products = []

        blocks = soup.select(
            "tr, .product-item, .variant, "
            "[class*='variant'], [class*='swatch']"
        )

        for block in blocks:
            txt = clean_text(
                block.get_text(" ", strip=True)
            )

            if (
                "Réf" not in txt
                or "Fabricant" not in txt
            ):
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
                r"(En stock|Sur commande|"
                r"En réapprovisionnement|Arrêté|"
                r"Indisponible|Rupture)",
                txt,
                re.I,
            )

            record = self._records.get(
                url,
                {},
            )

            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=(
                        title
                        or clean_text(
                            txt[:gacd.start()]
                        )
                    ),
                    merchant_reference=gacd.group(1),
                    manufacturer_reference=mref.group(1),
                    brand=brand,
                    price=(
                        parse_price(
                            price_match.group(0)
                        )
                        if price_match
                        else None
                    ),
                    availability=normalize_stock(
                        stock_match.group(1)
                        if stock_match
                        else None
                    ),
                    attributes={
                        "source": "common_crawl",
                        "archive_timestamp": record.get(
                            "timestamp"
                        ),
                        "common_crawl_collection": record.get(
                            "_collection"
                        ),
                    },
                )
            )

        if not products:
            products = self._parse_text_variants(
                page_text,
                title,
                brand,
                url,
            )

        unique = {}

        for product in products:
            key = (
                product.merchant_reference,
                product.manufacturer_reference,
            )
            unique[key] = product

        return list(unique.values())
