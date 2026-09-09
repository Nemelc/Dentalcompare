#!/usr/bin/env python3
"""Lightweight public Mega Dental refresh/probe for DentalCompare.

Reads already-known public Mega Dental product URLs from the existing catalogue
and refreshes only volatile offer data (price / availability). Uses ordinary
public HTTP only. No login, browser automation, CAPTCHA handling or bypass.
Stops on 403/429/challenge responses.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, re, threading, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / 'mega_catalog_visible_test.json'
CHALLENGE = ('captcha','cloudflare','access denied','verify you are human','just a moment')
UA = 'Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue refresh)'
_tls = threading.local()

class AccessBlocked(RuntimeError): pass

def session():
    s=getattr(_tls,'s',None)
    if s is None:
        s=requests.Session()
        s.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9'})
        s.mount('https://', requests.adapters.HTTPAdapter(pool_connections=16,pool_maxsize=16,max_retries=0))
        _tls.s=s
    return s

def get(url, timeout=18, retries=1):
    last=None
    for a in range(retries+1):
        try:
            r=session().get(url,timeout=timeout)
            low=(r.text[:12000] or '').lower()
            if r.status_code in (403,429) or any(x in low for x in CHALLENGE):
                raise AccessBlocked(f'HTTP {r.status_code}/challenge {url}')
            if r.status_code>=500 and a<retries:
                time.sleep(.5); continue
            r.raise_for_status(); return r
        except AccessBlocked: raise
        except Exception as e:
            last=e
            if a<retries: time.sleep(.5); continue
            raise
    raise last

def clean(x): return re.sub(r'\s+',' ',x or '').strip()

def money(x):
    if x is None:return None
    x=str(x).replace('\u202f','').replace('\u00a0','').replace(' ','').replace(',','.')
    m=re.search(r'(\d+(?:\.\d{1,2})?)',x)
    return float(m.group(1)) if m else None

def load_rows(path:Path):
    d=json.loads(path.read_text(encoding='utf-8'))
    if isinstance(d,list): return d
    for k in ('products','items','offers'):
        if isinstance(d.get(k),list): return d[k]
    raise ValueError('Format catalogue Mega non reconnu')

def parse_offer(url):
    r=get(url)
    soup=BeautifulSoup(r.text,'lxml')
    price=None; availability=''
    # Prefer structured data when present.
    for tag in soup.find_all('script',attrs={'type':'application/ld+json'}):
        try:
            data=json.loads(tag.string or tag.get_text() or '{}')
        except Exception:
            continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            obj=stack.pop()
            if isinstance(obj,dict):
                offers=obj.get('offers')
                if isinstance(offers,dict):
                    if price is None: price=money(offers.get('price') or offers.get('lowPrice'))
                    availability=availability or clean(str(offers.get('availability') or '').split('/')[-1])
                elif isinstance(offers,list): stack.extend(offers)
                for v in obj.values():
                    if isinstance(v,(dict,list)): stack.extend(v if isinstance(v,list) else [v])
    text=clean(soup.get_text(' ',strip=True))
    if price is None:
        candidates=re.findall(r'(\d{1,5}(?:[\s\u00a0\u202f]\d{3})*[,.]\d{2})\s*€',text)
        if candidates: price=money(candidates[0])
    if not availability:
        for s in ('En stock','Disponible','Sur commande','En réapprovisionnement','Rupture de stock','Indisponible'):
            if s.lower() in text.lower(): availability=s; break
    return {'url':url,'price':price,'availability':availability,'checked_at':datetime.now(timezone.utc).isoformat(),'http_status':r.status_code}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--catalog',default=str(DEFAULT_CATALOG)); ap.add_argument('--limit',type=int,default=40); ap.add_argument('--workers',type=int,default=6); ap.add_argument('--output',default='backend/snapshot/data/mega_refresh_probe.json'); args=ap.parse_args()
    rows=load_rows(Path(args.catalog))
    urls=[]; seen=set()
    for x in rows:
        u=x.get('url') or x.get('source_url') or x.get('product_url')
        if u and u not in seen:
            seen.add(u); urls.append(u)
        if len(urls)>=args.limit: break
    print(f'[Mega] {len(urls)} URLs connues sélectionnées',flush=True)
    out=[]; errors=[]; blocked=threading.Event()
    def one(u):
        if blocked.is_set(): return None
        try:return parse_offer(u)
        except AccessBlocked:
            blocked.set(); raise
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs={ex.submit(one,u):u for u in urls}
        for n,f in enumerate(cf.as_completed(futs),1):
            u=futs[f]
            try:
                z=f.result()
                if z: out.append(z)
            except Exception as e:
                errors.append({'url':u,'error':str(e)})
                print('[Mega] ERREUR',u,e,flush=True)
            if blocked.is_set():
                for x in futs:x.cancel()
                break
            if n%10==0: print(f'[Mega] {n}/{len(urls)} testées',flush=True)
    payload={'source':'mega_public_weekly_probe_v1','checked_at':datetime.now(timezone.utc).isoformat(),'requested':len(urls),'success':len(out),'with_price':sum(isinstance(x.get('price'),(int,float)) and x['price']>0 for x in out),'with_availability':sum(bool(x.get('availability')) for x in out),'errors':errors,'offers':out}
    p=Path(args.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[Mega] RESULTAT',json.dumps({k:payload[k] for k in ('requested','success','with_price','with_availability')},ensure_ascii=False),flush=True)
    return 2 if blocked.is_set() else 0

if __name__=='__main__': raise SystemExit(main())
