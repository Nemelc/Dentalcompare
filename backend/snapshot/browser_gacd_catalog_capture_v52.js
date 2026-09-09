// DentalCompare — GACD v5.2 : reprise IndexedDB sans aucun stockage volumineux dans localStorage.
// À exécuter sur https://www.gacd.fr/ dans DevTools > Console.
(async()=>{
'use strict';
const CFG={delayMs:1200,pauseEvery:200,pauseMs:45000,dbName:'dentalcompare_gacd_v5_1',dbVersion:2,pages:'pages',meta:'meta',legacy:'dentalcompare_gacd_capture_v5',light:'dentalcompare_gacd_capture_v5_1',old:'dentalcompare_gacd_capture_v4'};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const clean=v=>(v==null?'':String(v)).replace(/\s+/g,' ').trim();
const abs=h=>{try{return new URL(h,location.origin).href.split('#')[0]}catch{return''}};
const stamp=()=>new Date().toISOString().replace(/[:.]/g,'-');
const money=s=>{const m=clean(s).replace(/\u00a0/g,' ').match(/([0-9][0-9\s]*[,.][0-9]{2})\s*€/);return m?Number(m[1].replace(/\s/g,'').replace(',','.')):null};
const download=(name,obj)=>{const b=new Blob([JSON.stringify(obj,null,2)],{type:'application/json'}),a=document.createElement('a'),u=URL.createObjectURL(b);a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),1500)};
const load=k=>{try{return JSON.parse(localStorage.getItem(k))||{}}catch{return{}}};
function openDb(){return new Promise((res,rej)=>{const q=indexedDB.open(CFG.dbName,CFG.dbVersion);q.onupgradeneeded=()=>{const d=q.result;if(!d.objectStoreNames.contains(CFG.pages))d.createObjectStore(CFG.pages,{keyPath:'url'});if(!d.objectStoreNames.contains(CFG.meta))d.createObjectStore(CFG.meta,{keyPath:'key'})};q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)})}
const db=await openDb();
function put(store,val){return new Promise((res,rej)=>{const t=db.transaction(store,'readwrite');t.objectStore(store).put(val);t.oncomplete=()=>res();t.onerror=()=>rej(t.error);t.onabort=()=>rej(t.error||new Error('IDB_ABORT'))})}
function get(store,key){return new Promise((res,rej)=>{const q=db.transaction(store,'readonly').objectStore(store).get(key);q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)})}
function hasPage(url){return new Promise((res,rej)=>{const q=db.transaction(CFG.pages,'readonly').objectStore(CFG.pages).getKey(url);q.onsuccess=()=>res(q.result!==undefined);q.onerror=()=>rej(q.error)})}
function allPages(){return new Promise((res,rej)=>{const q=db.transaction(CFG.pages,'readonly').objectStore(CFG.pages).getAll();q.onsuccess=()=>res(q.result||[]);q.onerror=()=>rej(q.error)})}
async function setMeta(key,value){await put(CFG.meta,{key,value,at:new Date().toISOString()})}
async function getMeta(key,def=null){const x=await get(CFG.meta,key);return x?x.value:def}

// 1) Récupération/migration de l'ancien état. AUCUNE écriture dans localStorage.
let urls=await getMeta('productUrls',null);
let errors=await getMeta('errors',[]);
if(!Array.isArray(errors))errors=[];
if(!Array.isArray(urls)||!urls.length){
  const legacy=load(CFG.legacy), light=load(CFG.light), old=load(CFG.old);
  const sourceUrls=(Array.isArray(legacy.productUrls)&&legacy.productUrls.length)?legacy.productUrls:(Array.isArray(light.productUrls)&&light.productUrls.length)?light.productUrls:(Array.isArray(old.productUrls)?old.productUrls:[]);
  urls=[...new Set(sourceUrls)];
  if(!urls.length)throw new Error('Aucune liste URL GACD trouvée. Ne supprime pas les anciennes données et relance depuis le même profil Chrome.');
  await setMeta('productUrls',urls);
  const obj=legacy.products&&typeof legacy.products==='object'?legacy.products:{};
  const entries=Object.entries(obj);
  if(entries.length){
    console.log(`[GACD v5.2] Vérification/migration de ${entries.length} fiches déjà capturées…`);
    for(let i=0;i<entries.length;i++){
      const [url,rows]=entries[i];
      if(!(await hasPage(url)))await put(CFG.pages,{url,rows:Array.isArray(rows)?rows:[],savedAt:new Date().toISOString()});
      if((i+1)%100===0)console.log(`[GACD v5.2] Migration ${i+1}/${entries.length}`);
    }
  }
  if(Array.isArray(legacy.errors))errors=legacy.errors.slice(-250);
  await setMeta('errors',errors);
  // Une fois URLs + produits sécurisés dans IndexedDB, on libère localStorage.
  try{localStorage.removeItem(CFG.legacy)}catch{}
  try{localStorage.removeItem(CFG.light)}catch{}
  console.log(`[GACD v5.2] Migration sécurisée. ${urls.length} URL conservées dans IndexedDB.`);
}else{
  // v5.1 avait déjà pu migrer les pages avant de planter sur saveLight : on les réutilise.
  try{localStorage.removeItem(CFG.legacy)}catch{}
  try{localStorage.removeItem(CFG.light)}catch{}
  console.log(`[GACD v5.2] État IndexedDB retrouvé : ${urls.length} URL.`);
}

