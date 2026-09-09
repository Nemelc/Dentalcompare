#!/usr/bin/env python3
"""Resumable public Dentaltix collector for DentalCompare.

Uses ordinary public HTML only. No login, browser automation, CAPTCHA handling or
access-control circumvention. Discovery and product extraction are incremental so
partial runs are preserved instead of replacing the master catalogue.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, re, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE='https://www.dentaltix.com'
ROOTS=['/fr/cabinet-dentaire','/fr/equipement','/fr/laboratoire-dentaire']
CHALLENGE=('captcha','cloudflare','access denied','verify you are human')
UA='Mozilla/5.0 (compatible; DentalCompareCatalog/2.0; public catalogue refresh)'
_tls=threading.local()
class AccessBlocked(RuntimeError): pass

def now(): return datetime.now(timezone.utc).isoformat()
def session():
    s=getattr(_tls,'s',None)
    if s is None:
        s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9'})
        s.mount('https://',requests.adapters.HTTPAdapter(pool_connections=12,pool_maxsize=12,max_retries=0)); _tls.s=s
    return s

def get(url,timeout=20,retries=2):
    last=None
    for a in range(retries+1):
        try:
            r=session().get(url,timeout=timeout); low=(r.text[:12000] or '').lower()
            if r.status_code in (403,429) or any(x in low for x in CHALLENGE): raise AccessBlocked(f'HTTP {r.status_code}/challenge {url}')
            if r.status_code>=500 and a<retries: time.sleep(.8*(a+1)); continue
            r.raise_for_status(); return r
        except AccessBlocked: raise
        except Exception as e:
            last=e
            if a<retries: time.sleep(.8*(a+1)); continue
            raise
    raise last

def clean(x): return re.sub(r'\s+',' ',x or '').strip()
def money(x):
    try:return float(x.replace('\u202f','').replace('\u00a0','').replace(' ','').replace(',','.')) if x else None
    except:return None

def load_json(path,default):
    p=Path(path)
    if not p.exists(): return default
    try:return json.loads(p.read_text(encoding='utf-8'))
    except:return default

def save_json(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def product_links(html):
    soup=BeautifulSoup(html,'lxml'); out=set()
    for a in soup.find_all('a',href=True):
        href=urljoin(BASE,a['href']).split('#')[0]; p=urlparse(href)
        if not p.netloc.endswith('dentaltix.com') or not p.path.startswith('/fr/'): continue
        if any(z in p.path for z in ('/blog','/contact','/marques','/manufacturer','/category','/produits-dentaires-pour-les-patients')): continue
        parent=a.parent; context=clean(parent.get_text(' ',strip=True) if parent else '')
        if '€' in context or 'Voir options' in context or 'Ajouter' in context: out.add(href)
    return out

def discover_batch(urls_path,state_path,max_page=500,batch=60,workers=3):
    urls=set(load_json(urls_path,[])); st=load_json(state_path,{'next_page':{r:0 for r in ROOTS}}); nxt=st.setdefault('next_page',{r:0 for r in ROOTS})
    jobs=[]
    while len(jobs)<batch:
        progressed=False
        for root in ROOTS:
            p=int(nxt.get(root,0))
            if p>=max_page: continue
            u=BASE+root+(f'?page={p}' if p else '')
            jobs.append((root,p,u)); nxt[root]=p+1; progressed=True
            if len(jobs)>=batch: break
        if not progressed: break
    blocked=False
    def one(item):
        root,p,u=item; r=get(u); return root,p,product_links(r.text)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(one,j):j for j in jobs}
        for n,f in enumerate(cf.as_completed(futs),1):
            root,p,u=futs[f]
            try:
                _,_,found=f.result(); urls.update(found)
                if n%15==0: print(f'[Dentaltix] découverte lot {n}/{len(jobs)}: {len(urls)} URLs cumulées',flush=True)
            except AccessBlocked as e:
                blocked=True; print('[Dentaltix] protection pendant découverte:',e,flush=True)
                # rewind pages not safely completed, including current and cancelled futures
                for ff,jj in futs.items():
                    if not ff.done() or ff is f:
                        rr,pp,_=jj; nxt[rr]=min(int(nxt.get(rr,pp)),pp)
                    ff.cancel()
                break
            except Exception as e: print('[Dentaltix] erreur découverte',u,e,flush=True)
    save_json(urls_path,sorted(urls)); save_json(state_path,{'next_page':nxt,'updated_at':now()})
    return sorted(urls),blocked,nxt

def parse(url):
    r=get(url); soup=BeautifulSoup(r.text,'lxml'); h=soup.find('h1'); name=clean(h.get_text(' ',strip=True) if h else '')
    if not name:return []
    text=clean(soup.get_text(' ',strip=True)); brand=''; m=re.search(r'\bde\s+([A-Z0-9][A-Z0-9 .&+\-/]{1,50})\b',text)
    if m: brand=clean(m.group(1))
    crumbs=[clean(x.get_text(' ',strip=True)) for x in soup.select('.breadcrumb a,nav[aria-label*=breadcrumb] a')]; category=' > '.join(x for x in crumbs if x and x.lower()!='accueil')
    og=soup.find('meta',attrs={'property':'og:image'}); image=urljoin(BASE,og.get('content')) if og and og.get('content') else ''
    if not image:
        im=soup.find('img',src=True); image=urljoin(BASE,im['src']) if im else ''
    captured=now(); rows=[];seen=set(); blocks=soup.select('[itemprop="offers"],.product-variation,.variation,.attribute,.product-info') or [soup]
    ref_re=re.compile(r'(?:Réf(?:érence)?\.?\s*(?:Dentaltix)?|SKU)\s*[:#]?\s*([A-Za-z0-9._/-]{3,40})',re.I); price_re=re.compile(r'(\d{1,6}(?:[\s\u00a0\u202f]\d{3})*[,.]\d{2})\s*€')
    for b in blocks:
        bt=clean(b.get_text(' ',strip=True)); refs=ref_re.findall(bt); prices=price_re.findall(bt)
        for ref in refs:
            ref=clean(ref)
            if ref.lower() in ('dentaltix','produit','reference','référence') or ref in seen: continue
            seen.add(ref); rows.append({'merchant':'Dentaltix','url':url,'name':name,'price':money(prices[-1]) if prices else None,'currency':'EUR','merchant_reference':ref,'manufacturer_reference':'','ean':'','brand':brand,'category':category,'variant':'','packaging':'','image_url':image,'availability':'','captured_at':captured})
    if not rows:
        meta=soup.find('meta',attrs={'itemprop':'sku'}); ref=clean(meta.get('content')) if meta and meta.get('content') else ''
        prices=price_re.findall(text)
        if ref: rows=[{'merchant':'Dentaltix','url':url,'name':name,'price':money(prices[-1]) if prices else None,'currency':'EUR','merchant_reference':ref,'manufacturer_reference':'','ean':'','brand':brand,'category':category,'variant':'','packaging':'','image_url':image,'availability':'','captured_at':captured}]
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=5);ap.add_argument('--discover-workers',type=int,default=3);ap.add_argument('--max-pages',type=int,default=500);ap.add_argument('--discover-chunk',type=int,default=60);ap.add_argument('--product-chunk',type=int,default=300);ap.add_argument('--urls-out',default='backend/snapshot/data/dentaltix_product_urls.json');ap.add_argument('--discovery-state',default='backend/snapshot/data/dentaltix_discovery_progress.json');ap.add_argument('--progress-state',default='backend/snapshot/data/dentaltix_progress.json');ap.add_argument('--output',default='backend/snapshot/data/dentaltix_catalog.json');args=ap.parse_args()
    urls,blocked,nxt=discover_batch(args.urls_out,args.discovery_state,args.max_pages,args.discover_chunk,args.discover_workers)
    progress=load_json(args.progress_state,{'completed':[]}); completed=set(progress.get('completed',[])); master=load_json(args.output,{'products':[]}); byref={str(x.get('merchant_reference')):x for x in master.get('products',[]) if x.get('merchant_reference')}
    todo=[u for u in urls if u not in completed][:args.product_chunk]
    print(f'[Dentaltix] reprise produits: {len(completed)}/{len(urls)} URLs; lot={len(todo)}',flush=True)
    errors=[]
    if not blocked:
        def one(u): return u,parse(u)
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs={ex.submit(one,u):u for u in todo}
            for n,f in enumerate(cf.as_completed(futs),1):
                u=futs[f]
                try:
                    _,rows=f.result()
                    for row in rows: byref[str(row['merchant_reference'])]=row
                    completed.add(u)
                except AccessBlocked as e:
                    blocked=True;errors.append({'url':u,'error':str(e)});print('[Dentaltix] protection produit:',e,flush=True)
                    for x in futs:x.cancel()
                    break
                except Exception as e: errors.append({'url':u,'error':str(e)});print('[Dentaltix] erreur produit',u,e,flush=True)
                if n%25==0: print(f'[Dentaltix] lot {n}/{len(todo)} — {len(byref)} refs cumulées',flush=True)
    save_json(args.progress_state,{'completed':sorted(completed),'updated_at':now()})
    discovery_complete=all(int(nxt.get(r,0))>=args.max_pages for r in ROOTS)
    payload={'source':'dentaltix_public_resumable_v2','captured_at':now(),'product_pages_discovered':len(urls),'product_pages_completed':len(completed),'discovery_complete':discovery_complete,'catalogue_complete':discovery_complete and len(completed)>=len(urls),'total_products':len(byref),'errors':errors,'products':list(byref.values())}
    save_json(args.output,payload)
    print(f"[Dentaltix] sauvegarde: {len(urls)} URLs découvertes, {len(completed)} traitées, {len(byref)} refs, découverte complète={discovery_complete}",flush=True)
    return 2 if blocked else 0
if __name__=='__main__': raise SystemExit(main())
