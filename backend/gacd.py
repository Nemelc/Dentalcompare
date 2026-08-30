
import re
import time
from types import SimpleNamespace

import duckdb
import requests
from warcio.archiveiterator import ArchiveIterator

from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class GACDScraper(BaseScraper):
    """
    GACD via le Common Crawl URL Index.

    v0.6 :
    - aucun accès direct à gacd.fr
    - aucun accès s3://
    - lecture des fichiers Parquet publics via HTTPS
    - crawl de test : CC-MAIN-2025-51
    """

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    # Common Crawl a publié le nom exact des fichiers de ce crawl.
    CRAWL = "CC-MAIN-2025-51"
    PARQUET_UUID = "2e1354aa-67a6-459b-81f6-7e2c39db0a5b"
    PARQUET_COUNT = 300

    CC_DATA_URL = "https://data.commoncrawl.org/"
    MAX_INDEX_RESULTS = 500

    def __init__(self, delay=0.15):
        super().__init__(delay=delay)
        self._records = {}

        self.archive_session = requests.Session()
        self.archive_session.headers.update({
            "User-Agent": "DentalCompare/0.6 (Common Crawl catalog research)",
            "Accept": "*/*",
        })

    def _connection(self):
        con = duckdb.connect(database=":memory:")

        try:
            con.execute("INSTALL httpfs")
        except Exception:
            pass

        con.execute("LOAD httpfs")

        # Un peu plus tolérant pour les lectures HTTP distantes.
        try:
            con.execute("SET http_timeout=60")
        except Exception:
            pass

        return con

    def _parquet_urls(self):
        base = (
            f"{self.CC_DATA_URL}"
            "cc-index/table/cc-main/warc/"
            f"crawl={self.CRAWL}/subset=warc/"
        )

        return [
            (
                f"{base}"
                f"part-{i:05d}-{self.PARQUET_UUID}.c000.gz.parquet"
            )
            for i in range(self.PARQUET_COUNT)
        ]

    @staticmethod
    def _sql_string(value):
        return "'" + value.replace("'", "''") + "'"

    def _query_url_index(self):
        urls = self._parquet_urls()

        # IMPORTANT :
        # On fournit à DuckDB la liste exacte des fichiers HTTPS.
        # Il n'a donc plus besoin de faire un LIST sur S3.
        parquet_list = ",\n".join(
            self._sql_string(url)
            for url in urls
        )

        sql = f"""
        SELECT
            url,
            warc_filename,
            warc_record_offset,
            warc_record_length
        FROM read_parquet(
            [{parquet_list}],
            union_by_name=true
        )
        WHERE
            url_host_name IN ('gacd.fr', 'www.gacd.fr')
            AND (
                lower(url) LIKE '%.html'
                OR lower(url) LIKE '%/article-%'
            )
        LIMIT {int(self.MAX_INDEX_RESULTS)}
        """

        con = self._connection()

        try:
            rows = con.execute(sql).fetchall()
        finally:
            con.close()

        result = []

        for url, filename, offset, length in rows:
            if (
                not url
                or not filename
                or offset is None
                or length is None
            ):
                continue

            result.append({
                "url": url,
                "filename": filename,
                "offset": int(offset),
                "length": int(length),
                "_collection": self.CRAWL,
            })

        return result

    def discover_product_urls(self):
        self._records = {}

        print(
            "GACD : recherche dans le Common Crawl URL Index "
            f"{self.CRAWL} via HTTPS..."
        )

        try:
            records = self._query_url_index()
        except Exception as exc:
            raise RuntimeError(
                "Impossible de lire l'URL Index Common Crawl via HTTPS. "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        print(
            f"Common Crawl : {len(records)} URL GACD candidates trouvées."
        )

        for row in records:
            url = row["url"]
            low = url.lower()

            # Élimine les pages clairement non-produit.
            if any(x in low for x in (
                "/centre-aide/",
                "/qui-sommes-nous/",
                "/catalogsearch/",
                "/customer/",
                "/checkout/",
                "/mentions-",
                "/conditions-",
                "/contact",
                "/faq",
            )):
                continue

            self._records[url] = row

        if not self._records:
            raise RuntimeError(
                "Le crawl a été lu correctement, mais aucune URL GACD "
                "exploitable n'a été trouvée."
            )

        print(
            f"GACD : {len(self._records)} pages candidates conservées."
        )

        return sorted(self._records.keys())

    def _fetch_warc_html(self, row):
        start = int(row["offset"])
        end = start + int(row["length"]) - 1

        filename = row["filename"]

        if filename.startswith("http://") or filename.startswith("https://"):
            warc_url = filename
        else:
            warc_url = self.CC_DATA_URL + filename.lstrip("/")

        time.sleep(self.delay)

        response = self.archive_session.get(
            warc_url,
            headers={
                "Range": f"bytes={start}-{end}",
            },
            timeout=60,
        )

        response.raise_for_status()

        for record in ArchiveIterator(
            io.BytesIO(response.content)
        ):
            if record.rec_type != "response":
                continue

            raw = record.content_stream().read()

            content_type = ""

            if record.http_headers:
                content_type = (
                    record.http_headers.get_header(
                        "Content-Type"
                    )
                    or ""
                )

            charset = "utf-8"

            match = re.search(
                r"charset=([A-Za-z0-9._-]+)",
                content_type,
                re.I,
            )

            if match:
                charset = match.group(1)

            try:
                return raw.decode(
                    charset,
                    errors="replace",
                )
            except LookupError:
                return raw.decode(
                    "utf-8",
                    errors="replace",
                )

        raise RuntimeError(
            "Capture WARC HTML introuvable."
        )

    def get(self, url):
        row = self._records.get(url)

        if not row:
            raise KeyError(
                f"Capture Common Crawl introuvable : {url}"
            )

        return SimpleNamespace(
            text=self._fetch_warc_html(row),
            status_code=200,
            url=url,
        )

    @staticmethod
    def _variant_name(
        segment,
        gacd_match,
        mref_match,
    ):
        candidate = clean_text(
            segment[
                gacd_match.end():
                mref_match.start()
            ]
        )

        labels = [
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

        pattern = "|".join(
            re.escape(x)
            for x in labels
        )

        candidate = re.split(
            rf"\b(?:{pattern})\s*:",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]

        return clean_text(
            candidate.strip(" :-|")
        )

    def _parse_variants(
        self,
        text,
        title,
        brand,
        url,
    ):
        markers = list(
            re.finditer(
                r"Réf\.?\s*GACD\s*:?\s*([A-Z0-9-]+)",
                text,
                re.I,
            )
        )

        products = []

        for i, gacd_match in enumerate(markers):
            end = (
                markers[i + 1].start()
                if i + 1 < len(markers)
                else len(text)
            )

            segment = text[
                gacd_match.start():end
            ]

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

            after_ref = segment[
                mref.end():
            ]

            stock = re.search(
                r"(En stock|Sur commande|"
                r"En réapprovisionnement|Arrêté|"
                r"Indisponible|Rupture)",
                after_ref,
                re.I,
            )

            price = re.search(
                r"\d[\d\s\u202f.]*(?:,\d{1,2})?\s*€",
                after_ref,
            )

            meta = self._records.get(
                url,
                {},
            )

            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=name,
                    merchant_reference=(
                        gacd_match.group(1)
                    ),
                    manufacturer_reference=(
                        mref.group(1)
                    ),
                    brand=brand,
                    price=(
                        parse_price(
                            price.group(0)
                        )
                        if price
                        else None
                    ),
                    availability=normalize_stock(
                        stock.group(1)
                        if stock
                        else None
                    ),
                    attributes={
                        "source": "common_crawl_url_index_https",
                        "common_crawl_collection": (
                            meta.get("_collection")
                        ),
                    },
                )
            )

        return products

    def parse_product(
        self,
        url,
        html,
    ):
        soup = self.soup(html)

        h1 = soup.find("h1")

        title = clean_text(
            h1.get_text(
                " ",
                strip=True,
            )
            if h1
            else ""
        )

        text = clean_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        brand = None

        for obj in self.json_ld(soup):
            obj_type = obj.get("@type")

            if (
                obj_type == "Product"
                or (
                    isinstance(
                        obj_type,
                        list,
                    )
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

        products = self._parse_variants(
            text,
            title,
            brand,
            url,
        )

        unique = {}

        for product in products:
            unique[
                (
                    product.merchant_reference,
                    product.manufacturer_reference,
                )
            ] = product

        return list(
            unique.values()
        )