async function getDoc(url){
  const r=await fetch(url,{credentials:'include',cache:'no-store'});
  if([403,429].includes(r.status))throw new Error('PROTECTION_HTTP_'+r.status);
  if(!r.ok)throw new Error('HTTP_'+r.status);
  const html=await r.text(),doc=new DOMParser().parseFromString(html,'text/html');
  const probe=clean((doc.title||'')+' '+(doc.body?.innerText||'')).slice(0,3000);
  if(/just a moment|attention required|access denied|verify you are human|security check|checking your browser/i.test(probe))throw new Error('PROTECTION_CHALLENGE');
  return doc;
}
function meta(doc,p){return clean(doc.querySelector(`meta[property="${p}"],meta[name="${p}"]`)?.content)}
function stockFrom(t){return (t.match(/\b(En stock|Sur commande|En réapprovisionnement(?:\s+Disponible sous \d+ jours)?|Arrêté)\b/i)||[])[1]||''}
function validRef(v){v=clean(v);return /^[A-Z0-9][A-Z0-9._\/-]{1,}$/i.test(v)&&!/^(nom|name|r|ref|reference)$/i.test(v)?v:''}
function parseProduct(doc,url){
  const body=doc.body?.innerText||'',h1=clean(doc.querySelector('h1')?.textContent)||meta(doc,'og:title')||'Produit GACD';
  let brand=clean(doc.querySelector('[itemprop="brand"],.product-brand,.brand,[class*="manufacturer"]')?.textContent);
  if(!brand){const lines=body.split(/\r?\n/).map(clean).filter(Boolean),i=lines.findIndex(x=>x===h1);if(i>=0&&lines[i+1]&&!/^Réf|Voir la description/i.test(lines[i+1]))brand=lines[i+1]}
  const image=meta(doc,'og:image')||abs(doc.querySelector('.gallery-placeholder img,.product.media img,img[itemprop="image"]')?.getAttribute('src'));
  const category=[...doc.querySelectorAll('.breadcrumbs a,.breadcrumbs strong')].map(x=>clean(x.textContent)).filter(Boolean).slice(1).join(' > '),capturedAt=new Date().toISOString(),out=[];
  const matches=[...body.matchAll(/Réf\.\s*GACD\s*:\s*/ig)];
  for(let i=0;i<matches.length;i++){
    const start=matches[i].index+matches[i][0].length,end=i+1<matches.length?matches[i+1].index:Math.min(body.length,start+2500),seg=body.slice(start,end),lines=seg.split(/\r?\n/).map(clean).filter(Boolean);
    if(!lines.length)continue;
    const gacd=validRef(lines[0].split(/\s+/)[0]);if(!gacd)continue;
    const mm=seg.match(/Réf\.\s*Fabricant\s*:\s*([^\s\r\n]+)/i),mref=validRef(mm?.[1]||''),stock=stockFrom(seg),price=money(seg);
    let name='';for(const line of lines.slice(1)){if(/^Réf\.\s*Fabricant/i.test(line))break;if(/^(COULEUR|DIMENSION|TAILLE|TEINTE|FORME|GRAIN|N°|ISO|CONICITE|VISCOSITE|PRISE|LONGUEUR|DIAMETRE|DIAMÈTRE)\s*:/i.test(line))continue;if(/^(En stock|Sur commande|En réapprovisionnement|Arrêté|Ajouter au panier|Choisir une quantité|Prix|Qté)$/i.test(line))continue;if(/^[0-9\s,.]+\s*€/.test(line))continue;name=line;break}if(!name)name=h1;
    out.push({merchant:'GACD',merchant_reference:gacd,manufacturer_reference:mref||null,ean:null,name,brand:brand||null,category:category||null,variant:name!==h1?name:null,packaging:null,price_eur:price,availability:stock||null,image_url:image||null,source_url:url,captured_at:capturedAt});
  }
  const seen=new Set();return out.filter(p=>{if(seen.has(p.merchant_reference))return false;seen.add(p.merchant_reference);return true});
}

// 2) Reprise : les fiches déjà présentes dans IndexedDB sont sautées.
let already=0;for(const u of urls)if(await hasPage(u))already++;
console.log(`[GACD v5.2] Reprise : ${already}/${urls.length} fiches déjà sécurisées. Il en reste ${urls.length-already}.`);
let session=0,done=already;
for(let i=0;i<urls.length;i++){
  const url=urls[i];if(await hasPage(url))continue;
  try{
    const doc=await getDoc(url),rows=parseProduct(doc,url);await put(CFG.pages,{url,rows,savedAt:new Date().toISOString()});done++;session++;
    console.log(`[GACD v5.2] ${done}/${urls.length} — ${rows.length} variante(s) — ${url}`);
    if(session%25===0)await setMeta('progress',{done,total:urls.length,lastUrl:url,index:i});
    if(session%CFG.pauseEvery===0){console.log('[GACD v5.2] Pause 45 s…');await sleep(CFG.pauseMs)}
    await sleep(CFG.delayMs);
  }catch(e){errors.push({url,error:e.message,at:new Date().toISOString()});errors=errors.slice(-250);await setMeta('errors',errors);console.warn('[GACD v5.2]',url,e.message);if(/^PROTECTION_/.test(e.message)){const pages=await allPages(),products=pages.flatMap(x=>x.rows||[]);download('gacd_v52_partial_'+stamp()+'.json',{source:'gacd_browser_public_capture_v5_2',product_pages:urls.length,completed_pages:pages.length,total_products:products.length,errors,products});throw e}}
}
const pages=await allPages(),products=pages.flatMap(x=>x.rows||[]);
const output={source:'gacd_browser_public_capture_v5_2',captured_at:new Date().toISOString(),product_pages:urls.length,completed_pages:pages.length,total_products:products.length,errors,products};
download('gacd_catalog_v52_'+stamp()+'.json',output);
console.log(`[GACD v5.2] TERMINÉ : ${pages.length}/${urls.length} fiches, ${products.length} références. Fichier téléchargé.`);
})();