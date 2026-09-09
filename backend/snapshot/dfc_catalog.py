#!/usr/bin/env python3
"""Collecte le catalogue public DFC Instruments sans contournement de protection."""
import argparse,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

BASE='https://www.dfc-instruments.fr'
UA='DentalCompare catalogue indexer (+public product data)'
S=requests.Session(); S.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9'})
CHALLENGE=('verify you are human','captcha','access denied','just a moment','checking your browser')

def get(url):
    r=S.get(url,timeout=25)
    low=r.text[:5000].lower()
    if r.status_code in (403,429) or any(x in low for x in CHALLENGE):
        raise RuntimeError(f'ACCESS_BLOCKED {r.status_code} {url}')
    r.raise_for_status(); return r

def clean(x): return re.sub(r'\s+',' ',x or '').strip()
def price(s):
    m=re.search(r'([0-9][0-9\s]*[,.][0-9]{2})\s*€\s*HT',s,re.I)
    if not m: return None
    return float(m.group(1).replace(' ','').replace(',','.'))
def refs(s):
    m=re.search(r'R[ÉE]F\s*:?\s*([A-Z0-9._/-]+)',s,re.I)
    return m.group(1).strip() if m else None

def discover():
    seeds=[BASE+'/',BASE+'/nos-produits-27',BASE+'/plan-du-site']
    cats=set()
    for u in seeds:
        soup=BeautifulSoup(get(u).text,'lxml')
        for a in soup.select('a[href]'):
            href=urljoin(BASE,a.get('href'))
            if urlparse(href).netloc=='www.dfc-instruments.fr' and re.search(r'-\d+(?:\?.*)?$',urlparse(href).path): cats.add(href.split('?')[0])
    products=set(); checked=set()
    queue=list(cats)
    while queue:
        u=queue.pop();
        if u in checked: continue
        checked.add(u)
        soup=BeautifulSoup(get(u).text,'lxml')
        for a in soup.select('a[href]'):
            href=urljoin(BASE,a.get('href')).split('#')[0]
            if urlparse(href).netloc!='www.dfc-instruments.fr': continue
            txt=clean(a.get_text(' ',strip=True))
            path=urlparse(href).path
            if re.search(r'-\d+$',path) and ('voir le produit' in txt.lower() or a.find_parent(class_=re.compile('product',re.I))): products.add(href.split('?')[0])
        # Prestashop pagination
        nxt=soup.select_one('a.next[href],a[rel="next"][href]')
        if nxt:
            nu=urljoin(BASE,nxt.get('href'))
            if nu not in checked: queue.append(nu)
    return sorted(products)

def parse(url):
    soup=BeautifulSoup(get(url).text,'lxml')
    h1=clean(soup.select_one('h1').get_text(' ',strip=True) if soup.select_one('h1') else '')
    text=clean(soup.get_text(' ',strip=True))
    ref=refs(h1) or refs(text)
    p=price(text)
    img=''
    og=soup.select_one('meta[property="og:image"]')
    if og: img=urljoin(BASE,og.get('content',''))
    if not img:
        im=soup.select_one('.product-cover img,img[itemprop="image"]')
        if im: img=urljoin(BASE,im.get('src') or im.get('data-src') or '')
    brand=''
    b=soup.select_one('[itemprop="brand"],.product-manufacturer,.brand')
    if b: brand=clean(b.get_text(' ',strip=True))
    cat=' > '.join(clean(x.get_text(' ',strip=True)) for x in soup.select('.breadcrumb li') if clean(x.get_text(' ',strip=True)))
    availability='En stock' if re.search(r'\bEn stock\b',text,re.I) else ('Stock épuisé' if re.search(r'Stock épuisé',text,re.I) else None)
    return {'merchant':'DFC Instruments','merchant_reference':ref,'manufacturer_reference':None,'ean':None,'name':re.sub(r'\s*-\s*R[ÉE]F\s*:?.*$','',h1,flags=re.I).strip() or h1,'brand':brand or None,'category':cat or None,'variant':None,'packaging':None,'price_eur':p,'availability':availability,'image_url':img or None,'source_url':url,'captured_at':datetime.now(timezone.utc).isoformat()}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default='backend/snapshot/data/dfc_catalog.json'); ap.add_argument('--workers',type=int,default=6); args=ap.parse_args()
    urls=discover(); print(f'[DFC] {len(urls)} pages produit découvertes')
    rows=[]; errors=[]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fs={ex.submit(parse,u):u for u in urls}
        for i,f in enumerate(as_completed(fs),1):
            try:
                x=f.result()
                if x['name'] and x['merchant_reference']: rows.append(x)
            except Exception as e:
                errors.append({'url':fs[f],'error':str(e)})
                if 'ACCESS_BLOCKED' in str(e):
                    print('[DFC] protection détectée, arrêt prudent'); break
            if i%50==0: print(f'[DFC] {i}/{len(urls)} — {len(rows)} références')
    # dédoublonnage référence marchand
    out={}
    for x in rows: out[x['merchant_reference']]=x
    payload={'source':'dfc_instruments_public_v1','captured_at':datetime.now(timezone.utc).isoformat(),'product_pages':len(urls),'total_products':len(out),'errors':errors,'products':list(out.values())}
    import os; os.makedirs(os.path.dirname(args.output),exist_ok=True)
    with open(args.output,'w',encoding='utf-8') as f: json.dump(payload,f,ensure_ascii=False,indent=2)
    print(f'[DFC] terminé: {len(out)} références, {len(errors)} erreurs')
    return 0 if out else 1
if __name__=='__main__': raise SystemExit(main())
