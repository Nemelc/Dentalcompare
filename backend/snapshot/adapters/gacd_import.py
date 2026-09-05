import json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup
from core import Offer, begin_run, save_offers, finish_run

PRICE_RE = re.compile(r"(\d{1,5}(?:[ .]\d{3})*[,.]\d{2})\s*€")
GACD_RE = re.compile(r"Réf\.\s*GACD\s*:\s*([A-Z0-9-]+)", re.I)
FAB_RE = re.compile(r"Réf\.\s*Fabricant\s*:\s*([A-Z0-9+._ /-]+)", re.I)
STOCKS = ["En stock", "Sur commande", "En réapprovisionnement", "Arrêté"]

def parse_price(s):
    return float(s.replace("\u202f","").replace(" ","").replace(".","").replace(",", "."))

def parse_html(path):
    html=path.read_text(encoding="utf-8",errors="ignore"); soup=BeautifulSoup(html,"html.parser"); text=soup.get_text("\n",strip=True)
    title=soup.find("h1").get_text(" ",strip=True) if soup.find("h1") else path.stem
    canonical=soup.find("link",rel="canonical"); url=canonical.get("href","") if canonical else ""
    starts=[m.start() for m in GACD_RE.finditer(text)]; out=[]
    for i,start in enumerate(starts):
        block=text[start:(starts[i+1] if i+1<len(starts) else len(text))]
        gm=GACD_RE.search(block); fm=FAB_RE.search(block); price=PRICE_RE.search(block)
        stock=next((s for s in STOCKS if s.lower() in block.lower()),None)
        if gm: out.append(Offer(merchant="GACD",source_url=url or f"file://{path.name}",name=title,merchant_reference=gm.group(1).strip(),manufacturer_reference=fm.group(1).strip() if fm else None,price_eur=parse_price(price.group(1)) if price else None,availability=stock))
    return out

def parse_json(path):
    data=json.loads(path.read_text(encoding="utf-8")); products=data.get("products",data if isinstance(data,list) else []); out=[]
    for p in products:
        out.append(Offer(merchant="GACD",source_url=p.get("source_url") or data.get("source_url",""),name=p.get("name") or data.get("page_title") or "Produit GACD",merchant_reference=p.get("merchant_reference"),manufacturer_reference=p.get("manufacturer_reference"),ean=p.get("ean"),brand=p.get("brand"),category=p.get("category"),variant=p.get("variant"),packaging=p.get("packaging"),price_eur=p.get("price_eur"),availability=p.get("availability"),image_url=p.get("image_url"),captured_at=p.get("captured_at") or data.get("captured_at")))
    return out

def main():
    if len(sys.argv)<2: raise SystemExit("Usage: python adapters/gacd_import.py <dossier-ou-fichier>")
    target=Path(sys.argv[1]); files=[target] if target.is_file() else list(target.rglob("*.json"))+list(target.rglob("*.html")); offers=[]
    for p in files:
        try:
            parsed=parse_json(p) if p.suffix.lower()==".json" else parse_html(p); offers.extend(parsed); print(f"{p.name}: {len(parsed)} référence(s)")
        except Exception as e: print(f"[ERREUR] {p}: {e}")
    if not offers: raise SystemExit("Aucune référence GACD reconnue dans les captures.")
    run_id=begin_run("GACD","browser_capture_import",f"{len(files)} fichier(s)"); save_offers(run_id,offers); count=finish_run(run_id)
    print(f"Snapshot GACD #{run_id}: {count} offre(s) enregistrée(s).")

if __name__ == "__main__": main()
