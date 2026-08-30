import json


def export_frontend(conn, output_path):
    rows = conn.execute("""
    WITH latest AS (
      SELECT o.*, ROW_NUMBER() OVER(PARTITION BY merchant_product_id ORDER BY scraped_at DESC) rn
      FROM offers o
    )
    SELECT p.id,p.canonical_name,p.brand,p.manufacturer_reference,p.category,
           mp.merchant,mp.name merchant_name,mp.url,mp.image_url,mp.availability,mp.source_category,
           l.price,l.scraped_at
      FROM products p
      JOIN merchant_products mp ON mp.product_id=p.id
      LEFT JOIN latest l ON l.merchant_product_id=mp.id AND l.rn=1
     ORDER BY p.id, mp.merchant
    """).fetchall()

    products = {}
    for r in rows:
        p = products.setdefault(r["id"], {
            "id": f"dc-{r['id']}",
            "name": r["canonical_name"],
            "brand": r["brand"],
            "manufacturer_reference": r["manufacturer_reference"],
            "category": r["category"],
            "image_url": r["image_url"],
            "prices": []
        })
        if not p["image_url"] and r["image_url"]:
            p["image_url"] = r["image_url"]
        p["prices"].append({
            "merchant": r["merchant"],
            "value": r["price"],
            "url": r["url"],
            "in_stock": r["availability"] == "in_stock",
            "availability": r["availability"],
            "scraped_at": r["scraped_at"]
        })

    payload = list(products.values())
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("// Generated automatically by DentalCompare backend. Do not edit manually.\n")
        f.write("window.DENTALCOMPARE_PRODUCTS = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    return len(payload)
