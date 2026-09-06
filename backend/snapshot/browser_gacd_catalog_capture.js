// DentalCompare — capture publique GACD depuis un navigateur normal.
// À exécuter sur https://www.gacd.fr/ dans DevTools > Console.
// Aucun contournement de protection : arrêt immédiat sur 403/429/challenge.
(async () => {
  'use strict';

  const CFG = {
    delayMs: 1200,
    pauseEvery: 200,
    pauseMs: 45000,
    maxPagesPerCategory: 250,
    storageKey: 'dentalcompare_gacd_capture_v1'
  };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = v => (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
  const abs = href => { try { return new URL(href, location.origin).href.split('#')[0]; } catch { return ''; } };
  const money = s => {
    const m = clean(s).replace(/\u00a0/g, ' ').match(/([0-9][0-9\s]*[,.][0-9]{2}|[0-9][0-9\s]*)\s*€/);
    return m ? Number(m[1].replace(/\s/g,'').replace(',','.')) : null;
  };
  const download = (name, obj) => {
    const blob = new Blob([JSON.stringify(obj, null, 2)], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  };
  const stamp = () => new Date().toISOString().replace(/[:.]/g,'-');

  function loadState(){
    try { return JSON.parse(localStorage.getItem(CFG.storageKey)) || {}; } catch { return {}; }
  }
  function saveState(s){ localStorage.setItem(CFG.storageKey, JSON.stringify(s)); }
  const state = Object.assign({version:1, productUrls:[], products:{}, errors:[], categoryPagesDone:[], startedAt:new Date().toISOString()}, loadState());

  async function getDoc(url){
    const res = await fetch(url, {credentials:'include', cache:'no-store'});
    if ([403,429].includes(res.status)) throw new Error('PROTECTION_HTTP_'+res.status);
    if (!res.ok) throw new Error('HTTP_'+res.status);
    const html = await res.text();
    if (/captcha|cf-chl|cloudflare|access denied|verify you are human/i.test(html)) throw new Error('PROTECTION_CHALLENGE');
    return new DOMParser().parseFromString(html,'text/html');
  }

  function categorySeeds(doc){
    const bad = /\/customer|\/checkout|\/cart|\/search|\/catalogsearch|\/contact|\/mentions|\/conditions|\/privacy|\/brands?|\/promotions?|\/mon-stock/i;
    const urls = [...doc.querySelectorAll('a[href]')].map(a=>abs(a.getAttribute('href')))
      .filter(u=>u.startsWith(location.origin+'/') && /\.html(?:\?|$)/i.test(u) && !bad.test(u));
    return [...new Set(urls)];
  }

  function productLinks(doc){
    const selectors = [
      '.product-item a[href]', '.product-item-link[href]', '.product-item-info a[href]',
      '[class*="product"] a[href*=".html"]'
    ];
    const out = [];
    selectors.forEach(sel => doc.querySelectorAll(sel).forEach(a => {
      const u=abs(a.getAttribute('href'));
      if(u.startsWith(location.origin+'/') && /\.html(?:\?|$)/i.test(u)) out.push(u.split('?')[0]);
    }));
    return [...new Set(out)];
  }

  function meta(doc, prop){ return clean(doc.querySelector(`meta[property="${prop}"],meta[name="${prop}"]`)?.content); }
  function refFrom(text, label){
    const re = new RegExp(label+'\\s*:?\\s*([A-Z0-9][A-Z0-9._\\/-]*)','i');
    return clean(text.match(re)?.[1]);
  }
  function stockFrom(text){
    return (text.match(/\b(En stock|Sur commande|En réapprovisionnement|Arrêté)\b/i)||[])[1] || '';
  }

  function parseProduct(doc, url){
    const pageText = clean(doc.body?.innerText || '');
    const h1 = clean(doc.querySelector('h1')?.textContent);
    let brand = '';
    const brandEl = doc.querySelector('[itemprop="brand"], .product-brand, .brand, [class*="manufacturer"]');
    if(brandEl) brand = clean(brandEl.textContent);
    const image = meta(doc,'og:image') || abs(doc.querySelector('.gallery-placeholder img, .product.media img, img[itemprop="image"]')?.getAttribute('src'));
    const category = [...doc.querySelectorAll('.breadcrumbs a, .breadcrumbs strong')].map(x=>clean(x.textContent)).filter(Boolean).slice(1).join(' > ');

    const variants=[];
    const rows=[...doc.querySelectorAll('tr')];
    for(const row of rows){
      const t=clean(row.innerText);
      if(!/Réf\.\s*GACD|Référence\s*GACD/i.test(t)) continue;
      const gacd=refFrom(t,'Réf(?:érence|\\.)?\\s*GACD');
      if(!gacd) continue;
      const mref=refFrom(t,'Réf(?:érence|\\.)?\\s*Fabricant');
      const stock=stockFrom(t);
      const price=money(t);
      let name=clean(row.querySelector('[class*="name"], [class*="product"] a, a')?.textContent) || h1;
      variants.push({merchant:'GACD',merchant_reference:gacd,manufacturer_reference:mref||null,ean:null,name,brand:brand||null,category:category||null,variant:null,packaging:null,price_eur:price,availability:stock||null,image_url:image||null,source_url:url,captured_at:new Date().toISOString()});
    }

    if(!variants.length){
      const gacd=refFrom(pageText,'Réf(?:érence|\\.)?\\s*GACD');
      const mref=refFrom(pageText,'Réf(?:érence|\\.)?\\s*Fabricant');
      if(gacd) variants.push({merchant:'GACD',merchant_reference:gacd,manufacturer_reference:mref||null,ean:null,name:h1||meta(doc,'og:title')||'Produit GACD',brand:brand||null,category:category||null,variant:null,packaging:null,price_eur:money(pageText),availability:stockFrom(pageText)||null,image_url:image||null,source_url:url,captured_at:new Date().toISOString()});
    }
    return variants;
  }

  console.log('[GACD] Découverte des catégories…');
  const home = await getDoc(location.origin+'/');
  const seeds = categorySeeds(home);
  console.log('[GACD] Pages de départ:', seeds.length);

  const known = new Set(state.productUrls);
  for(let si=0; si<seeds.length; si++){
    const seed=seeds[si];
    for(let p=1; p<=CFG.maxPagesPerCategory; p++){
      const pageUrl = seed + (seed.includes('?')?'&':'?') + 'p=' + p;
      if(state.categoryPagesDone.includes(pageUrl)) continue;
      try{
        const doc=await getDoc(pageUrl); const links=productLinks(doc); let added=0;
        links.forEach(u=>{if(!known.has(u)){known.add(u);state.productUrls.push(u);added++;}});
        state.categoryPagesDone.push(pageUrl); saveState(state);
        console.log(`[GACD] catégorie ${si+1}/${seeds.length} page ${p}: ${links.length} liens, +${added}, total ${known.size}`);
        if(!links.length || (p>1 && added===0)) break;
        await sleep(CFG.delayMs);
      }catch(e){
        console.warn('[GACD]',pageUrl,e.message); state.errors.push({url:pageUrl,error:e.message,at:new Date().toISOString()}); saveState(state);
        if(/^PROTECTION_/.test(e.message)) { download('gacd_partial_'+stamp()+'.json',state); throw e; }
        break;
      }
    }
  }

  console.log('[GACD] Enrichissement des fiches:',state.productUrls.length);
  let done=Object.keys(state.products).length, session=0;
  for(const url of state.productUrls){
    if(state.products[url]) continue;
    try{
      const doc=await getDoc(url); const rows=parseProduct(doc,url);
      state.products[url]=rows; done++; session++; saveState(state);
      console.log(`[GACD] ${done}/${state.productUrls.length} — ${rows.length} référence(s) — ${url}`);
      if(session % CFG.pauseEvery===0){ console.log('[GACD] Pause 45 s…'); await sleep(CFG.pauseMs); }
      await sleep(CFG.delayMs);
    }catch(e){
      console.warn('[GACD]',url,e.message); state.errors.push({url,error:e.message,at:new Date().toISOString()}); saveState(state);
      if(/^PROTECTION_/.test(e.message)){ download('gacd_partial_'+stamp()+'.json',state); throw e; }
    }
  }

  const products=Object.values(state.products).flat();
  const output={source:'gacd_browser_public_capture_v1',captured_at:new Date().toISOString(),product_pages:state.productUrls.length,total_products:products.length,errors:state.errors,products};
  download('gacd_catalog_'+stamp()+'.json',output);
  console.log('[GACD] TERMINÉ:',products.length,'références. Fichier téléchargé.');
})();
