
import io
import json
import re
import time
from types import SimpleNamespace

import requests
from warcio.archiveiterator import ArchiveIterator

from models import MerchantProduct
from normalize import clean_text, parse_price, normalize_stock
from base import BaseScraper


class GACDScraper(BaseScraper):
    """
    DentalCompare - GACD via l'index brut Common Crawl (ZipNum/CDXJ).

    v0.8 :
    - pas d'appel direct à gacd.fr
    - pas de DuckDB
    - pas de scan des centaines de fichiers Parquet
    - pas d'API index.commoncrawl.org
    - recherche binaire dans cluster.idx via HTTP Range
    - téléchargement uniquement des petits blocs CDX utiles
    """

    merchant = "GACD"
    base_url = "https://www.gacd.fr"

    CRAWL = "CC-MAIN-2026-25"

    INDEX_BASE = (
        "https://data.commoncrawl.org/"
        f"cc-index/collections/{CRAWL}/indexes/"
    )

    CLUSTER_URL = INDEX_BASE + "cluster.idx"
    DATA_BASE = "https://data.commoncrawl.org/"

    # Plage SURT couvrant tout le domaine gacd.fr :
    # apex + www + éventuels autres sous-domaines.
    DOMAIN_LO = "fr,gacd)"
    DOMAIN_HI = "fr,gacd-"

    # Nombre maximal d'URL candidates avant filtrage.
    MAX_URLS = 200

    # Fenêtre utilisée pour la recherche binaire distante.
    SEARCH_WINDOW = 65536

    def __init__(self, delay=0.15):
        super().__init__(delay=delay)

        self._records = {}

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "DentalCompare/0.8 "
                "(Common Crawl index research)"
            ),
            "Accept": "*/*",
        })

    # ------------------------------------------------------------------
    # HTTP Range helpers
    # ------------------------------------------------------------------

    def _get_remote_size(self, url):
        """
        Détermine la taille d'un fichier distant sans le télécharger.
        """
        try:
            response = self.session.head(
                url,
                timeout=30,
                allow_redirects=True,
            )

            if response.ok:
                length = response.headers.get("Content-Length")

                if length:
                    return int(length)
        except requests.RequestException:
            pass

        # Fallback : demande un seul octet.
        response = self.session.get(
            url,
            headers={"Range": "bytes=0-0"},
            timeout=30,
        )
        response.raise_for_status()

        content_range = response.headers.get("Content-Range", "")

        match = re.search(r"/(\d+)$", content_range)

        if not match:
            raise RuntimeError(
                "Impossible de déterminer la taille de cluster.idx."
            )

        return int(match.group(1))

    def _range_get(self, url, start, end, timeout=45):
        response = self.session.get(
            url,
            headers={
                "Range": f"bytes={int(start)}-{int(end)}",
            },
            timeout=timeout,
        )

        response.raise_for_status()

        return response.content

    # ------------------------------------------------------------------
    # cluster.idx
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_cluster_line(line):
        """
        Format cluster.idx :
        <clé SURT> <timestamp> <cdx-file> <offset> <length> <block-id>
        Les deux premiers champs forment la clé de tri.
        """
        line = line.strip()

        if not line:
            return None

        parts = re.split(r"\s+", line)

        if len(parts) < 6:
            return None

        try:
            return {
                "surt": parts[0],
                "timestamp": parts[1],
                "cdx_file": parts[2],
                "offset": int(parts[3]),
                "length": int(parts[4]),
                "block_id": int(parts[5]),
                "raw": line,
            }
        except (TypeError, ValueError):
            return None

    def _line_near_offset(self, offset, file_size):
        """
        Récupère une ligne complète de cluster.idx autour d'un offset.
        """
        half = self.SEARCH_WINDOW // 2

        start = max(0, int(offset) - half)
        end = min(
            file_size - 1,
            int(offset) + half,
        )

        payload = self._range_get(
            self.CLUSTER_URL,
            start,
            end,
        )

        text = payload.decode(
            "utf-8",
            errors="replace",
        )

        # Position correspondant exactement à offset dans notre fenêtre.
        local = int(offset) - start

        # Cherche le début de la ligne.
        left = text.rfind("\n", 0, local)

        if left == -1:
            line_start = 0
        else:
            line_start = left + 1

        # Cherche la fin de la ligne.
        right = text.find("\n", local)

        if right == -1:
            line_end = len(text)
        else:
            line_end = right

        line = text[line_start:line_end]

        parsed = self._parse_cluster_line(line)

        if parsed is None:
            raise RuntimeError(
                "Impossible de lire une ligne valide de cluster.idx."
            )

        parsed["_absolute_start"] = start + line_start

        return parsed

    def _find_cluster_position(self, target):
        """
        Recherche binaire distante dans cluster.idx.
        Renvoie un offset situé au voisinage de la première clé >= target.
        """
        file_size = self._get_remote_size(
            self.CLUSTER_URL
        )

        low = 0
        high = file_size - 1

        # 40 itérations couvrent largement un fichier de ~100 Mo.
        for _ in range(40):
            if high - low < self.SEARCH_WINDOW:
                break

            mid = (low + high) // 2

            row = self._line_near_offset(
                mid,
                file_size,
            )

            key = row["surt"]

            if key < target:
                low = max(
                    low + 1,
                    row["_absolute_start"] + 1,
                )
            else:
                high = min(
                    high - 1,
                    row["_absolute_start"],
                )

        return max(0, low - self.SEARCH_WINDOW)

    def _cluster_rows_for_prefix(self, prefix):
        """
        Lit seulement la petite zone de cluster.idx autour du domaine cible.
        On garde aussi quelques blocs juste avant/après, car la première URL
        du domaine peut commencer dans le bloc précédent.
        """
        file_size = self._get_remote_size(
            self.CLUSTER_URL
        )

        pos = self._find_cluster_position(prefix)

        # Une zone de 1 Mo autour du point trouvé reste très petite
        # comparée au cluster.idx complet (~100 Mo).
        start = max(
            0,
            pos - 262144,
        )
        end = min(
            file_size - 1,
            pos + 786432,
        )

        payload = self._range_get(
            self.CLUSTER_URL,
            start,
            end,
        )

        text = payload.decode(
            "utf-8",
            errors="replace",
        )

        rows = []

        for line in text.splitlines():
            row = self._parse_cluster_line(line)

            if row:
                rows.append(row)

        if not rows:
            return []

        # Repère la première ligne >= prefix.
        idx = 0

        for i, row in enumerate(rows):
            if row["surt"] >= prefix:
                idx = i
                break
        else:
            idx = len(rows) - 1

        # Le bloc précédent peut contenir le début de la plage.
        first = max(0, idx - 2)

        # Quelques blocs suffisent pour notre test initial.
        last = min(
            len(rows),
            idx + 8,
        )

        return rows[first:last]

    # ------------------------------------------------------------------
    # CDX blocks
    # ------------------------------------------------------------------

    def _fetch_cdx_block(self, row):
        url = self.INDEX_BASE + row["cdx_file"]

        payload = self._range_get(
            url,
            row["offset"],
            row["offset"] + row["length"] - 1,
        )

        try:
            data = gzip.decompress(payload)
        except OSError as exc:
            raise RuntimeError(
                f"Bloc CDX non décompressable : {row['cdx_file']} "
                f"offset={row['offset']}"
            ) from exc

        return data.decode(
            "utf-8",
            errors="replace",
        )

    @staticmethod
    def _parse_cdx_line(line):
        """
        CDXJ :
        <urlkey> <timestamp> {json}
        """
        try:
            urlkey, timestamp, payload = line.split(
                " ",
                2,
            )
            meta = json.loads(payload)
        except Exception:
            return None

        return {
            "urlkey": urlkey,
            "timestamp": timestamp,
            **meta,
        }

    @staticmethod
    def _is_gacd_urlkey(urlkey):
        return (
            urlkey.startswith("fr,gacd)/")
            or urlkey.startswith("fr,gacd,www)/")
        )

    @staticmethod
    def _looks_like_product_url(url):
        if not url:
            return False

        low = url.lower()

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
            "/media/",
            "/static/",
        )):
            return False

        return (
            low.endswith(".html")
            or "/article-" in low
        )

    def discover_product_urls(self):
        self._records = {}

        print(
            "GACD : chargement de cluster.idx "
            f"({self.CRAWL})..."
        )

        # Pour ce crawl, cluster.idx fait environ 101 Mo.
        # Le télécharger en entier rend la sélection du domaine
        # beaucoup plus fiable qu'une recherche binaire HTTP distante.
        response = self.session.get(
            self.CLUSTER_URL,
            timeout=120,
        )
        response.raise_for_status()

        text = response.text

        rows = []

        for line in text.splitlines():
            row = self._parse_cluster_line(line)
            if row:
                rows.append(row)

        if not rows:
            raise RuntimeError(
                "cluster.idx a été téléchargé mais aucune ligne "
                "valide n'a été lue."
            )

        print(
            f"cluster.idx : {len(rows)} blocs indexés."
        )
        print(
            "GACD : recherche de la plage SURT "
            f"[{self.DOMAIN_LO}, {self.DOMAIN_HI})..."
        )

        # cluster.idx contient la première clé de chaque bloc.
        # On prend le bloc juste avant DOMAIN_LO puis on avance
        # jusqu'à ce que le début du bloc dépasse DOMAIN_HI.
        candidate_rows = []

        first_idx = 0

        for i, row in enumerate(rows):
            if row["surt"] >= self.DOMAIN_LO:
                first_idx = max(0, i - 1)
                break
        else:
            first_idx = max(0, len(rows) - 1)

        for row in rows[first_idx:]:
            # Une fois au-delà de la borne haute, les blocs suivants
            # ne peuvent plus contenir gacd.fr.
            if (
                candidate_rows
                and row["surt"] >= self.DOMAIN_HI
            ):
                break

            candidate_rows.append(row)

            # Garde-fou : un domaine comme GACD ne devrait pas
            # nécessiter des centaines de blocs pour le test.
            if len(candidate_rows) >= 40:
                break

        print(
            f"GACD : {len(candidate_rows)} blocs CDX à examiner."
        )

        for row in candidate_rows:
            try:
                cdx_text = self._fetch_cdx_block(row)
            except Exception as exc:
                print(
                    f"  Bloc ignoré : {exc}"
                )
                continue

            for line in cdx_text.splitlines():
                item = self._parse_cdx_line(line)

                if not item:
                    continue

                urlkey = item["urlkey"]

                # Tout gacd.fr, y compris www et sous-domaines,
                # doit être dans cette plage SURT.
                if not (
                    self.DOMAIN_LO
                    <= urlkey
                    < self.DOMAIN_HI
                ):
                    continue

                if str(
                    item.get("status", "")
                ) != "200":
                    continue

                url = item.get("url")

                if not self._looks_like_product_url(
                    url
                ):
                    continue

                filename = item.get("filename")
                offset = item.get("offset")
                length = item.get("length")

                if (
                    not filename
                    or offset is None
                    or length is None
                ):
                    continue

                candidate = {
                    "url": url,
                    "filename": filename,
                    "offset": int(offset),
                    "length": int(length),
                    "timestamp": item.get("timestamp"),
                    "_collection": self.CRAWL,
                }

                current = self._records.get(url)

                if (
                    current is None
                    or str(
                        candidate.get("timestamp", "")
                    )
                    > str(
                        current.get("timestamp", "")
                    )
                ):
                    self._records[url] = candidate

                if len(self._records) >= self.MAX_URLS:
                    break

            if len(self._records) >= self.MAX_URLS:
                break

        if not self._records:
            raise RuntimeError(
                "La plage gacd.fr a été examinée dans l'index "
                "Common Crawl, mais aucune fiche produit HTTP 200 "
                "n'a été trouvée dans ce crawl."
            )

        print(
            f"GACD : {len(self._records)} URL produit candidates trouvées."
        )

        for i, url in enumerate(
            sorted(self._records)[:10],
            1,
        ):
            print(
                f"  URL {i}: {url}"
            )

        return sorted(
            self._records.keys()
        )

    # ------------------------------------------------------------------
    # WARC
    # ------------------------------------------------------------------

    def _fetch_warc_html(self, row):
        start = int(row["offset"])
        length = int(row["length"])
        end = start + length - 1

        warc_url = (
            self.DATA_BASE
            + row["filename"].lstrip("/")
        )

        time.sleep(self.delay)

        payload = self._range_get(
            warc_url,
            start,
            end,
            timeout=60,
        )

        for record in ArchiveIterator(
            io.BytesIO(payload)
        ):
            if record.rec_type != "response":
                continue

            raw = (
                record.content_stream().read()
            )

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
            "Aucune réponse HTML dans la capture WARC."
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

    # ------------------------------------------------------------------
    # GACD parser
    # ------------------------------------------------------------------

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

        for i, gacd_match in enumerate(
            markers
        ):
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
                            "common_crawl_cluster_idx"
                        ),
                        "common_crawl_collection": (
                            meta.get("_collection")
                        ),
                        "archive_timestamp": (
                            meta.get("timestamp")
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
