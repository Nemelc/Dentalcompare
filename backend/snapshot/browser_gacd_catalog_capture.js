// DentalCompare — capture publique GACD v5.1 depuis un navigateur normal.
// À exécuter sur https://www.gacd.fr/ dans DevTools > Console.
// Correction QuotaExceededError : les produits sont stockés dans IndexedDB,
// localStorage ne conserve qu'un état léger de progression.
// Aucun contournement de protection : arrêt immédiat sur 403/429/challenge.
(async () => {
  'use strict';

  const CFG = {
    delayMs: 1200,
    renderWaitMs: 12000,
    pauseEvery: 200,
    pauseMs: 45000,
    maxPagesPerCategory: 250,
    storageKey: 'dentalcompare_gacd_capture_v5_1',
    legacyStorageKey: 'dentalcompare_gacd_capture_v5',
    oldStorageKey: 'dentalcompare_gacd_capture_v4',
    dbName: 'dentalcompare_gacd_v5_1',
    dbVersion: 1,
    productStore: 'pages'
  };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = v => (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
  const abs = href => { try { return new URL(href, location.origin).href.split('#')[0]; } catch { return ''; } };
  const stamp = () => new Date().toISOString().replace(/[:.]/g, '-');
  const pathParts = u => { try { return new URL(u).pathname.split('/').filter(Boolean); } catch { return []; } };
  const money = s => {
    const m = clean(s).replace(/\u00a0/g, ' ').match(/([0-9][0-9\s]*[,.][0-9]{2})\s*€/);
    return m ? Number(m[1].replace(/\s/g, '').replace(',', '.')) : null;
  };
  const download = (name, obj) => {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    const objectUrl = URL.createObjectURL(blob);
    a.href = objectUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
  };

  function load(key) {
    try { return JSON.parse(localStorage.getItem(key)) || {}; }
    catch { return {}; }
  }

  function saveLight(state) {
    const light = {
      version: '5.1',
      productUrls: state.productUrls || [],
      nextIndex: Number.isInteger(state.nextIndex) ? state.nextIndex : 0,
      errors: (state.errors || []).slice(-250),
      startedAt: state.startedAt || new Date().toISOString(),
      migratedLegacy: !!state.migratedLegacy
    };
    localStorage.setItem(CFG.storageKey, JSON.stringify(light));
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(CFG.dbName, CFG.dbVersion);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(CFG.productStore)) {
          db.createObjectStore(CFG.productStore, { keyPath: 'url' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function idbPut(db, url, rows) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(CFG.productStore, 'readwrite');
      tx.objectStore(CFG.productStore).put({ url, rows, savedAt: new Date().toISOString() });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('IDB_ABORT'));
    });
  }

  function idbHas(db, url) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(CFG.productStore, 'readonly');
      const req = tx.objectStore(CFG.productStore).getKey(url);
      req.onsuccess = () => resolve(req.result !== undefined);
      req.onerror = () => reject(req.error);
    });
  }

  function idbAll(db) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(CFG.productStore, 'readonly');
      const req = tx.objectStore(CFG.productStore).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  function idbCount(db) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(CFG.productStore, 'readonly');
      const req = tx.objectStore(CFG.productStore).count();
      req.onsuccess = () => resolve(req.result || 0);
      req.onerror = () => reject(req.error);
    });
  }

  const db = await openDb();
  let state = Object.assign({
    version: '5.1',
    productUrls: [],
    nextIndex: 0,
    errors: [],
    startedAt: new Date().toISOString(),
    migratedLegacy: false
  }, load(CFG.storageKey));

  // Migration automatique du v5 qui a rempli localStorage.
  // On copie ses résultats déjà acquis dans IndexedDB puis on supprime la grosse clé v5.
  if (!state.migratedLegacy) {
    const legacy = load(CFG.legacyStorageKey);
    if (Array.isArray(legacy.productUrls) && legacy.productUrls.length) {
      if (!state.productUrls.length) state.productUrls = [...new Set(legacy.productUrls)];
      const productsObj = legacy.products && typeof legacy.products === 'object' ? legacy.products : {};
      const productEntries = Object.entries(productsObj);
      console.log(`[GACD v5.1] Migration de ${productEntries.length} fiches déjà capturées vers IndexedDB…`);
      for (let i = 0; i < productEntries.length; i++) {
        const [url, rows] = productEntries[i];
        await idbPut(db, url, Array.isArray(rows) ? rows : []);
        if ((i + 1) % 100 === 0) console.log(`[GACD v5.1] Migration ${i + 1}/${productEntries.length}`);
      }

      // Retrouve le dernier index réellement traité dans l'ancien run.
      const touched = new Set([
        ...Object.keys(productsObj),
        ...(Array.isArray(legacy.errors) ? legacy.errors.map(e => e && e.url).filter(Boolean) : [])
      ]);
      let lastTouched = -1;
      for (let i = 0; i < state.productUrls.length; i++) {
        if (touched.has(state.productUrls[i])) lastTouched = i;
      }
      if (lastTouched >= 0) state.nextIndex = Math.max(state.nextIndex || 0, lastTouched + 1);
      if (Array.isArray(legacy.errors)) state.errors = legacy.errors.slice(-250);

      state.migratedLegacy = true;
      saveLight(state);

      // Important : libère immédiatement les ~5 Mo de localStorage qui ont causé l'erreur.
      try { localStorage.removeItem(CFG.legacyStorageKey); } catch {}
      console.log(`[GACD v5.1] Migration terminée. Reprise prévue à ${state.nextIndex}/${state.productUrls.length}.`);
    } else {
      state.migratedLegacy = true;
      saveLight(state);
    }
  }

  // Si aucune URL v5 n'est disponible, réutilise la découverte v4.
  if (!state.productUrls.length) {
    const old = load(CFG.oldStorageKey);
    if (Array.isArray(old.productUrls) && old.productUrls.length) {
      state.productUrls = [...new Set(old.productUrls)];
      console.log('[GACD v5.1] ' + state.productUrls.length + ' URL produit récupérées depuis v4.');
      saveLight(state);
    }
  }

  async function getDoc(url) {
    const res = await fetch(url, { credentials: 'include', cache: 'no-store' });
    if ([403, 429].includes(res.status)) throw new Error('PROTECTION_HTTP_' + res.status);
    if (!res.ok) throw new Error('HTTP_' + res.status);
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const title = clean(doc.title || '');
    const txt = clean(doc.body?.innerText || '').slice(0, 3000);
    if (/just a moment|attention required|access denied|verify you are human|security check|checking your browser/i.test(title + ' ' + txt)) {
      throw new Error('PROTECTION_CHALLENGE');
    }
    return doc;
  }

  function categorySeeds(doc) {
    const bad = /\/customer|\/checkout|\/cart|\/search|\/catalogsearch|\/contact|\/mentions|\/conditions|\/privacy|\/brands?|\/promotions?|\/mon-stock|amenagement|textile|tech/i;
    return [...new Set([...doc.querySelectorAll('a[href]')]
      .map(a => abs(a.getAttribute('href')))
      .filter(u => u.startsWith(location.origin + '/') && /\.html(?:\?|$)/i.test(u) && !bad.test(u) && pathParts(u).length >= 2)
      .map(u => u.split('?')[0]))];
  }

  function createFrame() {
    document.getElementById('dc-gacd-capture-frame')?.remove();
    const f = document.createElement('iframe');
    f.id = 'dc-gacd-capture-frame';
    f.style.cssText = 'position:fixed;left:-10000px;top:0;width:1280px;height:1000px;border:0;opacity:0;pointer-events:none';
    document.body.appendChild(f);
    return f;
  }

  async function loadRendered(frame, url) {
    return new Promise((resolve, reject) => {
      let finished = false;
      const finish = (fn, v) => { if (finished) return; finished = true; clearTimeout(timer); fn(v); };
      const timer = setTimeout(() => finish(reject, new Error('RENDER_TIMEOUT')), CFG.renderWaitMs);
      frame.onload = async () => {
        try {
          const doc = frame.contentDocument;
          if (!doc) return finish(reject, new Error('NO_FRAME_DOCUMENT'));
          const txt = clean((doc.title || '') + ' ' + (doc.body?.innerText || '')).slice(0, 3000);
          if (/just a moment|attention required|access denied|verify you are human|security check|checking your browser/i.test(txt)) {
            return finish(reject, new Error('PROTECTION_CHALLENGE'));
          }
          const started = Date.now();
          while (Date.now() - started < CFG.renderWaitMs - 1000) {
            if (doc.querySelectorAll('a.result[href]').length) return finish(resolve, doc);
            await sleep(250);
          }
          finish(resolve, doc);
        } catch (e) { finish(reject, e); }
      };
      frame.src = url;
    });
  }

  function productLinks(doc) {
    return [...new Set([...doc.querySelectorAll('a.result[href]')]
      .map(a => abs(a.getAttribute('href')))
      .filter(u => u.startsWith(location.origin + '/') && /\.html(?:\?|$)/i.test(u))
      .map(u => u.split('?')[0]))];
  }

  function nextPage(doc, currentUrl) {
    const current = new URL(currentUrl);
    const links = [...doc.querySelectorAll('a[rel="next"][href],a.next[href],.pages-item-next a[href],.pagination a[href],.pages a[href]')]
      .map(a => abs(a.getAttribute('href'))).filter(Boolean);
    for (const u of links) {
      try {
        const x = new URL(u);
        if (x.origin === location.origin && x.pathname === current.pathname && x.href !== current.href && /(?:[?&](?:p|page)=\d+)/i.test(x.search)) return x.href;
      } catch {}
    }
    return '';
  }

  function meta(doc, p) {
    return clean(doc.querySelector(`meta[property="${p}"],meta[name="${p}"]`)?.content);
  }
  function stockFrom(t) {
    return (t.match(/\b(En stock|Sur commande|En réapprovisionnement(?:\s+Disponible sous \d+ jours)?|Arrêté)\b/i) || [])[1] || '';
  }
  function validRef(v) {
    v = clean(v);
    return /^[A-Z0-9][A-Z0-9._\/-]{1,}$/i.test(v) && !/^(nom|name|r|ref|reference)$/i.test(v) ? v : '';
  }

  function parseProduct(doc, url) {
    const body = doc.body?.innerText || '';
    const h1 = clean(doc.querySelector('h1')?.textContent) || meta(doc, 'og:title') || 'Produit GACD';
    let brand = clean(doc.querySelector('[itemprop="brand"],.product-brand,.brand,[class*="manufacturer"]')?.textContent);
    if (!brand) {
      const lines = body.split(/\r?\n/).map(clean).filter(Boolean);
      const hi = lines.findIndex(x => x === h1);
      if (hi >= 0 && lines[hi + 1] && !/^Réf|Voir la description/i.test(lines[hi + 1])) brand = lines[hi + 1];
    }
    const image = meta(doc, 'og:image') || abs(doc.querySelector('.gallery-placeholder img,.product.media img,img[itemprop="image"]')?.getAttribute('src'));
    const category = [...doc.querySelectorAll('.breadcrumbs a,.breadcrumbs strong')].map(x => clean(x.textContent)).filter(Boolean).slice(1).join(' > ');
    const capturedAt = new Date().toISOString();
    const out = [];

    const marker = /Réf\.\s*GACD\s*:\s*/ig;
    const matches = [...body.matchAll(marker)];
    for (let i = 0; i < matches.length; i++) {
      const start = matches[i].index + matches[i][0].length;
      const end = i + 1 < matches.length ? matches[i + 1].index : Math.min(body.length, start + 2500);
      const seg = body.slice(start, end);
      const lines = seg.split(/\r?\n/).map(clean).filter(Boolean);
      if (!lines.length) continue;
      const gacd = validRef(lines[0].split(/\s+/)[0]);
      if (!gacd) continue;
      const m = seg.match(/Réf\.\s*Fabricant\s*:\s*([^\s\r\n]+)/i);
      const mref = validRef(m?.[1] || '');
      const stock = stockFrom(seg);
      const price = money(seg);
      let name = '';
      for (const line of lines.slice(1)) {
        if (/^Réf\.\s*Fabricant/i.test(line)) break;
        if (/^(COULEUR|DIMENSION|TAILLE|TEINTE|FORME|GRAIN|N°|ISO|CONICITE|VISCOSITE|PRISE|LONGUEUR|DIAMETRE|DIAMÈTRE)\s*:/i.test(line)) continue;
        if (/^(En stock|Sur commande|En réapprovisionnement|Arrêté|Ajouter au panier|Choisir une quantité|Prix|Qté)$/i.test(line)) continue;
        if (/^[0-9\s,.]+\s*€/.test(line)) continue;
        name = line;
        break;
      }
      if (!name) name = h1;
      out.push({
        merchant: 'GACD',
        merchant_reference: gacd,
        manufacturer_reference: mref || null,
        ean: null,
        name,
        brand: brand || null,
        category: category || null,
        variant: name !== h1 ? name : null,
        packaging: null,
        price_eur: price,
        availability: stock || null,
        image_url: image || null,
        source_url: url,
        captured_at: capturedAt
      });
    }

    const seen = new Set();
    return out.filter(p => {
      if (seen.has(p.merchant_reference)) return false;
      seen.add(p.merchant_reference);
      return true;
    });
  }

  console.log('[GACD v5.1] Démarrage — stockage IndexedDB, reprise automatique.');

  // Découverte uniquement si aucune liste d'URL n'existe déjà.
  if (!state.productUrls.length) {
    const seeds = categorySeeds(document);
    const frame = createFrame();
    const known = new Set();
    console.log('[GACD v5.1] Découverte catégories:', seeds.length);
    for (let si = 0; si < seeds.length; si++) {
      let pageUrl = seeds[si], pageIndex = 0;
      const seen = new Set();
      while (pageUrl && pageIndex < CFG.maxPagesPerCategory && !seen.has(pageUrl)) {
        seen.add(pageUrl);
        pageIndex++;
        try {
          const doc = await loadRendered(frame, pageUrl);
          const links = productLinks(doc);
          let added = 0;
          links.forEach(u => {
            if (!known.has(u)) {
              known.add(u);
              state.productUrls.push(u);
              added++;
            }
          });
          const next = nextPage(doc, pageUrl);
          saveLight(state);
          console.log(`[GACD v5.1] catégorie ${si + 1}/${seeds.length} page ${pageIndex}: ${links.length}, +${added}, total ${known.size}`);
          pageUrl = next;
          await sleep(CFG.delayMs);
        } catch (e) {
          state.errors.push({ url: pageUrl, error: e.message, at: new Date().toISOString() });
          saveLight(state);
          if (/^PROTECTION_/.test(e.message)) {
            frame.remove();
            throw e;
          }
          break;
        }
      }
    }
    frame.remove();
  }

  const already = await idbCount(db);
  console.log(`[GACD v5.1] Enrichissement de ${state.productUrls.length} fiches. ${already} déjà stockée(s). Reprise index ${state.nextIndex}.`);

  let session = 0;
  for (let i = state.nextIndex; i < state.productUrls.length; i++) {
    const url = state.productUrls[i];

    // Protection supplémentaire contre un éventuel redémarrage à un index trop bas.
    if (await idbHas(db, url)) {
      state.nextIndex = i + 1;
      if ((i + 1) % 25 === 0) saveLight(state);
      continue;
    }

    try {
      const doc = await getDoc(url);
      const rows = parseProduct(doc, url);
      await idbPut(db, url, rows);
      state.nextIndex = i + 1;
      session++;
      saveLight(state);
      console.log(`[GACD v5.1] ${i + 1}/${state.productUrls.length} — ${rows.length} variante(s) — ${url}`);

      if (session % CFG.pauseEvery === 0) {
        console.log('[GACD v5.1] Pause 45 s…');
        await sleep(CFG.pauseMs);
      }
      await sleep(CFG.delayMs);
    } catch (e) {
      state.errors.push({ url, error: e.message, at: new Date().toISOString() });
      state.nextIndex = i + 1;
      saveLight(state);
      console.warn('[GACD v5.1]', url, e.message);
      if (/^PROTECTION_/.test(e.message)) throw e;
    }
  }

  const pages = await idbAll(db);
  const products = pages.flatMap(x => Array.isArray(x.rows) ? x.rows : []);
  const output = {
    source: 'gacd_browser_public_capture_v5_1',
    captured_at: new Date().toISOString(),
    product_pages: state.productUrls.length,
    product_pages_stored: pages.length,
    total_products: products.length,
    errors: state.errors,
    products
  };
  download('gacd_catalog_v5_1_' + stamp() + '.json', output);
  console.log('[GACD v5.1] TERMINÉ:', products.length, 'références. Fichier téléchargé.');
})();