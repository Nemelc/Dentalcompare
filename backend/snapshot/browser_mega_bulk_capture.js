(async () => {
  const LIMIT = 20;
  const DELAY_MS = 1800;
  const SITEMAPS = [
    'https://www.megadental.fr/media/sitemap/sitemap_14-1-1.xml',
    'https://www.megadental.fr/media/sitemap/sitemap_14-1-2.xml'
  ];

  const clean = s => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const parser = new DOMParser();

  const isRealChallenge = (html, status) => {
    if (status === 403 || status === 429) return true;

    const doc = parser.parseFromString(html, 'text/html');
    const title = clean(doc.title || '').toLowerCase();
    const body = clean(doc.body?.innerText || doc.body?.textContent || '').toLowerCase();

    const titleLooksLikeChallenge =
      title === 'just a moment...' ||
      title === 'just a moment' ||
      title.includes('checking your browser') ||
      title.includes('attention required');

    const bodyLooksLikeChallenge =
      body.startsWith('checking your browser') ||
      body.startsWith('verify you are human') ||
      body.includes('performing security verification') ||
      body.includes('enable javascript and cookies to continue');

    const productPageLooksNormal = Boolean(
      doc.querySelector('h1') &&
      (doc.querySelector('.product-info-main') ||
       doc.querySelector('[data-price-type="finalPrice"]') ||
       doc.querySelector('.price-box') ||
       doc.querySelector('[itemprop="price"]'))
    );

    return !productPageLooksNormal && (titleLooksLikeChallenge || bodyLooksLikeChallenge);
  };

  const parsePrice = s => {
    if (!s) return null;
    const m = clean(s).match(/(\d{1,5}(?:[ .\u202f]\d{3})*[,.]\d{2})\s*€/);
    if (!m) return null;
    const normalized = m[1].replace(/[ .\u202f]/g, '').replace(',', '.');
    const n = Number(normalized);
    return Number.isFinite(n) ? n : null;
  };

  const validPlainValue = value => {
    const v = clean(value);
    if (!v || v.length > 100) return null;
    if (/[{}\[\];]/.test(v)) return null;
    if (/\b(function|type_id|writeRecentlyViewed|require\(|dataLayer)\b/i.test(v)) return null;
    return v;
  };

  const validReference = value => {
    const v = validPlainValue(value);
    if (!v) return null;
    if (/^(?:S\/?O|N\/?A|N\.A\.|NC|N\/C|Non renseigné|Aucun|DIVERS)$/i.test(v)) return null;
    if (v.length > 60) return null;
    return v;
  };

  const qText = (doc, selectors) => {
    for (const sel of selectors) {
      const el = doc.querySelector(sel);
      const value = validPlainValue(el?.textContent || el?.getAttribute?.('content') || '');
      if (value) return value;
    }
    return null;
  };

  const valueNearLabel = (doc, labels) => {
    const normalizedLabels = labels.map(x => x.toLowerCase());
    const blocks = doc.querySelectorAll(
      'tr, .product.attribute, .additional-attributes-wrapper tr, dl > div, .product-info-main li, .product-info-main p'
    );

    for (const block of blocks) {
      const text = clean(block.textContent || '');
      if (!text) continue;
      const low = text.toLowerCase();
      const matched = normalizedLabels.find(label => low.startsWith(label.toLowerCase()));
      if (!matched) continue;

      const explicitValue = block.querySelector('.value, td:last-child, dd, [data-th]');
      const fromElement = validPlainValue(explicitValue?.textContent || '');
      if (fromElement && fromElement.toLowerCase() !== matched) return fromElement;

      const escaped = matched.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const m = text.match(new RegExp('^\\s*' + escaped + '\\s*:?\\s*(.+)$', 'i'));
      const fallback = validPlainValue(m?.[1] || '');
      if (fallback) return fallback;
    }

    return null;
  };

  const readJsonLdProduct = doc => {
    const result = {
      sku: null,
      mpn: null,
      gtin: null,
      brand: null,
      image: null
    };

    for (const node of doc.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(node.textContent);
        const queue = Array.isArray(parsed) ? [...parsed] : [parsed];

        while (queue.length) {
          const obj = queue.shift();
          if (!obj || typeof obj !== 'object') continue;
          if (Array.isArray(obj['@graph'])) queue.push(...obj['@graph']);

          const types = Array.isArray(obj['@type']) ? obj['@type'] : [obj['@type']];
          if (!types.includes('Product')) continue;

          if (!result.sku) result.sku = validReference(obj.sku);
          if (!result.mpn) result.mpn = validReference(obj.mpn);
          if (!result.gtin) {
            result.gtin = validReference(obj.gtin13 || obj.gtin14 || obj.gtin12 || obj.gtin8 || obj.gtin);
          }
          if (!result.brand && obj.brand) {
            const rawBrand = typeof obj.brand === 'object' ? obj.brand.name : obj.brand;
            result.brand = validPlainValue(rawBrand);
          }
          if (!result.image && obj.image) {
            const rawImage = Array.isArray(obj.image) ? obj.image[0] : obj.image;
            if (typeof rawImage === 'string' && /^https?:\/\//i.test(rawImage)) result.image = rawImage;
          }
        }
      } catch (_) {}
    }

    return result;
  };

  const extractProduct = (html, url) => {
    const doc = parser.parseFromString(html, 'text/html');
    const bodyText = clean(doc.body?.innerText || doc.body?.textContent || '');
    const title = clean(doc.querySelector('h1')?.textContent || doc.title || '');
    const ld = readJsonLdProduct(doc);

    let price = null;
    for (const sel of [
      '[itemprop="price"]',
      '[data-price-type="finalPrice"] .price',
      '.special-price .price',
      '.price-box .price-final_price .price',
      '.price-box .price'
    ]) {
      const el = doc.querySelector(sel);
      if (!el) continue;
      const attr = el.getAttribute('content') || el.getAttribute('data-price-amount');
      if (attr && /^\d+(?:\.\d+)?$/.test(attr)) {
        const n = Number(attr);
        if (Number.isFinite(n)) {
          price = n;
          break;
        }
      }
      const n = parsePrice(el.textContent);
      if (n != null) {
        price = n;
        break;
      }
    }

    if (price == null) {
      const m = bodyText.match(/MPN\s*:\s*[^€]{0,120}?(\d{1,5}(?:[ .\u202f]\d{3})*[,.]\d{2})\s*€/i);
      price = m ? parsePrice(m[0]) : null;
    }

    let merchantReference = validReference(qText(doc, [
      '[itemprop="sku"]',
      '.product.attribute.sku .value',
      '.product-info-main .sku .value',
      '.product-info-stock-sku .sku .value'
    ]));

    if (!merchantReference) {
      const el = doc.querySelector('[data-product-sku]');
      merchantReference = validReference(el?.getAttribute('data-product-sku') || '');
    }

    if (!merchantReference) merchantReference = validReference(ld.sku);
    if (!merchantReference) {
      merchantReference = validReference(valueNearLabel(doc, [
        'Référence Mega Dental', 'Réf. Mega Dental', 'Réf Mega Dental', 'SKU'
      ]));
    }

    let manufacturerReference = validReference(ld.mpn);
    if (!manufacturerReference) {
      manufacturerReference = validReference(valueNearLabel(doc, [
        'MPN', 'Référence fabricant', 'Réf. fabricant', 'Réf fabricant', 'Code fabricant'
      ]));
    }

    let ean = null;
    const ldGtin = String(ld.gtin || '').replace(/\D/g, '');
    if (/^\d{8,14}$/.test(ldGtin)) ean = ldGtin;
    if (!ean) {
      const explicitEan = valueNearLabel(doc, ['EAN', 'GTIN', 'EAN13', 'GTIN13']);
      const digits = String(explicitEan || '').replace(/\D/g, '');
      if (/^\d{8,14}$/.test(digits)) ean = digits;
    }

    const availabilityMatch = bodyText.match(/\b(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture de stock|Indisponible)\b/i);

    let brand = validPlainValue(ld.brand);
    if (!brand) {
      brand = validPlainValue(valueNearLabel(doc, ['Fournisseur', 'Marque', 'Fabricant']));
    }

    let image = ld.image;
    if (!image) {
      image = doc.querySelector('meta[property="og:image"]')?.content || null;
    }

    const crumbsRaw = [...doc.querySelectorAll('.breadcrumbs a, .breadcrumbs li, nav[aria-label*="breadcrumb" i] a')]
      .map(el => clean(el.textContent))
      .filter(Boolean);

    const crumbs = [];
    for (const crumb of crumbsRaw) {
      if (!crumbs.includes(crumb)) crumbs.push(crumb);
    }

    const category = crumbs.length >= 3 ? crumbs.slice(1, -1).join(' > ') : null;

    return {
      merchant: 'Mega Dental',
      merchant_reference: merchantReference || null,
      manufacturer_reference: manufacturerReference || null,
      ean,
      name: title,
      brand: brand || null,
      category,
      price_eur: price,
      availability: availabilityMatch ? availabilityMatch[1] : null,
      image_url: image,
      source_url: url,
      captured_at: new Date().toISOString()
    };
  };

  console.clear();
  console.log('DentalCompare — test automatique Mega Dental v3');
  console.log('Chargement des sitemaps…');

  const allUrls = [];

  for (const sitemapUrl of SITEMAPS) {
    const res = await fetch(sitemapUrl, {
      credentials: 'include',
      cache: 'no-store'
    });

    if (!res.ok) {
      throw new Error(`Sitemap inaccessible: ${res.status} ${sitemapUrl}`);
    }

    const xml = parser.parseFromString(await res.text(), 'application/xml');

    for (const node of xml.querySelectorAll('url')) {
      const loc = clean(node.querySelector('loc')?.textContent || '');
      const priority = clean(node.querySelector('priority')?.textContent || '');

      if (!loc || priority !== '1.0') continue;
      if (!/^https:\/\/www\.megadental\.fr\/[^?#]+\.html$/i.test(loc)) continue;

      allUrls.push(loc);
    }
  }

  const urls = [...new Set(allUrls)].slice(0, LIMIT);
  console.log(`${allUrls.length} URL produit détectées. Test sur ${urls.length}.`);

  const products = [];
  const errors = [];
  let stopped = false;

  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    console.log(`[${i + 1}/${urls.length}] ${url}`);

    try {
      const res = await fetch(url, {
        credentials: 'include',
        cache: 'no-store'
      });

      const html = await res.text();

      if (isRealChallenge(html, res.status)) {
        console.warn(`Protection réelle détectée (${res.status}). Arrêt sans contournement.`);
        errors.push({ url, status: res.status, error: 'protection_detected' });
        stopped = true;
        break;
      }

      if (!res.ok) {
        console.warn(`HTTP ${res.status}`);
        errors.push({ url, status: res.status, error: 'http_error' });
      } else {
        const product = extractProduct(html, url);

        if (!product.name || product.price_eur == null) {
          console.warn('Fiche incomplète', product);
          errors.push({
            url,
            status: res.status,
            error: 'incomplete_product',
            product
          });
        } else {
          products.push(product);
          console.log(
            `✓ ${product.name} — ${product.price_eur} € — ${product.brand || 'marque ?'} — ` +
            `réf Mega: ${product.merchant_reference || '?'} — réf fab: ${product.manufacturer_reference || '?'}`
          );
        }
      }
    } catch (e) {
      console.error(e);
      errors.push({
        url,
        error: String(e?.message || e)
      });
    }

    if (i < urls.length - 1) {
      await sleep(DELAY_MS);
    }
  }

  const payload = {
    source: 'mega_dental_bulk_browser_test_v3',
    requested_limit: LIMIT,
    discovered_product_urls: allUrls.length,
    completed: products.length,
    stopped_on_protection: stopped,
    errors,
    captured_at: new Date().toISOString(),
    products
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: 'application/json'
  });

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `mega_bulk_test_${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
  a.click();

  setTimeout(() => URL.revokeObjectURL(a.href), 2000);

  console.log('Terminé.', payload);

  alert(`Test Mega Dental terminé\n\nProduits OK : ${products.length}/${urls.length}\nErreurs : ${errors.length}\nProtection : ${stopped ? 'oui' : 'non'}\n\nLe fichier JSON a été téléchargé.`);
})();
