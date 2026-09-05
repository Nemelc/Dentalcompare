import json, re
from pathlib import Path
from core import connect, init_db

HERE=Path(__file__).resolve().parent
OUT_JSON=HERE/"data"/"latest_offers.json"

def norm_ref(s): return re.sub(r"[^A-Z0-9]","",(s or "").upper())

def main():
    init_db(); con=connect()
    merchants=[r["merchant"] for r in con.execute("SELECT DISTINCT merchant FROM snapshot_runs WHERE finished_at IS NOT NULL").fetchall()]; all_offers=[]
    for m in merchants:
        row=con.execute("SELECT id FROM snapshot_runs WHERE merchant=? AND finished_at IS NOT NULL ORDER BY finished_at DESC,id DESC LIMIT 1",(m,)).fetchone()
        if row: all_offers += [dict(r) for r in con.execute("SELECT * FROM offers WHERE run_id=?",(row["id"],)).fetchall()]
    con.close(); OUT_JSON.parent.mkdir(parents=True,exist_ok=True); OUT_JSON.write_text(json.dumps(all_offers,ensure_ascii=False,indent=2),encoding="utf-8")
    groups={}
    for o in all_offers:
        key=("ean",norm_ref(o["ean"])) if o.get("ean") else (("mref",norm_ref(o["manufacturer_reference"])) if o.get("manufacturer_reference") else ("merchant",o["merchant"],norm_ref(o.get("merchant_reference"))))
        groups.setdefault(key,[]).append(o)
    result=[]
    for offers in groups.values():
        first=offers[0]; prices=[]
        for o in offers:
            if o.get("price_eur") is not None: prices.append({"merchant":o["merchant"],"value":o["price_eur"],"url":o.get("source_url"),"availability":o.get("availability"),"merchantReference":o.get("merchant_reference"),"manufacturerReference":o.get("manufacturer_reference"),"capturedAt":o.get("captured_at")})
        result.append({"name":first.get("name"),"brand":first.get("brand"),"variant":first.get("variant"),"manufacturerReference":first.get("manufacturer_reference"),"ean":first.get("ean"),"image":first.get("image_url"),"prices":prices})
    print(f"{len(all_offers)} offres / {len(result)} produits canoniques -> {OUT_JSON}")

if __name__=="__main__": main()
