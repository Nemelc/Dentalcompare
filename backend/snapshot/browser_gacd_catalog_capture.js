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
    storageKey: 'dentalcompare_gacd_capture_v2'
  };

  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = v => (v == null ? '' : String(v)).replace(/\s+/g, ' ').trim();
  const abs = (href, base=location.origin) => { try { return new URL(href, base).href.split('#')[0]; } catch { return ''; } };
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

  function loadState(){ try { return JSON.parse(localStorage.getItem(CFG.storageKey)) || {}; } catch { return {}; } }
  function saveState(s){ localStorage.setItem(CFG.storageKey, JSON.stringify(s)); }
  const state = Object.assign({version:2, productUrls:[], products:{}, errors:[], categoryPagesDone:[], startedAt:new Date().toISOString()}, loadState());

  async function getDoc(url){
    const res = await fetch(url, {credentials:'include', cache:'no-store'});
    if ([403,429].includes(res.status)) throw new Error('PROTECTION_HTTP_'+res.status);
    if (!res.ok) throw new Error('HTTP_'+res.status);
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html,'text/html');
    const title = clean(doc.title || '');
    const bodyText = clean(doc.body?.innerText || '').slice(0,3000);
    if (/just a moment|attention required|access denied|verify you are human|security check/i.test(title) || /verify you are human|checking your browser|enable javascript and cookies to continue|attention required/i.test(bodyText)) throw new Error('PROTECTION_CHALLENGE');
    return doc;
  }

  const excludedTop = /^(?:\/amenagement-textile-et-tech(?:\/|$)|\/nos-marques(?:\/|$)|\/offre-gacd(?:\/|$)|\/promotions?(?:\/|$)|\/customer(?:\/|$)|\/checkout(?:\/|$)|\/catalogsearch(?:\/|$)|\/search(?:\/|$)|\/contact(?:\/|$)|\/home-connectee(?:\/|$))/i;

  function categorySeeds(doc){
    // Le menu GACD contient les vraies catégories dentaires. On ne prend que les liens du menu,
    // et on écarte volontairement Tech/loisirs, marques, promos et pages de service.
    const anchors=[...doc.querySelectorAll('nav a[href], .navigation a[href], [class*="menu"] a[href]')];
    const urls=anchors.map(a=>abs(a.getAttribute('href'))).filter(u=>{
      try {
        const x=new URL(u); return x.origin===location.origin && /\.html$/i.test(x.pathname) && !excludedTop.test(x.pathname);
      } catch { return false; }
    });
    return [...new Set(urls)];
  }

  function isLikelyProductUrl(u){
    try {
      const x=new URL(u); if(x.origin!==location.origin || !/\.html$/i.test(x.pathname) || excludedTop.test(x.pathname)) return false;
      return true;
    } catch { return false; }
  }

  function productLinks(doc){
    // Sélecteurs Magento/GACD centrés sur les cartes produit, pas tous les liens contenant "product".
    const selectors=['a.product-item-link[href]','.product-item-info a.product-item-link[href]','.products-grid .product-item a[href]','.products-list .product-item a[href]','[data-container="product-grid"] a.product-item-link[href]'];
    const out=[];
    selectors.forEach(sel=>doc.querySelectorAll(sel).forEach(a=>{
      const u=abs(a.getAttribute('href')); if(isLikelyProductUrl(u)) out.push(u.split('?')[0]);
    }));
    return [...new Set(out)];
  }

  function nextPageUrl(doc, currentUrl){
    // Utilise le vrai lien "suivant" généré par GACD au lieu de supposer ?p=N.
    const a=doc.querySelector('a.action.next[href], .pages a.next[href], link[rel="next"][href], a[rel="next"][href]');
    if(!a) return '';
    const href=a.getAttribute('href'); const u=abs(href,currentUrl);
    return u && u!==currentUrl ? u : '';
  }

  function meta(doc, prop){ return clean(doc.querySelector(`meta[property="${prop}"],meta[name="${prop}"]`)?.content); }
  function refFrom(text, label){ const re=new RegExp(label+'\\s*:?\\s*([A-Z0-9][A-Z0-9._\\/-]*)','i'); return clean(text.match(re)?.[1]); }
  function stockFrom(text){ return (text.match(/\b(En stock|Sur commande|En réapprovisionnement|Arrêté)\b/i)||[])[1] || ''; }

  function parseProduct(doc, url){
    const pageText=clean(doc.body?.innerText || '');
    const h1=clean(doc.querySelector('h1')?.textContent);
    let brand=''; const brandEl=doc.querySelector('[itemprop="brand"], .product-brand, .brand, [class*="manufacturer"]'); if(brandEl) brand=clean(brandEl.textContent);
    const image=meta(doc,'og:image') || abs(doc.querySelector('.gallery-placeholder img, .product.media img, img[itemprop="image"]')?.getAttribute('src'));
    const category=[...doc.querySelectorAll('.breadcrumbs a, .breadcrumbs strong')].map(x=>clean(x.textContent)).filter(Boolean).slice(1).join(' > ');
    const variants=[];
    const candidateRows=[...doc.querySelectorAll('tr, [class*="variant"], [class*="declinaison"], [class*="reference"]')];
    const seen=new Set();
    for(const row of candidateRows){
      const t=clean(row.innerText); if(!/Réf\.\s*GACD|Référence\s*GACD/i.test(t)) continue;
      const gacd=refFrom(t,'Réf(?:érence|\\.)?\\s*GACD'); if(!gacd || seen.has(gacd)) continue; seen.add(gacd);
      const mref=refFrom(t,'Réf(?:érence|\\.)?\\s*Fabricant');
      const stock=stockFrom(t); const price=money(t);
      const rowName=clean(row.querySelector('[class*="name"], a')?.textContent) || h1;
      variants.push({merchant:'GACD',merchant_reference:gacd,manufacturer_reference:mref||null,ean:null,name:rowName,brand:brand||null,category:category||null,variant:t!==rowName?t:null,packaging:null,price_eur:price,availability:stock||null,image_url:image||null,source_url:url,captured_at:new Date().toISOString()});
    }
    if(!variants.length){
      const gacd=refFrom(pageText,'Réf(?:érence|\\.)?\\s*GACD'); const mref=refFrom(pageText,'Réf(?:érence|\\.)?\\s*Fabricant');
      if(gacd) variants.push({merchant:'GACD',merchant_reference:gacd,manufacturer_reference:mref||null,ean:null,name:h1||meta(doc,'og:title')||'Produit GACD',brand:brand||null,category:category||null,variant:null,packaging:null,price_eur:money(pageText),availability:stockFrom(pageText)||null,image_url:image||null,source_url:url,captured_at:new Date().toISOString()});
    }
    return variants;
  }

  console.log('[GACD v2] Découverte des catégories dentaires…');
  const home=await getDoc(location.origin+'/'); const seeds=categorySeeds(home);
  console.log('[GACD v2] Catégories retenues:',seeds.length);
  const known=new Set(state.productUrls);

  for(let si=0;si<seeds.length;si++){
    let pageUrl=seeds[si]; let previousSignature='';
    for(let p=1;p<=CFG.maxPagesPerCategory && pageUrl;p++){
      if(state.categoryPagesDone.includes(pageUrl)) break;
      try{
        const doc=await getDoc(pageUrl); const links=productLinks(doc);
        const signature=links.join('|'); if(p>1 && signature && signature===previousSignature){ console.warn('[GACD v2] Pagination répétée, arrêt catégorie:',pageUrl); break; }
        previousSignature=signature; let added=0;
        links.forEach(u=>{if(!known.has(u)){known.add(u);state.productUrls.push(u);added++;}});
        state.categoryPagesDone.push(pageUrl); saveState(state);
        console.log(`[GACD v2] catégorie ${si+1}/${seeds.length} page ${p}: ${links.length} produits, +${added}, total ${known.size}`);
        const next=nextPageUrl(doc,pageUrl); if(!links.length || !next) break; pageUrl=next; await sleep(CFG.delayMs);
      }catch(e){
        console.warn('[GACD v2]',pageUrl,e.message); state.errors.push({url:pageUrl,error:e.message,at:new Date().toISOString()}); saveState(state);
        if(/^PROTECTION_/.test(e.message)){download('gacd_partial_'+stamp()+'.json',state);throw e;} break;
      }
    }
  }

  console.log('[GACD v2] Enrichissement des fiches:',state.productUrls.length);
  let done=Object.keys(state.products).length,session=0;
  for(const url of state.productUrls){
    if(state.products[url]) continue;
    try{
      const doc=await getDoc(url); const rows=parseProduct(doc,url); state.products[url]=rows; done++;session++;saveState(state);
      console.log(`[GACD v2] ${done}/${state.productUrls.length} — ${rows.length} référence(s) — ${url}`);
      if(session%CFG.pauseEvery===0){console.log('[GACD v2] Pause 45 s…');await sleep(CFG.pauseMs);} await sleep(CFG.delayMs);
    }catch(e){
      console.warn('[GACD v2]',url,e.message);state.errors.push({url,error:e.message,at:new Date().toISOString()});saveState(state);
      if(/^PROTECTION_/.test(e.message)){download('gacd_partial_'+stamp()+'.json',state);throw e;}
    }
  }

  const products=Object.values(state.products).flat();
  download('gacd_catalog_'+stamp()+'.json',{source:'gacd_browser_public_capture_v2',captured_at:new Date().toISOString(),product_pages:state.productUrls.length,total_products:products.length,errors:state.errors,products});
  console.log('[GACD v2] TERMINÉ:',products.length,'références. Fichier téléchargé.');
})();