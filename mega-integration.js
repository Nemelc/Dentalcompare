// Catalogue DentalCompare : Mega Dental + GACD + Dentaltix.
(function(){
  'use strict';
  const SOURCES=[['Mega Dental','mega_catalog_visible_test.json',false],['GACD','gacd_catalog_visible.json.gz',true],['Dentaltix','backend/snapshot/data/dentaltix_catalog.json',false]];
  const PAGE_SIZE=60, STOP=new Set('de du des la le les un une pour avec sans et en au aux par sur boite coffret lot unite dental dentaire'.split(' '));
  const BASE_CATEGORIES=[
    ['usage-unique','Usage unique'],['anesthesie','Anesthésie'],['empreintes','Empreintes'],
    ['rotatifs','Instruments rotatifs'],['endodontie','Endodontie'],['hygiene','Hygiène & stérilisation']
  ];
  let products=[],filtered=[],category='usage-unique',query='',sort='default',visible=PAGE_SIZE;
  const esc=v=>String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  const fold=v=>String(v||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
  const ref=v=>String(v||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
  const normBrand=v=>fold(v).replace(/\s+\d+$/,'').replace(/ /g,'').replace(/^3m(espe|oralcare)?$/,'solventum').replace(/^dentsply$/,'dentsplysirona');
  const tokens=v=>new Set(fold(v).split(' ').filter(x=>x.length>1&&!STOP.has(x)));
  const variants=v=>new Set(String(v||'').toUpperCase().match(/\b(?:A[1-4](?:\.5)?|B[1-4]|C[1-4]|D[2-4]|XS|S|M|L|XL|\d+(?:[.,]\d+)?\s*(?:MM|ML|MG|G)|\d+\s*(?:PCS|PIECES|CAPSULES|SERINGUES|BLOCS))\b/g)||[]);
  const ean=v=>/^\d{8,14}$/.test(ref(v))?ref(v):'';
  const mfr=v=>{const x=ref(v);return x.length>=4&&!['NONE','NULL','REFERENCE','PRODUIT','DENTALTIX'].includes(x)?x:'';};
  const money=v=>Number(v).toFixed(2).replace('.',',')+' €';
  const intersect=(a,b)=>{let n=0;a.forEach(x=>{if(b.has(x))n++;});return n;};
  // Matching volontairement permissif : un libellé court entièrement contenu
  // dans un libellé marchand plus détaillé doit être regroupé.
  function similarity(a,b){const x=tokens(a),y=tokens(b);return x.size&&y.size?intersect(x,y)/Math.min(x.size,y.size):0;}
  function variantsCompatible(a,b){const x=variants(a),y=variants(b);return !x.size||!y.size||intersect(x,y)>0;}
  function baseCategory(raw,name){
    const s=fold((raw||'')+' '+(name||''));
    if(/anesth|aiguille|seringue carpule|carpule/.test(s))return ['anesthesie','Anesthésie'];
    if(/empreinte|silicone|alginate|porte empreinte|prothese|platre|laboratoire/.test(s))return ['empreintes','Empreintes'];
    if(/rotatif|fraise|poliss|disque abras|contre angle|turbine/.test(s))return ['rotatifs','Instruments rotatifs'];
    if(/endodont|endocanalaire|canal|lime|gutta|apex|obturation canalaire/.test(s))return ['endodontie','Endodontie'];
    if(/hygiene|steril|desinfect|nettoy|autoclave|sachet de steril|thermodesinfect/.test(s))return ['hygiene','Hygiène & stérilisation'];
    return ['usage-unique','Usage unique'];
  }
  function normalize(raw,merchant){
    const price=Number(raw.price_eur!=null?raw.price_eur:raw.price);
    const name=String(raw.name||'').trim(),detailCategory=String(raw.dental_category||raw.category||'').trim();
    const [categoryKey,categoryLabel]=baseCategory(detailCategory,name);
    return {merchant:raw.merchant||merchant,name,brand:String(raw.brand||'').trim(),categoryKey,categoryLabel,detailCategory,variant:raw.variant||'',packaging:raw.packaging||'',price,image:raw.image_url||raw.image||'',availability:raw.availability||'',merchantReference:raw.merchant_reference||'',manufacturerReference:raw.manufacturer_reference||'',ean:raw.ean||'',url:raw.source_url||raw.url||''};
  }
  const usable=p=>p.name&&Number.isFinite(p.price)&&p.price>0&&p.image&&p.url;
  function makeGroup(o,id){return {id,name:o.name,brand:o.brand,categoryKey:o.categoryKey,categoryLabel:o.categoryLabel,detailCategory:o.detailCategory,image:o.image,manufacturerReference:o.manufacturerReference,ean:o.ean,offers:[o]};}
  function combine(offers){
    const groups=[],byEan=new Map(),byMfr=new Map(),byToken=new Map();
    const accepts=(g,o)=>!g.offers.some(x=>x.merchant===o.merchant);
    function index(g){
      const e=ean(g.ean);if(e)byEan.set(e,g);
      const r=mfr(g.manufacturerReference);if(r){const a=byMfr.get(r)||[];if(!a.includes(g))a.push(g);byMfr.set(r,a);}
      tokens(g.name).forEach(t=>{if(t.length<3)return;const a=byToken.get(t)||[];if(a.length<500&&!a.includes(g))a.push(g);byToken.set(t,a);});
    }
    offers.forEach(o=>{
      let g=null;const e=ean(o.ean),r=mfr(o.manufacturerReference),b=normBrand(o.brand);
      if(e){const candidate=byEan.get(e)||null;if(candidate&&accepts(candidate,o))g=candidate;}
      if(!g&&r){const candidates=byMfr.get(r)||[];g=candidates.find(x=>accepts(x,o)&&(!b||!normBrand(x.brand)||b===normBrand(x.brand)))||null;}
      if(!g){
        const counts=new Map();tokens(o.name).forEach(t=>(byToken.get(t)||[]).forEach(x=>counts.set(x,(counts.get(x)||0)+1)));
        let best=null,bestCommon=0,bestScore=0;
        counts.forEach((common,x)=>{if(!accepts(x,o))return;const s=similarity(o.name,x.name);if(common>bestCommon||(common===bestCommon&&s>bestScore)){best=x;bestCommon=common;bestScore=s;}});
        // Choix produit assumé : deux mots significatifs communs suffisent,
        // même lorsque les libellés, marques ou conditionnements divergent.
        if(bestCommon>=2)g=best;
      }
      if(!g){g=makeGroup(o,'p'+(groups.length+1));groups.push(g);index(g);}
      else if(!g.offers.some(x=>x.merchant===o.merchant&&ref(x.merchantReference)===ref(o.merchantReference))){g.offers.push(o);if(!g.image)g.image=o.image;index(g);}
    });
    return groups.map(g=>({...g,offers:g.offers.sort((a,b)=>a.price-b.price),minPrice:Math.min(...g.offers.map(x=>x.price))}));
  }
  const haystack=p=>[p.name,p.brand,p.categoryLabel,p.detailCategory,p.manufacturerReference,p.ean,...p.offers.map(x=>x.merchantReference)].join(' ').toLowerCase();
  function buildNav(){const nav=document.querySelector('.subnav');if(!nav)return;nav.innerHTML='<div class="subnav-label">Catégories</div>';BASE_CATEGORIES.forEach(([key,label])=>{const b=document.createElement('button');b.textContent=label;b.dataset.cat=key;if(key===category)b.classList.add('active');b.onclick=()=>{category=key;query='';visible=PAGE_SIZE;const i=document.getElementById('site-search');if(i)i.value='';buildNav();apply();};nav.appendChild(b);});}
  function card(p){const best=p.offers[0],max=Math.max(...p.offers.map(x=>x.price));const ranks=p.offers.map((o,i)=>`<div class="rank-row ${i===0?'best':''}"><span class="num">${i+1}</span><span class="merch">${esc(o.merchant)}</span><span class="rank-bar-track"><span class="rank-bar-fill" style="width:${Math.max(18,100*o.price/max)}%"></span></span><span class="price">${money(o.price)}</span></div>`).join('');const payload={id:p.id,name:p.name,tag:p.categoryLabel,sub:p.brand,prices:p.offers.map(o=>({merchant:o.merchant,value:o.price,url:o.url}))};return `<div class="card"><div class="card-top"><div class="prod-photo" style="height:180px;padding:10px;overflow:hidden"><img src="${esc(p.image)}" alt="${esc(p.name)}" loading="lazy" style="max-width:100%;max-height:100%;object-fit:contain" onerror="this.style.display='none'"></div><span class="tag">${esc(p.categoryLabel)}</span><p class="prod-name">${esc(p.name)}</p><div class="prod-sub">${esc(p.brand)}${p.manufacturerReference?' · Réf. fabricant '+esc(p.manufacturerReference):''}</div></div><div class="price-hero"><div class="from">Meilleur prix parmi ${p.offers.length} offre(s)</div><div class="amount">${money(p.minPrice)}</div></div><div><div class="rank-label">Comparaison des offres</div><div class="rank-list">${ranks}</div></div><div class="cta-row"><button class="cta-btn" onclick="window.open('${esc(best.url)}','_blank','noopener')">Voir chez ${esc(best.merchant)} &nbsp;→</button><div class="cta-note">Ouvre la fiche du marchand</div></div><button class="add-cart-btn" onclick='addProductToCart(this)' data-product='${JSON.stringify(payload).replace(/'/g,'&#39;')}'>+ Ajouter au panier</button></div>`;}
  function draw(){const grid=document.getElementById('grid');if(!grid)return;const shown=filtered.slice(0,visible);grid.innerHTML=shown.length?shown.map(card).join(''):'<div class="empty-state">Aucune référence trouvée.</div>';if(visible<filtered.length){const d=document.createElement('div');d.style='grid-column:1/-1;text-align:center';d.innerHTML='<button class="cta-btn" style="display:inline-flex;flex:none;padding:11px 22px">Afficher 60 de plus</button>';d.firstChild.onclick=()=>{visible+=PAGE_SIZE;draw();};grid.appendChild(d);}}
  function apply(){let list=category==='all'?products:products.filter(p=>p.categoryKey===category);if(query)list=list.filter(p=>haystack(p).includes(query.toLowerCase()));list=[...list];if(sort==='price-asc')list.sort((a,b)=>a.minPrice-b.minPrice);filtered=list;const title=document.getElementById('page-title'),sub=document.getElementById('page-sub');if(title)title.textContent=query?`Résultats pour « ${query} »`:(BASE_CATEGORIES.find(x=>x[0]===category)?.[1]||'Catalogue dentaire');if(sub){const offers=filtered.reduce((n,p)=>n+p.offers.length,0);sub.textContent=`${filtered.length.toLocaleString('fr-FR')} produit(s) · ${offers.toLocaleString('fr-FR')} offre(s) comparées`;}draw();}
  function overrides(){window.handleSearch=e=>{query=e.key==='Escape'?'':e.target.value.trim();if(e.key==='Escape')e.target.value='';visible=PAGE_SIZE;apply();};window.closeSearchSoon=()=>{};window.closeSearch=()=>{};window.sortCards=m=>{sort=m;visible=PAGE_SIZE;apply();};window.switchCategory=k=>{category=k||'all';query='';visible=PAGE_SIZE;buildNav();apply();};const p=document.getElementById('search-results');if(p){p.classList.remove('open');p.innerHTML='';}}
  async function init(){if(!document.getElementById('grid'))return;try{const loaded=await Promise.all(SOURCES.map(async([merchant,url,gzip])=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(url+' '+r.status);const d=gzip?await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).json():await r.json();return (Array.isArray(d)?d:(d.products||[])).map(x=>normalize(x,merchant)).filter(usable);}));products=combine(loaded.flat());filtered=products;overrides();buildNav();apply();}catch(e){console.error('Catalogues DentalCompare non chargés',e);}}
  init();
})();
