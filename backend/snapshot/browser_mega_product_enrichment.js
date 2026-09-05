(async () => {
  const DELAY_MS = 1500;
  const BATCH_SIZE = 250;
  const BATCH_PAUSE_MS = 60000;
  const DB_NAME = 'dentalcompare_mega_enrichment';
  const STORE_NAME = 'products';
  const META_STORE = 'meta';
  const parser = new DOMParser();
  const clean = s => (s || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  const validPlainValue = value => {
    const v = clean(value);
    if (!v || v.length > 120) return null;
    if (/[{}\[\];]/.test(v)) return null;
    if (/\b(function|type_id|writeRecentlyViewed|require\(|dataLayer)\b/i.test(v)) return null;
    return v;
  };

  const validReference = value => {
    const v = validPlainValue(value);
    if (!v) return null;
    if (/^(?:\.|-|--|S\/?O|N\/?A|N\.A\.|NC|N\/C|Non renseign[eé]|Aucun|DIVERS)$/i.test(v)) return null;
    if (v.length > 60) return null;
    return v;
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
      const matched = normalizedLabels.find(label => low.startsWith(label));
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
    const result = { sku: null, mpn: null, gtin: null, brand: null, image: null };
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
          if (!result.gtin) result.gtin = validReference(obj.gtin13 || obj.gtin14 || obj.gtin12 || obj.gtin8 || obj.gtin);
          if (!result.brand && obj.brand) {
            const raw = typeof obj.brand === 'object' ? obj.brand.name : obj.brand;
            result.brand = validPlainValue(raw);
          }
          if (!result.image && obj.image) {
            const raw = Array.isArray(obj.image) ? obj.image[0] : obj.image;
            if (typeof raw === 'string' && /^https?:\/\//i.test(raw)) result.image = raw;
          }
        }
      } catch (_) {}
    }
    return result;
  };

  const isRealChallenge = (html, status) => {
    if (status === 403 || status === 429) return true;
    const doc = parser.parseFromString(html, 'text/html');
    const title = clean(doc.title || '').toLowerCase();
    const body = clean(doc.body?.innerText || doc.body?.textContent || '').toLowerCase();
    return title === 'just a moment...' || title === 'just a moment' ||
      title.includes('checking your browser') || title.includes('attention required') ||
      body.startsWith('checking your browser') || body.startsWith('verify you are human') ||
      body.includes('performing security verification') ||
      body.includes('enable javascript and cookies to continue');
  };

  const extract = (html, url) => {
    const doc = parser.parseFromString(html, 'text/html');
    const ld = readJsonLdProduct(doc);
    const bodyText = clean(doc.body?.innerText || doc.body?.textContent || '');

    let manufacturerReference = validReference(ld.mpn);
    if (!manufacturerReference) {
      manufacturerReference = validReference(valueNearLabel(doc, [
        'MPN', 'Référence fabricant', 'Réf. fabricant', 'Réf fabricant', 'Code fabricant'
      ]));
    }

    let ean = null;
    const ldDigits = String(ld.gtin || '').replace(/\D/g, '');
    if (/^\d{8,14}$/.test(ldDigits)) ean = ldDigits;
    if (!ean) {
      const explicit = valueNearLabel(doc, ['EAN', 'GTIN', 'EAN13', 'GTIN13']);
      const digits = String(explicit || '').replace(/\D/g, '');
      if (/^\d{8,14}$/.test(digits)) ean = digits;
    }

    let merchantReference = validReference(ld.sku);
    if (!merchantReference) {
      merchantReference = validReference(valueNearLabel(doc, [
        'Référence Mega Dental', 'Réf. Mega Dental', 'Réf Mega Dental', 'SKU'
      ]));
    }

    let brand = validPlainValue(ld.brand);
    if (!brand) brand = validPlainValue(valueNearLabel(doc, ['Fournisseur', 'Marque', 'Fabricant']));

    let image = ld.image;
    if (!image) image = doc.querySelector('meta[property="og:image"]')?.content || null;
    if (image && (!/^https?:\/\//i.test(image) || /produitsansphoto|placeholder/i.test(image))) image = null;

    const availabilityMatch = bodyText.match(/\b(En stock|Disponible|Sur commande|En réapprovisionnement|Rupture de stock|Indisponible)\b/i);

    const crumbs = [...doc.querySelectorAll('.breadcrumbs a, .breadcrumbs li, nav[aria-label*="breadcrumb" i] a')]
      .map(el => clean(el.textContent)).filter(Boolean);
    const dedup = [];
    for (const c of crumbs) if (!dedup.includes(c)) dedup.push(c);
    const category = dedup.length >= 3 ? dedup.slice(1, -1).join(' > ') : null;

    return {
      source_url: url,
      merchant_reference: merchantReference || null,
      manufacturer_reference: manufacturerReference || null,
      ean,
      brand: brand || null,
      category,
      availability: availabilityMatch ? availabilityMatch[1] : null,
      image_url: image || null,
      captured_at: new Date().toISOString(),
      catalog_source: 'browser_product_enrichment_v2'
    };
  };

  const pickJson = () => new Promise((resolve, reject) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.onchange = async () => {
      try {
        const file = input.files?.[0];
        if (!file) return reject(new Error('Aucun fichier sélectionné'));
        resolve({ file, data: JSON.parse(await file.text()) });
      } catch (e) { reject(e); }
      finally { input.remove(); }
    };
    input.click();
  });

  const openDb = () => new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'source_url' });
      if (!db.objectStoreNames.contains(META_STORE)) db.createObjectStore(META_STORE, { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  const dbPut = (db, store, value) => new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).put(value);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });

  const dbGetAll = (db, store) => new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readonly');
    const req = tx.objectStore(store).getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror = () => reject(req.error);
  });

  const downloadPayload = (payload, prefix = 'mega_product_enrichment_full') => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${prefix}_${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  };

  console.clear();
  console.log('DentalCompare — enrichissement Mega Dental autonome v2');
  console.log('Choisis data/mega_catalog_product_enriched.json. Ensuite tu peux laisser l’ordinateur travailler seul.');

  const { file, data } = await pickJson();
  const products = Array.isArray(data) ? data : (Array.isArray(data.products) ? data.products : []);
  if (!products.length) throw new Error('Aucun produit trouvé dans le JSON sélectionné.');

  const candidates = products.filter(p =>
    p?.source_url && /^https:\/\/www\.megadental\.fr\//i.test(p.source_url) &&
    (!validReference(p.manufacturer_reference) || !p.ean || !p.image_url || !p.availability || !p.category)
  );

  const db = await openDb();
  const already = await dbGetAll(db, STORE_NAME);
  const doneUrls = new Set(already.map(x => x.source_url));
  const pending = candidates.filter(p => !doneUrls.has(p.source_url));

  console.log(`Catalogue: ${products.length} produits (${file.name})`);
  console.log(`À enrichir selon le catalogue: ${candidates.length}`);
  console.log(`Déjà sauvegardés automatiquement dans le navigateur: ${doneUrls.size}`);
  console.log(`Restants pour cette session: ${pending.length}`);
  console.log(`Rythme: ${DELAY_MS / 1000}s entre fiches, pause ${BATCH_PAUSE_MS / 1000}s toutes les ${BATCH_SIZE} fiches.`);

  const errors = [];
  let stopped = false;
  let sessionCompleted = 0;

  for (let i = 0; i < pending.length; i++) {
    const p = pending[i];
    console.log(`[${i + 1}/${pending.length}] ${p.source_url}`);
    try {
      const res = await fetch(p.source_url, { credentials: 'include', cache: 'no-store' });
      const html = await res.text();

      if (isRealChallenge(html, res.status)) {
        console.warn(`Protection détectée (${res.status}). Arrêt immédiat, sans contournement. La progression est déjà sauvegardée.`);
        errors.push({ source_url: p.source_url, status: res.status, error: 'protection_detected' });
        stopped = true;
        break;
      }

      if (!res.ok) {
        errors.push({ source_url: p.source_url, status: res.status, error: 'http_error' });
      } else {
        const extra = extract(html, p.source_url);
        await dbPut(db, STORE_NAME, extra);
        sessionCompleted++;
        console.log(`✓ réf fab: ${extra.manufacturer_reference || '?'} | EAN: ${extra.ean || '?'} | image: ${extra.image_url ? 'oui' : 'non'} | stock: ${extra.availability || '?'}`);
      }
    } catch (e) {
      console.error(e);
      errors.push({ source_url: p.source_url, error: String(e?.message || e) });
    }

    await dbPut(db, META_STORE, {
      key: 'last_run',
      updated_at: new Date().toISOString(),
      input_file: file.name,
      input_products: products.length,
      candidates: candidates.length,
      session_completed: sessionCompleted,
      errors: errors.length
    });

    if (i < pending.length - 1) {
      if ((i + 1) % BATCH_SIZE === 0) {
        console.log(`Pause de ${BATCH_PAUSE_MS / 1000}s après ${i + 1} fiches. Progression sauvegardée automatiquement.`);
        await sleep(BATCH_PAUSE_MS);
      } else {
        await sleep(DELAY_MS);
      }
    }
  }

  const allSaved = await dbGetAll(db, STORE_NAME);
  const payload = {
    source: 'mega_dental_browser_product_enrichment_v2',
    input_file: file.name,
    input_products: products.length,
    candidates: candidates.length,
    previously_saved: already.length,
    session_completed: sessionCompleted,
    total_saved: allSaved.length,
    stopped_on_protection: stopped,
    errors,
    captured_at: new Date().toISOString(),
    products: allSaved
  };

  downloadPayload(payload, stopped ? 'mega_product_enrichment_checkpoint' : 'mega_product_enrichment_full');
  console.log('Terminé.', payload);
  alert(`Enrichissement Mega terminé\n\nNouveaux traités : ${sessionCompleted}\nTotal sauvegardé : ${allSaved.length}\nErreurs : ${errors.length}\nProtection : ${stopped ? 'oui' : 'non'}\n\nUn fichier JSON final/checkpoint a été téléchargé.`);
})();
