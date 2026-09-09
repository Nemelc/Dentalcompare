#!/usr/bin/env python3
"""Public Dentaltix catalogue collector for DentalCompare.

Uses ordinary public HTML only. No login, browser automation, CAPTCHA handling,
or access-control circumvention. Stops on 403/429/challenge responses.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, re, threading, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE='https://www.dentaltix.com'
START=[BASE+'/fr/cabinet-dentaire', BASE+'/fr/equipement', BASE+'/fr/laboratoire-dentaire']
CHALLENGE=('captcha','cloudflare','access denied','verify you are human')
UA='Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue refresh)'
_tls=threading.local()
class AccessBlocked(RuntimeError): pass

def session():
    s=getattr(_tls,'s',None)
    if s is None:
        s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9'})
        s.mount('https://',requests.adapters.HTTPAdapter(pool_connections=24,pool_maxsize=24,max_retries=0)); _tls.s=s
    return s

def get(url,timeout=20,retries=2):
    last=None
    for a in range(retries+1):
        try:
            r=session().get(url,timeout=timeout); low=(r.text[:12000] or '').lower()
            if r.status_code in (403,429) or any(x in low for x in CHALLENGE): raise AccessBlocked(f'HTTP {r.status_code}/challenge {url}')
            if r.status_code>=500 and a<retries: time.sleep(.5*(a+1)); continue
            r.raise_for_status(); return r
        except AccessBlocked: raise
        except Exception as e:
            last=e
            if a<retries: time.sleep(.5*(a+1)); continue
            raise
    raise last

def clean(x): return re.sub(r'\s+',' ',x or '').strip()
def money(x):
    if not x:return None
    try:return float(x.replace('\u202f','').replace('\u00a0','').replace(' ','').replace(',','.'))
    except:return None

def product_links(html):
    soup=BeautifulSoup(html,'lxml'); out=set()
    for a in soup.find_all('a',href=True):
        href=urljoin(BASE,a['href']).split('#')[0]
        p=urlparse(href)
        if p.netloc.endswith('dentaltix.com') and p.path.startswith('/fr/') and not any(z in p.path for z in ('/blog','/contact','/marques','/manufacturer','/category','/produits-dentaires-pour-les-patients')):
            # Product cards normally expose price/add/options around their links.
            parent=a.parent
            context=clean(parent.get_text(' ',strip=True) if parent else '')
            if '€' in context or 'Voir options' in context or 'Ajouter' in context: out.add(href)
    return out

def discover(max_pages=500,workers=10):
    # Broad top-level listings; pagination is cheap and duplicate URLs are deduped.
    seeds=[]
    for root in START:
        seeds.extend([root if p==0 else root+f'?page={p}' for p in range(max_pages)])
    urls=set(); empty=0
    def one(u):
        r=get(u); return u,product_links(r.text)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(one,u):u for u in seeds}
        for n,f in enumerate(cf.as_completed(futs),1):
            try:
                _,found=f.result(); urls.update(found)
                if found: empty=0
                else: empty+=1
                if n%50==0: print(f'[Dentaltix] découverte {n}/{len(seeds)}: {len(urls)} URLs',flush=True)
            except requests.HTTPError as e:
                if getattr(e.response,'status_code',None)!=404: print('[Dentaltix]',e,flush=True)
            except AccessBlocked:
                for x in futs:x.cancel()
                raise
            except Exception as e: print('[Dentaltix]',e,flush=True)
    return sorted(urls)

def parse(url):
    r=get(url); soup=BeautifulSoup(r.text,'lxml')
    h=soup.find('h1'); name=clean(h.get_text(' ',strip=True) if h else '')
    if not name:return []
    text=clean(soup.get_text(' ',strip=True))
    brand=''
    # Visible pages commonly use "de BRAND" near product heading.
    m=re.search(r'\bde\s+([A-Z0-9][A-Z0-9 .&+\-/]{1,50})\b',text)
    if m:brand=clean(m.group(1))
    crumbs=[clean(x.get_text(' ',strip=True)) for x in soup.select('.breadcrumb a, nav[aria-label*=breadcrumb] a')]
    category=' > '.join(x for x in crumbs if x and x.lower()!='accueil')
    og=soup.find('meta',attrs={'property':'og:image'}); image=urljoin(BASE,og.get('content')) if og and og.get('content') else ''
    if not image:
        im=soup.find('img',src=True); image=urljoin(BASE,im['src']) if im else ''
    captured=datetime.now(timezone.utc).isoformat()
    # Extract offer/variant blocks from structured HTML first.
    rows=[]; seen=set()
    blocks=soup.select('[itemprop="offers"], .product-variation, .variation, .attribute, .product-info')
    if not blocks: blocks=[soup]
    ref_patterns=[re.compile(r'(?:Réf(?:érence)?\.?\s*(?:Dentaltix)?|SKU)\s*[:#]?\s*([A-Za-z0-9._/-]{3,40})',re.I)]
    price_re=re.compile(r'(\d{1,6}(?:[\s\u00a0\u202f]\d{3})*[,.]\d{2})\s*€')
    for b in blocks:
        bt=clean(b.get_text(' ',strip=True)); refs=[]
        for rp in ref_patterns: refs += rp.findall(bt)
        prices=price_re.findall(bt)
        if not refs: continue
        for ref in refs:
            ref=clean(ref)
            if ref.lower() in ('dentaltix','produit','reference','référence') or ref in seen:continue
            seen.add(ref)
            rows.append({'merchant':'Dentaltix','url':url,'name':name,'price':money(prices[-1]) if prices else None,'currency':'EUR','merchant_reference':ref,'manufacturer_reference':'','ean':'','brand':brand,'category':category,'variant':'','packaging':'','image_url':image,'availability':'','captured_at':captured})
    # Fallback family-level offer: useful for discovery/QC even when variant markup differs.
    if not rows:
        prices=price_re.findall(text)
        meta=soup.find('meta',attrs={'itemprop':'sku'})
        ref=clean(meta.get('content')) if meta and meta.get('content') else ''
        rows=[{'merchant':'Dentaltix','url':url,'name':name,'price':money(prices[-1]) if prices else None,'currency':'EUR','merchant_reference':ref,'manufacturer_reference':'','ean':'','brand':brand,'category':category,'variant':'','packaging':'','image_url':image,'availability':'','captured_at':captured}]
    return rows

def collect(urls,workers=10,limit=None):
    if limit:urls=urls[:limit]
    products=[]; errors=[]; blocked=threading.Event(); started=time.time()
    def one(u):
        if blocked.is_set():return []
        try:return parse(u)
        except AccessBlocked:blocked.set();raise
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs={ex.submit(one,u):u for u in urls}
        for n,f in enumerate(cf.as_completed(futs),1):
            u=futs[f]
            try:products.extend(f.result())
            except Exception as e:errors.append({'url':u,'error':str(e)});print('[Dentaltix] ERREUR',u,e,flush=True)
            if n%50==0:
                rate=n/max((time.time()-started)/60,.01);print(f'[Dentaltix] {n}/{len(urls)} — {len(products)} refs — {rate:.0f} pages/min',flush=True)
            if blocked.is_set():
                for x in futs:x.cancel()
                break
    return products,errors

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=10);ap.add_argument('--discover-workers',type=int,default=10);ap.add_argument('--max-pages',type=int,default=500);ap.add_argument('--limit',type=int);ap.add_argument('--urls-file');ap.add_argument('--urls-out',default='backend/snapshot/data/dentaltix_product_urls.json');ap.add_argument('--output',default='backend/snapshot/data/dentaltix_catalog.json');args=ap.parse_args()
    if args.urls_file and Path(args.urls_file).exists():urls=json.loads(Path(args.urls_file).read_text(encoding='utf-8'));print(f'[Dentaltix] {len(urls)} URLs réutilisées',flush=True)
    else:urls=discover(args.max_pages,args.discover_workers)
    Path(args.urls_out).parent.mkdir(parents=True,exist_ok=True);Path(args.urls_out).write_text(json.dumps(urls,ensure_ascii=False,indent=2),encoding='utf-8');print(f'[Dentaltix] découverte terminée: {len(urls)} URLs',flush=True)
    products,errors=collect(urls,args.workers,args.limit)
    payload={'source':'dentaltix_public_fast_v1','captured_at':datetime.now(timezone.utc).isoformat(),'product_pages_discovered':len(urls),'product_pages_attempted':min(len(urls),args.limit) if args.limit else len(urls),'total_products':len(products),'errors':errors,'products':products}
    Path(args.output).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(f'[Dentaltix] TERMINE: {len(products)} refs, {len(errors)} erreurs',flush=True)
    return 2 if any('403' in e['error'] or '429' in e['error'] or 'challenge' in e['error'].lower() for e in errors) else 0
if __name__=='__main__':raise SystemExit(main())
