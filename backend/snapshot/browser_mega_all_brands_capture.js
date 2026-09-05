(async () => {
  const ORIGIN = 'https://www.megadental.fr';
  const INDEX = ORIGIN + '/brands/toutes-les-marques';
  const DELAY_MS = 900;
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const clean = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const escRe = (v) => String(v || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const abs = (u, base = location.href) => { try { return new URL(u, base).href; } catch { return null; } };
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
  const pageBrand = (doc) => {
    const title = clean(doc.title);
    let m = title.match(/Produits de la marque\s*:\s*(.+?)(?:\s*\||$)/i);
    if (m) return clean(m[1]);
    const h1 = clean(doc.querySelector('h1')?.textContent || '');
    return clean(h1.replace(/^Produits de la marque\s*:?\s*/i, ''));
  };
  const cleanName = (raw, brand, ref) => {
    let name = clean(raw);
    if (ref) name = clean(name.replace(new RegExp('^Réf\\.?\\s*' + escRe(ref) + '\\s*', 'i'), ''));
    name = name.replace(/(?:À partir de\s*)?[0-9][0-9\s.]*(?:,[0-9]{1,2})?\s*€(?:\s*au lieu de\s*[0-9][0-9\s.]*(?:,[0-9]{1,2})?\s*€)?(?:\s*-?\d+%)?.*$/i, '').trim();
    if (brand) name = name.replace(new RegExp('\\s+' + escRe(brand) + '\\s*$', 'i'), '').trim();
    return clean(name);
  };
  const bestImage = (img, base) => {
    if (!img) return null;
    const candidates = [img.getAttribute('data-src'), img.getAttribute('data-lazy-load'), img.getAttribute('data-original'), img.getAttribute('data-srcset')?.split(',')[0]?.trim()?.split(' ')[0], img.getAttribute('srcset')?.split(',')[0]?.trim()?.split(' ')[0], img.getAttribute('src')].filter(Boolean);
    for (const c of candidates) {
      const u = abs(c, base);
      if (!u || u.startsWith('data:') || /placeholder|produitsansphoto/i.test(u)) continue;
      return u;
    }
    return null;
  };
  const extractProducts = (doc, pageUrl) => {
    const brand = pageBrand(doc);
    const selectors = ['.product-item', '.item.product', 'li.product-item', '[data-container="product-grid"] .product-item', '.products-grid .product-item', '.product-list-item'];
    let cards = [];
    for (const s of selectors) cards.push(...doc.querySelectorAll(s));
    cards = [...new Set(cards)];
    const seen = new Set();
    const out = [];
    for (const card of cards) {
      const text = clean(card.textContent || '');
      if (!text) continue;
      const linkEl = card.querySelector('a.product-item-link, a.product-item-photo, a[href$=".html"], a[href*="megadental.fr/"]');
      const url = linkEl ? abs(linkEl.getAttribute('href'), pageUrl) : null;
      if (!url || !/megadental\.fr\//i.test(url) || seen.has(url)) continue;
      seen.add(url);
      const ref = refFromText(text);
      const brandEl = card.querySelector('.brand, .product-brand, [itemprop="brand"], [class*="brand"]');
      const cardBrand = clean(brandEl?.textContent || brand || '');
      const nameEl = card.querySelector('.product-item-name, .product.name, .product-item-link, [itemprop="name"]');
      const name = cleanName(clean(nameEl?.textContent || linkEl?.textContent || text), cardBrand, ref);
      const priceEl = card.querySelector('.special-price .price, [data-price-type="finalPrice"] .price, .price-final_price .price, .price, [itemprop="price"]');
      const price = money(priceEl?.textContent || text);
      const imgEl = card.querySelector('img.product-image-photo, img[itemprop="image"], img');
      out.push({merchant:'Mega Dental', source_url:url, name:name||null, merchant_reference:ref, manufacturer_reference:null, ean:null, brand:cardBrand||null, category:null, variant:null, packaging:null, price_eur:price, availability:null, image_url:bestImage(imgEl,pageUrl), listing_page:pageUrl, captured_at:new Date().toISOString(), catalog_source:'browser_all_brands_capture_v1'});
    }
    return out;
  };
  const fetchDoc = async (url) => {
    const r = await fetch(url, {credentials:'include', cache:'no-store', headers:{'Accept':'text/html,application/xhtml+xml'}});
    if (r.status === 403 || r.status === 429) throw new Error('Protection HTTP ' + r.status + ' sur ' + url);
    if (!r.ok) throw new Error('HTTP ' + r.status + ' sur ' + url);
    const html = await r.text();
    if (/just a moment|attention required|captcha|verify you are human/i.test(html.slice(0, 8000))) throw new Error('Page de protection détectée sur ' + url);
    return new DOMParser().parseFromString(html, 'text/html');
  };

  console.log('Mega Dental: récupération de la liste des marques…');
  const indexDoc = location.href.startsWith(INDEX) ? document : await fetchDoc(INDEX);
  let brandUrls = [...indexDoc.querySelectorAll('a[href*="/brands/"]')]
    .map(a => abs(a.getAttribute('href'), INDEX))
    .filter(u => u && /^https:\/\/www\.megadental\.fr\/brands\//i.test(u) && !/toutes-les-marques|\/brands\/?$/i.test(u));
  brandUrls = [...new Set(brandUrls)];
  console.log('Marques détectées:', brandUrls.length);
  if (!brandUrls.length) throw new Error('Aucune page de marque détectée. Lance le script depuis ' + INDEX);

  const all = new Map();
  const errors = [];
  let pagesRead = 0;
  for (let i = 0; i < brandUrls.length; i++) {
    const brandUrl = brandUrls[i];
    try {
      const first = await fetchDoc(brandUrl);
      const brand = pageBrand(first) || brandUrl.split('/').pop();
      const pageQueue = [brandUrl];
      const pageSeen = new Set();
      let doc = first;
      while (pageQueue.length) {
        const pageUrl = pageQueue.shift();
        if (pageSeen.has(pageUrl)) continue;
        pageSeen.add(pageUrl);
        if (pageUrl !== brandUrl) doc = await fetchDoc(pageUrl);
        pagesRead++;
        for (const p of extractProducts(doc, pageUrl)) {
          const prev = all.get(p.source_url);
          if (!prev || Object.values(p).filter(v => v !== null && v !== '').length > Object.values(prev).filter(v => v !== null && v !== '').length) all.set(p.source_url, p);
        }
        const pager = [...doc.querySelectorAll('.pages a[href], .toolbar a[href*="p="], a.action.next[href]')]
          .map(a => abs(a.getAttribute('href'), pageUrl))
          .filter(u => u && u.startsWith(brandUrl.split('?')[0]) && /[?&]p=\d+/i.test(u));
        for (const u of pager) if (!pageSeen.has(u) && !pageQueue.includes(u)) pageQueue.push(u);
        await sleep(DELAY_MS);
      }
      console.log(`[${i+1}/${brandUrls.length}] ${brand}: total cumulé ${all.size}`);
    } catch (e) {
      errors.push({url:brandUrl, error:String(e.message || e)});
      console.warn(`[${i+1}/${brandUrls.length}] arrêt sur ${brandUrl}:`, e.message || e);
      if (/Protection HTTP|Page de protection/i.test(String(e.message || e))) break;
    }
  }

  const products = [...all.values()];
  const payload = {source:'mega_dental_browser_all_brands_capture_v1', captured_at:new Date().toISOString(), brands_discovered:brandUrls.length, pages_read:pagesRead, total_products:products.length, errors, products};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'mega_all_brands_' + new Date().toISOString().replace(/[:.]/g,'-') + '.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  console.log('Terminé. Produits uniques:', products.length, 'Pages lues:', pagesRead, 'Erreurs:', errors.length);
})();
