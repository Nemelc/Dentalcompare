import gzip
import json
import re
import requests


CRAWL = "CC-MAIN-2026-25"
INDEX_BASE = (
    "https://data.commoncrawl.org/"
    f"cc-index/collections/{CRAWL}/indexes/"
)
CLUSTER_URL = INDEX_BASE + "cluster.idx"

DOMAIN_LO = "fr,gacd)"
DOMAIN_HI = "fr,gacd-"


def parse_cluster_line(line):
    parts = re.split(r"\s+", line.strip())

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
        }
    except Exception:
        return None


def parse_cdx_line(line):
    try:
        urlkey, timestamp, payload = line.split(" ", 2)
        meta = json.loads(payload)
        return {
            "urlkey": urlkey,
            "timestamp": timestamp,
            **meta,
        }
    except Exception:
        return None


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "DentalCompare-CDX-Diagnostic/1.0",
        "Accept": "*/*",
    })

    print(f"Diagnostic Common Crawl : {CRAWL}")
    print("Téléchargement de cluster.idx...")

    r = session.get(CLUSTER_URL, timeout=120)
    r.raise_for_status()

    rows = []

    for line in r.text.splitlines():
        row = parse_cluster_line(line)
        if row:
            rows.append(row)

    print(f"cluster.idx : {len(rows)} blocs indexés.")

    first_idx = None

    for i, row in enumerate(rows):
        if row["surt"] >= DOMAIN_LO:
            first_idx = max(0, i - 1)
            break

    if first_idx is None:
        raise RuntimeError(
            "Impossible de localiser la zone gacd.fr dans cluster.idx"
        )

    candidates = []

    for row in rows[first_idx:first_idx + 10]:
        if (
            candidates
            and row["surt"] >= DOMAIN_HI
        ):
            break
        candidates.append(row)

    print("")
    print("Blocs cluster.idx autour de GACD :")

    for i, row in enumerate(candidates, 1):
        print(
            f"{i}. surt={row['surt']} "
            f"file={row['cdx_file']} "
            f"offset={row['offset']} "
            f"length={row['length']}"
        )

    print("")
    print("Lecture brute des blocs CDX...")

    total_lines = 0
    gacd_lines = 0

    for block_num, row in enumerate(candidates, 1):
        url = INDEX_BASE + row["cdx_file"]

        rr = session.get(
            url,
            headers={
                "Range": (
                    f"bytes={row['offset']}-"
                    f"{row['offset'] + row['length'] - 1}"
                )
            },
            timeout=60,
        )
        rr.raise_for_status()

        try:
            payload = gzip.decompress(rr.content)
        except Exception as exc:
            print(
                f"BLOC {block_num}: erreur gzip: {exc}"
            )
            continue

        text = payload.decode("utf-8", errors="replace")

        print("")
        print(
            f"===== BLOC {block_num} ====="
        )

        block_total = 0
        block_gacd = 0

        for line in text.splitlines():
            item = parse_cdx_line(line)

            if not item:
                continue

            block_total += 1
            total_lines += 1

            urlkey = item.get("urlkey", "")
            url_value = item.get("url", "")
            status = item.get("status", "")
            mime = item.get("mime", "")
            filename = item.get("filename", "")

            # On affiche :
            # 1) toute ligne qui ressemble à gacd
            # 2) sinon quelques lignes autour pour voir la zone réelle.
            is_gacd = (
                "gacd" in urlkey.lower()
                or "gacd" in str(url_value).lower()
            )

            if is_gacd:
                block_gacd += 1
                gacd_lines += 1

                print(
                    "GACD | "
                    f"urlkey={urlkey} | "
                    f"status={status} | "
                    f"mime={mime} | "
                    f"url={url_value}"
                )

                if filename:
                    print(
                        f"      warc={filename}"
                    )

        print(
            f"Bloc {block_num}: "
            f"{block_total} lignes CDX, "
            f"{block_gacd} ligne(s) contenant 'gacd'."
        )

    print("")
    print("===== RÉSUMÉ =====")
    print(f"Lignes CDX lues : {total_lines}")
    print(f"Lignes contenant 'gacd' : {gacd_lines}")

    if gacd_lines == 0:
        print("")
        print(
            "Aucune ligne contenant 'gacd' dans les blocs sélectionnés."
        )
        print(
            "Cela indiquera que notre sélection de blocs autour "
            "de la borne SURT est incorrecte."
        )
    else:
        print("")
        print(
            "Des lignes GACD ont été trouvées. "
            "Copie les lignes GACD du log pour corriger "
            "le filtre du scraper."
        )


if __name__ == "__main__":
    main()
