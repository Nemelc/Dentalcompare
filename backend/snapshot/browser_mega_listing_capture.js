(() => {
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const money = (text) => {
    const t = clean(text).replace(/\u00a0/g, ' ');
    const m = t.match(/(?:À partir de\s*)?([0-9][0-9\s.]*(?:,[0-9]{1,2})?)\s*€/i);
    if (!m) return null;
    const n = m[1].replace(/[\s.]/g, '').replace(',', '.');
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

  const cardSelectors = [
    '.product-item',
    '.item.product',
    'li.product-item',
    '[data-container="product-grid"] .product-item',
    '.products-grid .product-item',
    '.product-list-item'
  ];
  let cards = [];
  for (const s of cardSelectors) cards.push(...document.querySelectorAll(s));
  cards = [...new Set(cards)];

  const products = [];
  for (const card of cards) {
    const text = clean(card.innerText || card.textContent || '');
    if (!text) continue;

    const linkEl = card.querySelector('a.product-item-link, a.product-item-photo, a[href$=".html"], a[href*="megadental.fr/"]');
    const url = linkEl ? abs(linkEl.getAttribute('href')) : null;
    if (!url || !/megadental\.fr\//i.test(url)) continue;

    const nameEl = card.querySelector('.product-item-name, .product.name, .product-item-link, [itemprop="name"]');
    let name = clean(nameEl?.textContent || linkEl?.textContent || '');

    const ref = refFromText(text);
    if (ref && name) name = clean(name.replace(new RegExp('^Réf\\.?\\s*' + ref.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), ''));

    const brandEl = card.querySelector('.brand, .product-brand, [itemprop="brand"], [class*="brand"]');
    let brand = clean(brandEl?.textContent || '');

    const priceEl = card.querySelector('.price, [data-price-type="finalPrice"] .price, .special-price .price, [itemprop="price"]');
    const price = money(priceEl?.textContent || text);

    const imgEl = card.querySelector('img.product-image-photo, img[itemprop="image"], img');
    const image = imgEl ? abs(imgEl.currentSrc || imgEl.src || imgEl.getAttribute('data-src')) : null;

    products.push({
      merchant: 'Mega Dental',
      source_url: url,
      name: name || null,
      merchant_reference: ref,
      brand: brand || null,
      price_eur: price,
      image_url: image,
      listing_page: location.href,
      captured_at: new Date().toISOString(),
      catalog_source: 'browser_listing_capture'
    });
  }

  const payload = {
    source: 'mega_dental_browser_listing_capture_v1',
    page_url: location.href,
    page_title: document.title,
    captured_at: new Date().toISOString(),
    total_products: products.length,
    products
  };

  console.log('Mega Dental - produits détectés:', products.length);
  console.table(products.slice(0, 20));

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mega_listing_' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
})();
