#!/usr/bin/env python3
"""Resumable public Dental Good Deal catalogue collector for DentalCompare.

Uses ordinary public HTML only. No login, browser automation, CAPTCHA handling or
access-control circumvention. 403/429/challenge responses stop the run.

The catalogue is incremental: discovered URLs are kept, completed family pages are
remembered, and each run processes only a bounded chunk. Existing products are
merged by merchant_reference so a partial run never replaces the master catalogue.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, re, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE='https://www.dentalgooddeal.com/'
LISTING=BASE+'promotions-page{page}.html'
ARTICLE_RE=re.compile(r'/article_[^\"\'#?]+\.html',re.I)
REF_RE=re.compile(r'\bRéf\s+(\d{4,})\b',re.I)
MFR_RE=re.compile(r'Réf\s+fabri(?:quant|cant)\s*[:\s]*([^\s|<>]+)',re.I)
PRICE_RE=re.compile(r'(\d{1,5}(?:[\s\u00a0]\d{3})*[,.]\d{2})\s*€')
STOCK_VALUES=('En stock','Bientôt disponible','Sur commande','En réapprovisionnement','Indisponible','Arrêté','Rupture de stock')
CHALLENGE_MARKERS=('captcha','cloudflare','access denied','verify you are human')
UA='Mozilla/5.0 (compatible; DentalCompareCatalog/2.0; public catalogue refresh)'
_tls=threading.local()
class AccessBlocked(RuntimeError): pass

def now(): return datetime.now(timezone.utc).isoformat()
def session():
    s=getattr(_tls,'s',None)
    if s is None:
        s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9','Connection':'keep-alive'})
        s.mount('https://',requests.adapters.HTTPAdapter(pool_connections=16,pool_maxsize=16,max_retries=0)); _tls.s=s
    return s

def get(url,timeout=18,retries=2):
    last=None
    for a in range(retries+1):
        try:
            r=session().get(url,timeout=timeout); low=(r.text[:10000] if r.text else '').lower()
            if r.status_code in (403,429) or any(x in low for x in CHALLENGE_MARKERS): raise AccessBlocked(f'HTTP {r.status_code}/challenge {url}')
            if r.status_code>=500 and a<retries: time.sleep(.8*(a+1)); continue
            r.raise_for_status(); return r
        except AccessBlocked: raise
        except Exception as e:
            last=e
            if a<retries: time.sleep(.8*(a+1)); continue
            raise
    raise last

def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def price_float(s):
    try:return float(s.replace('\u00a0','').replace(' ','').replace(',','.')) if s else None
    except:return None

def discover(max_pages=220,workers=4):
    urls=set()
    def one(p):
        r=get(LISTING.format(page=p)); return {urljoin(BASE,m.group(0)) for m in ARTICLE_RE.finditer(r.text)}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(one,p):p for p in range(1,max_pages+1)}
        for n,f in enumerate(cf.as_completed(futs),1):
            urls.update(f.result())
            if n%20==0: print(f'[DGD] découverte {n}/{max_pages}: {len(urls)} familles',flush=True)
    return sorted(urls)

def image_candidates(soup):
    imgs=[]
    for img in soup.find_all('img'):
        src=img.get('src') or img.get('data-src') or img.get('data-original')
        if src: imgs.append((' '.join([str(img.get('alt') or ''),str(src)]),urljoin(BASE,src)))
    og=soup.find('meta',attrs={'property':'og:image'}); og_url=urljoin(BASE,og['content']) if og and og.get('content') else None
    fallback=next((u for _,u in imgs if not any(x in u.lower() for x in ('logo','sprite','icon'))),None)
    return imgs,og_url,fallback

def best_image(imgs,og,fallback,ref): return next((u for hay,u in imgs if ref in hay),None) or og or fallback

def parse_page(url):
    r=get(url); soup=BeautifulSoup(r.text,'lxml')
    h=soup.find('h1') or soup.find('title'); title=clean(h.get_text(' ',strip=True) if h else '')
    crumbs=[clean(x.get_text(' ',strip=True)) for x in soup.select('.breadcrumb a,#breadcrumb a,nav[aria-label*=breadcrumb] a')]
    category=' > '.join(x for x in crumbs if x and x.lower()!='accueil')
    meta_brand=soup.find('meta',attrs={'itemprop':'brand'}); brand=clean(meta_brand.get('content')) if meta_brand else ''
    imgs,og,fallback=image_candidates(soup); text=clean(soup.get_text(' ',strip=True)); matches=list(REF_RE.finditer(text)); out=[];seen=set();captured=now()
    for i,m in enumerate(matches):
        ref=m.group(1)
        if ref in seen: continue
        seen.add(ref); start=m.start(); end=matches[i+1].start() if i+1<len(matches) else min(len(text),start+1800); seg=text[start:end]
        mm=MFR_RE.search(seg); mfr=clean(mm.group(1)) if mm else ''; ps=PRICE_RE.findall(seg); pr=price_float(ps[0]) if ps else None
        stock=next((s for s in STOCK_VALUES if s.lower() in seg.lower()),'')
        variant=seg[m.end()-start:]; variant=re.split(r'Réf\s+fabri(?:quant|cant)|ajouter au|En stock|Bientôt disponible|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture de stock|\d{1,5}[,.]\d{2}\s*€',variant,maxsplit=1,flags=re.I)[0]
        out.append({'merchant':'Dental Good Deal','url':url,'name':title,'price':pr,'currency':'EUR','merchant_reference':ref,'manufacturer_reference':mfr,'ean':'','brand':brand,'category':category,'variant':clean(variant),'packaging':'','image_url':best_image(imgs,og,fallback,ref),'availability':stock,'captured_at':captured})
    return out

def load_json(path,default):
    p=Path(path)
    if not p.exists(): return default
    try:return json.loads(p.read_text(encoding='utf-8'))
    except:return default

def save_json(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=6);ap.add_argument('--discover-workers',type=int,default=4);ap.add_argument('--max-pages',type=int,default=220);ap.add_argument('--chunk-size',type=int,default=400);ap.add_argument('--urls-out',default='backend/snapshot/data/dgd_product_urls.json');ap.add_argument('--state',default='backend/snapshot/data/dgd_progress.json');ap.add_argument('--output',default='backend/snapshot/data/dental_good_deal_catalog.json');args=ap.parse_args()
    urls=load_json(args.urls_out,[])
    if not urls:
        urls=discover(args.max_pages,args.discover_workers);save_json(args.urls_out,urls);print(f'[DGD] découverte terminée: {len(urls)} familles',flush=True)
    else: print(f'[DGD] {len(urls)} URL connues réutilisées',flush=True)
    state=load_json(args.state,{'completed':[]}); completed=set(state.get('completed',[]))
    master=load_json(args.output,{'products':[]}); byref={str(x.get('merchant_reference')):x for x in master.get('products',[]) if x.get('merchant_reference')}
    todo=[u for u in urls if u not in completed][:args.chunk_size]
    print(f'[DGD] reprise: {len(completed)}/{len(urls)} familles terminées; lot={len(todo)}',flush=True)
    blocked=False; errors=[]
    def one(u): return u,parse_page(u)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs={ex.submit(one,u):u for u in todo}
        for n,f in enumerate(cf.as_completed(futs),1):
            u=futs[f]
            try:
                _,rows=f.result()
                for row in rows: byref[str(row['merchant_reference'])]=row
                completed.add(u)
            except AccessBlocked as e:
                blocked=True;errors.append({'url':u,'error':str(e)});print('[DGD] protection détectée:',e,flush=True)
                for x in futs:x.cancel()
                break
            except Exception as e: errors.append({'url':u,'error':str(e)});print('[DGD] erreur',u,e,flush=True)
            if n%25==0: print(f'[DGD] lot {n}/{len(todo)} — {len(byref)} références cumulées',flush=True)
    save_json(args.state,{'completed':sorted(completed),'updated_at':now()})
    payload={'source':'dental_good_deal_public_resumable_v3','captured_at':now(),'product_pages_discovered':len(urls),'product_pages_completed':len(completed),'catalogue_complete':len(completed)>=len(urls),'total_products':len(byref),'errors':errors,'products':list(byref.values())}
    save_json(args.output,payload)
    print(f"[DGD] sauvegarde: {len(completed)}/{len(urls)} familles, {len(byref)} références",flush=True)
    return 2 if blocked else 0
if __name__=='__main__': raise SystemExit(main())
