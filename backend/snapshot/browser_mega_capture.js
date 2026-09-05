(() => {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const text = clean(document.body?.innerText || "");
  const title = clean(document.querySelector("h1")?.innerText || document.title);

  const first = (...selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return clean(el.textContent || el.getAttribute("content") || "");
    }
    return null;
  };

  const priceText = first(
    '[itemprop="price"]',
    '.price-wrapper [data-price-amount]',
    '.price-box .price',
    '.special-price .price',
    '.normal-price .price'
  ) || (text.match(/\b\d[\d\s\u202f]*(?:[,.]\d{2})\s*€/i)?.[0] || null);

  const price = priceText
    ? Number(priceText.replace(/[^0-9,.-]/g, "").replace(/\./g, "").replace(",", "."))
    : null;

  const refMatch = text.match(/\b(?:Réf\.?|Référence)\s*:?\s*([A-Z0-9][A-Z0-9._\/-]+)/i);
  const manufacturerRefMatch = text.match(/(?:Réf(?:érence)?\s+fabricant|Code\s+fabricant)\s*:?\s*([A-Z0-9._+\/-]+)/i);
  const eanMatch = text.match(/(?:EAN|GTIN)\s*:?\s*(\d{8,14})/i);
  const availabilityMatch = text.match(/(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture|Indisponible)/i);

  let brand = null;
  let image = null;
  try {
    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
      const parsed = JSON.parse(node.textContent);
      const items = Array.isArray(parsed) ? parsed : [parsed];
      for (const obj of items) {
        if (!obj || obj['@type'] !== 'Product') continue;
        if (!brand && obj.brand) brand = typeof obj.brand === 'object' ? obj.brand.name : obj.brand;
        if (!image && obj.image) image = Array.isArray(obj.image) ? obj.image[0] : obj.image;
      }
    }
  } catch (_) {}

  const product = {
    merchant: "Mega Dental",
    merchant_reference: refMatch ? refMatch[1] : null,
    manufacturer_reference: manufacturerRefMatch ? manufacturerRefMatch[1] : null,
    ean: eanMatch ? eanMatch[1] : null,
    name: title,
    brand: brand,
    price_eur: Number.isFinite(price) ? price : null,
    availability: availabilityMatch ? availabilityMatch[1] : null,
    image_url: image || document.querySelector('meta[property="og:image"]')?.content || null,
    source_url: location.href,
    captured_at: new Date().toISOString()
  };

  const payload = {
    source: "mega_dental_browser_capture",
    page_title: title,
    source_url: location.href,
    captured_at: new Date().toISOString(),
    products: [product]
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `mega_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  alert(`1 fiche Mega Dental capturée : ${title}`);
})();
