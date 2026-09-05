(() => {
  const clean = s => (s || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
  const bodyText = clean(document.body?.innerText || "");
  const title = clean(document.querySelector("h1")?.innerText || document.title);

  const textOf = el => el ? clean(el.textContent || el.getAttribute?.("content") || "") : null;
  const firstText = (...selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      const value = textOf(el);
      if (value) return value;
    }
    return null;
  };
  const firstAttr = (attr, ...selectors) => {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      const value = clean(el?.getAttribute?.(attr) || "");
      if (value) return value;
    }
    return null;
  };
  const parsePrice = s => {
    if (!s) return null;
    const m = clean(s).match(/(\d{1,5}(?:[ .\u202f]\d{3})*[,.]\d{2})\s*€/);
    if (!m) return null;
    const normalized = m[1].replace(/[ .\u202f]/g, "").replace(",", ".");
    const n = Number(normalized);
    return Number.isFinite(n) ? n : null;
  };

  // Prefer the active product price area, never the first euro amount found in the whole page.
  let price = null;
  const priceSelectors = [
    '[itemprop="price"]',
    '[data-price-type="finalPrice"] .price',
    '.special-price .price',
    '.price-box .price-final_price .price',
    '.price-box .price'
  ];
  for (const sel of priceSelectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const attr = el.getAttribute?.('content') || el.getAttribute?.('data-price-amount');
    if (attr && /^\d+(?:\.\d+)?$/.test(attr)) {
      const n = Number(attr);
      if (Number.isFinite(n)) { price = n; break; }
    }
    const n = parsePrice(el.textContent);
    if (n != null) { price = n; break; }
  }
  if (price == null) {
    // Mega pages place the current price immediately after MPN/Fournisseur in the product summary.
    const summary = firstText('.product-info-main', '.product-info-price', 'main') || bodyText;
    const aroundMpn = summary.match(/MPN\s*:\s*[^€]{0,120}?(\d{1,5}(?:[ .\u202f]\d{3})*[,.]\d{2})\s*€/i);
    price = aroundMpn ? parsePrice(aroundMpn[0]) : null;
  }

  // Merchant reference: use dedicated SKU fields only. Do not infer it from generic "Réf." text,
  // because Mega pages contain unrelated labels such as cart/search UI.
  let merchantReference = firstText(
    '[itemprop="sku"]',
    '.product.attribute.sku .value',
    '.product-info-main .sku .value',
    '[data-product-sku]'
  );
  if (!merchantReference) {
    merchantReference = firstAttr('data-product-sku', '[data-product-sku]');
  }
  if (merchantReference) {
    merchantReference = clean(merchantReference.replace(/^(?:SKU|Réf(?:érence)?|Numéro de référence)\s*:?\s*/i, ""));
  }

  let manufacturerReference = null;
  const mpnMatch = bodyText.match(/\bMPN\s*:\s*([^\n|]{1,60})/i);
  if (mpnMatch) {
    const v = clean(mpnMatch[1]).split(/\s{2,}|\b(?:En stock|Rupture|Disponible)\b/i)[0];
    if (v && !/^(?:S\/?O|N\/?A|NC|Non renseigné)$/i.test(v)) manufacturerReference = v;
  }
  if (!manufacturerReference) {
    const m = bodyText.match(/(?:Réf(?:érence)?\s+fabricant|Code\s+fabricant)\s*:?\s*([A-Z0-9._+\/-]+)/i);
    manufacturerReference = m ? m[1] : null;
  }

  const eanMatch = bodyText.match(/(?:EAN|GTIN)\s*:?\s*(\d{8,14})/i);
  const availabilityMatch = bodyText.match(/\b(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture de stock|Indisponible)\b/i);

  let brand = null;
  let image = null;
  try {
    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
      const parsed = JSON.parse(node.textContent);
      const queue = Array.isArray(parsed) ? [...parsed] : [parsed];
      while (queue.length) {
        const obj = queue.shift();
        if (!obj || typeof obj !== 'object') continue;
        if (Array.isArray(obj['@graph'])) queue.push(...obj['@graph']);
        if (obj['@type'] !== 'Product') continue;
        if (!brand && obj.brand) brand = typeof obj.brand === 'object' ? obj.brand.name : obj.brand;
        if (!image && obj.image) image = Array.isArray(obj.image) ? obj.image[0] : obj.image;
      }
    }
  } catch (_) {}
  if (!brand) {
    const m = bodyText.match(/(?:Fournisseur|Marque)\s*:\s*([^\n|]{1,80})/i)
      || bodyText.match(/\bMarque\s+([A-Za-z0-9&+ ._-]{2,60})(?=\s+(?:Nous respectons|Description|Plus d'informations))/i);
    if (m) brand = clean(m[1]);
  }

  const breadcrumbs = [...document.querySelectorAll('.breadcrumbs a, .breadcrumbs li, nav[aria-label*="breadcrumb" i] a')]
    .map(el => clean(el.textContent)).filter(Boolean);
  const category = breadcrumbs.length >= 2 ? breadcrumbs.slice(1, -1).join(' > ') || null : null;

  const product = {
    merchant: "Mega Dental",
    merchant_reference: merchantReference || null,
    manufacturer_reference: manufacturerReference,
    ean: eanMatch ? eanMatch[1] : null,
    name: title,
    brand: brand || null,
    category,
    price_eur: price,
    availability: availabilityMatch ? availabilityMatch[1] : null,
    image_url: image || document.querySelector('meta[property="og:image"]')?.content || null,
    source_url: location.href,
    captured_at: new Date().toISOString()
  };

  const payload = {
    source: "mega_dental_browser_capture_v2",
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
  alert(`Mega Dental capturé : ${title}\nPrix: ${price ?? 'non trouvé'} €\nRéf: ${merchantReference || 'non trouvée'}\nMarque: ${brand || 'non trouvée'}`);
})();
