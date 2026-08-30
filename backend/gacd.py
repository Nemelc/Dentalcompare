
import re
import time
from types import SimpleNamespace

import duckdb
from huggingface_hub import HfFileSystem
from warcio.archiveiterator import ArchiveIterator

from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class GACDScraper(BaseScraper):
    """
    DentalCompare - GACD via le miroir officiel Hugging Face de Common Crawl.

    v0.7
    - aucun appel direct à gacd.fr
    - aucun s3://
    - aucun appel à data.commoncrawl.org
    - URL Index lu via hf:// + HfFileSystem + DuckDB
    - captures WARC lues via le même bucket Hugging Face
    """

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    # Le miroir Hugging Face officiel contient ce crawl et ses URL Index.
    CRAWL = "CC-MAIN-2026-17"

    HF_BUCKET_ROOT = "buckets/commoncrawl/commoncrawl"
    HF_INDEX_ROOT = (
        "hf://buckets/commoncrawl/commoncrawl/"
        "cc-index/table/cc-main/warc/"
    )
    HF_CRAWL_ROOT = (
        "buckets/commoncrawl/commoncrawl/"
    )

    MAX_INDEX_RESULTS = 500

    def __init__(self, delay=0.15):
        super().__init__(delay=delay)
        self._records = {}

        # token=False : on force l'accès public, sans compte Hugging Face.
        self.hf = HfFileSystem(token=False)

    def _connection(self):
        con = duckdb.connect(database=":memory:")

        # DuckDB sait déléguer les lectures hf:// au filesystem fsspec
        # de Hugging Face.
        con.register_filesystem(self.hf)

        return con

    def _index_glob(self):
        return (
            f"{self.HF_INDEX_ROOT}"
            f"crawl={self.CRAWL}/subset=warc/*.parquet"
        )

    def _query_url_index(self):
        path = self._index_glob()

        print("Hugging Face : connexion au bucket Common Crawl...")
        print(f"Index : {self.CRAWL}")

        con = self._connection()

        sql = f"""
        SELECT
            url,
            warc_filename,
            warc_record_offset,
            warc_record_length
        FROM read_parquet(
            '{path}',
            union_by_name=true,
            hive_partitioning=true
        )
        WHERE
            (
                url_host_name = 'gacd.fr'
                OR url_host_name = 'www.gacd.fr'
            )
            AND fetch_status = 200
            AND (
                lower(url) LIKE '%.html'
                OR lower(url) LIKE '%/article-%'
            )
        LIMIT {int(self.MAX_INDEX_RESULTS)}
        """

        try:
            rows = con.execute(sql).fetchall()
        finally:
            con.close()

        records = []

        for url, filename, offset, length in rows:
            if (
                not url
                or not filename
                or offset is None
                or length is None
            ):
                continue

            records.append({
                "url": str(url),
                "filename": str(filename),
                "offset": int(offset),
                "length": int(length),
                "_collection": self.CRAWL,
            })

        return records

    def discover_product_urls(self):
        self._records = {}

        print(
            "GACD : recherche via le miroir Hugging Face "
            "de Common Crawl..."
        )

        try:
            records = self._query_url_index()
        except Exception as exc:
            raise RuntimeError(
                "Impossible de lire l'URL Index depuis Hugging Face. "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        print(
            f"Hugging Face : {len(records)} URL GACD candidates trouvées."
        )

        for row in records:
            url = row["url"]
            low = url.lower()

            # Pages clairement non-produits.
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
                "/blog/",
            )):
                continue

            self._records[url] = row

        if not self._records:
            raise RuntimeError(
                "L'URL Index Hugging Face a été interrogé, "
                "mais aucune page GACD exploitable n'a été trouvée."
            )

        print(
            f"GACD : {len(self._records)} pages candidates conservées."
        )

        return sorted(self._records.keys())

    @staticmethod
    def _hf_path_from_warc_filename(filename):
        filename = filename.lstrip("/")

        # Les chemins Common Crawl ressemblent à :
        # crawl-data/CC-MAIN-2026-17/segments/.../warc/....warc.gz
        return (
            "buckets/commoncrawl/commoncrawl/"
            + filename
        )

    def _fetch_warc_html(self, row):
        path = self._hf_path_from_warc_filename(
            row["filename"]
        )

        offset = int(row["offset"])
        length = int(row["length"])

        time.sleep(self.delay)

        # HfFileSystem/fsspec permet seek + read :
        # on ne télécharge donc que la zone du gros fichier WARC
        # contenant la page qui nous intéresse.
        with self.hf.open(path, "rb") as remote:
            remote.seek(offset)
            payload = remote.read(length)

        if not payload:
            raise RuntimeError(
                "Capture WARC vide depuis Hugging Face."
            )

        for record in ArchiveIterator(
            io.BytesIO(payload)
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
            "Aucune réponse HTML trouvée dans la capture WARC."
        )

    def get(self, url):
        row = self._records.get(url)

        if not row:
            raise KeyError(
                f"Capture Common Crawl introuvable : {url}"
            )

        html = self._fetch_warc_html(row)

        return SimpleNamespace(
            text=html,
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
                        "source": (
                            "common_crawl_huggingface"
                        ),
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
