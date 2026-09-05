import json, sys
from pathlib import Path
from core import Offer, begin_run, save_offers, finish_run


def parse_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    products = data.get("products", data if isinstance(data, list) else [])
    out = []
    for p in products:
        out.append(Offer(
            merchant="Mega Dental",
            source_url=p.get("source_url") or data.get("source_url", ""),
            name=p.get("name") or data.get("page_title") or "Produit Mega Dental",
            merchant_reference=p.get("merchant_reference"),
            manufacturer_reference=p.get("manufacturer_reference"),
            ean=p.get("ean"),
            brand=p.get("brand"),
            category=p.get("category"),
            variant=p.get("variant"),
            packaging=p.get("packaging"),
            price_eur=p.get("price_eur"),
            availability=p.get("availability"),
            image_url=p.get("image_url"),
            captured_at=p.get("captured_at") or data.get("captured_at")
        ))
    return out


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python adapters/mega_import.py <dossier-ou-fichier>")

    target = Path(sys.argv[1])
    files = [target] if target.is_file() else list(target.rglob("*.json"))
    offers = []

    for p in files:
        try:
            parsed = parse_json(p)
            offers.extend(parsed)
            print(f"{p.name}: {len(parsed)} référence(s)")
        except Exception as e:
            print(f"[ERREUR] {p}: {e}")

    if not offers:
        raise SystemExit("Aucune référence Mega Dental reconnue dans les captures.")

    run_id = begin_run("Mega Dental", "browser_capture_import", f"{len(files)} fichier(s)")
    save_offers(run_id, offers)
    count = finish_run(run_id)
    print(f"Snapshot Mega Dental #{run_id}: {count} offre(s) enregistrée(s).")


if __name__ == "__main__":
    main()
