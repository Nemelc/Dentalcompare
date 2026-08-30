import io
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
    """Récupère des copies archivées de pages GACD via le Common Crawl URL Index."""

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    CRAWLS = [
        "CC-MAIN-2026-25",
        "CC-MAIN-2026-21",
        "CC-MAIN-2026-17",
        "CC-MAIN-2026-12",
        "CC-MAIN-2026-08",
        "CC-MAIN-2026-04",
        "CC-MAIN-2025-51",
        "CC-MAIN-2025-47",
    ]

    CC_DATA_URL = "https://data.commoncrawl.org/"
    MAX_INDEX_RESULTS = 500

    def __init__(self, delay=0.15):
        super().__init__(delay=delay)
        self._records = {}
        self.archive_session = requests.Session()
        self.archive_session.headers.update({
            "User-Agent": "DentalCompare/0.4 (Common Crawl catalog research)",
            "Accept": "*/*",
        })

    def _connection(self):
        con = duckdb.connect(database=":memory:")
        try:
            con.execute("INSTALL httpfs")
        except Exception:
            pass
        con.execute("LOAD httpfs")
        con.execute("SET s3_region='us-east-1'")
        return con

    def _query_url_index(self, crawl):
        path = (
            "s3://commoncrawl/cc-index/table/cc-main/warc/"
            f"crawl={crawl}/subset=warc/*.parquet"
        )

        sql = f"""
        SELECT
            url,
            warc_filename,
            warc_record_offset,
            warc_record_length,
            fetch_status
        FROM read_parquet('{path}', hive_partitioning=true)
        WHERE
            url_host_registered_domain = 'gacd.fr'
            AND fetch_status = 200
            AND (
                lower(url) LIKE '%.html'
                OR lower(url) LIKE '%/article-%'
            )
        LIMIT {self.MAX_INDEX_RESULTS}
        """

        con = self._connection()
        try:
            rows = con.execute(sql).fetchall()
        finally:
            con.close()

        result = []
        for url, filename, offset, length, status in rows:
            if not url or not filename or offset is None or length is None:
                continue
            result.append({
                "url": url,
                "filename": filename,
                "offset": int(offset),
                "length": int(length),
                "status": status,
                "_collection": crawl,
            })
        return result

    def discover_product_urls(self):
        self._records = {}
        errors = []

        print("GACD : recherche dans le Common Crawl URL Index...")

        for i, crawl in enumerate(self.CRAWLS, 1):
            print(f"[{i}/{len(self.CRAWLS)}] {crawl}")

            try:
                records = self._query_url_index(crawl)
            except Exception as exc:
                errors.append(f"{crawl}: {type(exc).__name__}: {exc}")
                print(f"  erreur : {exc}")
                continue

            for row in records:
                url = row["url"]
                low = url.lower()

                if any(x in low for x in (
                    "/centre-aide/",
                    "/qui-sommes-nous/",
                    "/catalogsearch/",
                    "/customer/",
                    "/checkout/",
                    "/mentions-",
                    "/conditions-",
                )):
                    continue

                self._records[url] = row

            if self._records:
                print(
                    f"  {len(self._records)} pages GACD trouvées dans {crawl}"
                )
                break

            print("  0 page GACD trouvée")

        if not self._records:
            details = " | ".join(errors[-3:]) if errors else "aucun résultat"
            raise RuntimeError(
                "Aucune page GACD trouvée via le Common Crawl URL Index. "
                f"Détails : {details}"
            )

        return sorted(self._records.keys())

    def _fetch_warc_html(self, row):
        start = row["offset"]
        end = start + row["length"] - 1
        warc_url = self.CC_DATA_URL + row["filename"]

        time.sleep(self.delay)

        response = self.archive_session.get(
            warc_url,
            headers={"Range": f"bytes={start}-{end}"},
            timeout=45,
        )
        response.raise_for_status()

        for record in ArchiveIterator(io.BytesIO(response.content)):
            if record.rec_type != "response":
                continue

            raw = record.content_stream().read()
            content_type = ""

            if record.http_headers:
                content_type = (
                    record.http_headers.get_header("Content-Type") or ""
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
                return raw.decode(charset, errors="replace")
            except LookupError:
                return raw.decode("utf-8", errors="replace")

        raise RuntimeError("Capture WARC HTML introuvable.")

    def get(self, url):
        row = self._records.get(url)
        if not row:
            raise KeyError(f"Capture Common Crawl introuvable : {url}")

        return SimpleNamespace(
            text=self._fetch_warc_html(row),
            status_code=200,
            url=url,
        )

    @staticmethod
    def _variant_name(segment, gacd_match, mref_match):
        candidate = clean_text(
            segment[gacd_match.end():mref_match.start()]
        )

        labels = [
            "TEINTE", "COULEUR", "DIMENSION",
            "DIAMETRE-DIMENSION", "DIAMÈTRE-DIMENSION",
            "LONGUEUR", "N°", "MORS", "PRISE", "PARFUM", "TAILLE",
            "EPAISSEUR", "ÉPAISSEUR", "TYPE", "MODELE", "MODÈLE",
            "GRAIN", "ISO", "CONDITIONNEMENT", "QUANTITE",
            "QUANTITÉ", "ESPACEMENT",
        ]
        pattern = "|".join(re.escape(x) for x in labels)

        candidate = re.split(
            rf"\b(?:{pattern})\s*:",
            candidate,
            maxsplit=1,
            flags=re.I,
        )[0]

        return clean_text(candidate.strip(" :-|"))

    def _parse_variants(self, text, title, brand, url):
        markers = list(re.finditer(
            r"Réf\.?\s*GACD\s*:?\s*([A-Z0-9-]+)",
            text,
            re.I,
        ))
        products = []

        for i, gacd_match in enumerate(markers):
            end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            segment = text[gacd_match.start():end]

            mref = re.search(
                r"Réf\.?\s*Fabricant\s*:?\s*([^\s€|]+)",
                segment,
                re.I,
            )
            if not mref:
                continue

            name = self._variant_name(segment, gacd_match, mref) or title
            after_ref = segment[mref.end():]

            stock = re.search(
                r"(En stock|Sur commande|En réapprovisionnement|"
                r"Arrêté|Indisponible|Rupture)",
                after_ref,
                re.I,
            )

            price = re.search(
                r"\d[\d\s\u202f.]*(?:,\d{1,2})?\s*€",
                after_ref,
            )

            meta = self._records.get(url, {})

            products.append(
                MerchantProduct(
                    merchant=self.merchant,
                    url=url,
                    name=name,
                    merchant_reference=gacd_match.group(1),
                    manufacturer_reference=mref.group(1),
                    brand=brand,
                    price=parse_price(price.group(0)) if price else None,
                    availability=normalize_stock(
                        stock.group(1) if stock else None
                    ),
                    attributes={
                        "source": "common_crawl_url_index",
                        "common_crawl_collection": meta.get("_collection"),
                    },
                )
            )

        return products

    def parse_product(self, url, html):
        soup = self.soup(html)

        h1 = soup.find("h1")
        title = clean_text(
            h1.get_text(" ", strip=True) if h1 else ""
        )
        text = clean_text(soup.get_text(" ", strip=True))

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

        return list(unique.values())
