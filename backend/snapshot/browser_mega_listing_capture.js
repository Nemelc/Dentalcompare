(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const escRe = (v) => String(v || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const money = (text) => {
    const t = clean(text).replace(/\u00a0/g, ' ');
    const matches = [...t.matchAll(/(?:À partir de\s*)?([0-9][0-9\s.]*(?:,[0-9]{1,2})?)\s*€/gi)];
    if (!matches.length) return null;
    const preferred = matches.find(m => /À partir de\s*$/i.test(t.slice(Math.max(0, m.index - 20), m.index))) || matches[0];
    const n = preferred[1].replace(/[\s.]/g, '').replace(',', '.');
    const v = Number(n);
    return Number.isFinite(v) ? v : null;
  };
  const refFromText = (text) => {
    const m = clean(text).match(/Réf\.?\s*([A-Z0-9.-]+(?:-[A-Z0-9.-]+)?)/i);
    return m ? m[1] : null;
  };
  const abs = (u) => {
    try { return new URL(u, location.href).href; } catch { return null; }
  };
  const pageBrand = (() => {
    const title = clean(document.title);
    let m = title.match(/Produits de la marque\s*:\s*(.+?)(?:\s*\||$)/i);
    if (m) return clean(m[1]);
    const h1 = clean(document.querySelector('h1')?.textContent || '');
    m = h1.match(/(?:marque\s*:?\s*)?(.+)/i);
    return clean(m?.[1] || '');
  })();
  const cleanName = (raw, brand, ref) => {
    let name = clean(raw);
    if (ref) name = clean(name.replace(new RegExp('^Réf\\.?\\s*' + escRe(ref) + '\\s*', 'i'), ''));
    name = name.replace(/(?:À partir de\s*)?[0-9][0-9\s.]*(?:,[0-9]{1,2})?\s*€(?:\s*au lieu de\s*[0-9][0-9\s.]*(?:,[0-9]{1,2})?\s*€)?(?:\s*-?\d+%)?.*$/i, '').trim();
    if (brand) name = name.replace(new RegExp('\\s+' + escRe(brand) + '\\s*$', 'i'), '').trim();
    return clean(name);
  };
  const bestImage = (img) => {
    if (!img) return null;
    const candidates = [
      img.getAttribute('data-src'),
      img.getAttribute('data-lazy-load'),
      img.getAttribute('data-original'),
      img.getAttribute('data-srcset')?.split(',')[0]?.trim()?.split(' ')[0],
      img.getAttribute('srcset')?.split(',')[0]?.trim()?.split(' ')[0],
      img.currentSrc,
      img.getAttribute('src')
    ].filter(Boolean);
    for (const c of candidates) {
      const u = abs(c);
      if (!u || u.startsWith('data:') || /placeholder|produitsansphoto/i.test(u)) continue;
      return u;
    }
    return null;
  };

  const cardSelectors = [
    '.product-item', '.item.product', 'li.product-item',
    '[data-container="product-grid"] .product-item',
    '.products-grid .product-item', '.product-list-item'
  ];
  let cards = [];
  for (const s of cardSelectors) cards.push(...document.querySelectorAll(s));
  cards = [...new Set(cards)];

  const products = [];
  const seen = new Set();
  for (const card of cards) {
    const text = clean(card.innerText || card.textContent || '');
    if (!text) continue;
    const linkEl = card.querySelector('a.product-item-link, a.product-item-photo, a[href$=".html"], a[href*="megadental.fr/"]');
    const url = linkEl ? abs(linkEl.getAttribute('href')) : null;
    if (!url || !/megadental\.fr\//i.test(url) || seen.has(url)) continue;
    seen.add(url);

    const ref = refFromText(text);
    const brandEl = card.querySelector('.brand, .product-brand, [itemprop="brand"], [class*="brand"]');
    const brand = clean(brandEl?.textContent || pageBrand || '');
    const nameEl = card.querySelector('.product-item-name, .product.name, .product-item-link, [itemprop="name"]');
    const rawName = clean(nameEl?.textContent || linkEl?.textContent || '');
    const name = cleanName(rawName || text, brand, ref);
    const priceEl = card.querySelector('.special-price .price, [data-price-type="finalPrice"] .price, .price-final_price .price, .price, [itemprop="price"]');
    const price = money(priceEl?.textContent || text);
    const imgEl = card.querySelector('img.product-image-photo, img[itemprop="image"], img');

    products.push({
      merchant: 'Mega Dental', source_url: url, name: name || null,
      merchant_reference: ref, manufacturer_reference: null, ean: null,
      brand: brand || null, category: null, variant: null, packaging: null,
      price_eur: price, availability: null, image_url: bestImage(imgEl),
      listing_page: location.href, captured_at: new Date().toISOString(),
      catalog_source: 'browser_listing_capture_v2'
    });
  }

  const payload = {
    source: 'mega_dental_browser_listing_capture_v2', page_url: location.href,
    page_title: document.title, brand: pageBrand || null,
    captured_at: new Date().toISOString(), total_products: products.length, products
  };
  console.log('Mega Dental - marque:', pageBrand || '(inconnue)');
  console.log('Mega Dental - produits détectés:', products.length);
  console.table(products.slice(0, 20));
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mega_listing_' + (pageBrand || 'page').replace(/[^a-z0-9]+/gi, '_') + '_' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
})();
