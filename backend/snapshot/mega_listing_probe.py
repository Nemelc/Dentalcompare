#!/usr/bin/env python3
from __future__ import annotations
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE='https://www.megadental.fr'
URLS=[
 BASE+'/sitemap/products',
 BASE+'/shopping.html',
 BASE+'/offres-fabricants.html',
 BASE+'/produits-liberte.html',
 BASE+'/destockage.html',
 BASE+'/prothese.html',
 BASE+'/brands/micro-mega',
]
CHALLENGE=('captcha','cloudflare','access denied','verify you are human','just a moment')
UA='Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue refresh)'
PRICE_RE=re.compile(r'(\d{1,6}(?:[\s\u00a0\u202f]\d{3})*[,.]\d{2})\s*€')
REF_RE=re.compile(r'Réf\.\s*([A-Za-z0-9._/-]{3,40})',re.I)

def clean(x):return re.sub(r'\s+',' ',x or '').strip()
def money(x):
    try:return float(x.replace('\u202f','').replace('\u00a0','').replace(' ','').replace(',','.'))
    except:return None

def get(url):
    r=requests.get(url,headers={'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9'},timeout=20)
    low=(r.text[:12000] or '').lower()
    if r.status_code in (403,429) or any(x in low for x in CHALLENGE):
        raise RuntimeError(f'BLOCKED {r.status_code} {url}')
    r.raise_for_status();return r

def extract(url,html):
    soup=BeautifulSoup(html,'lxml'); rows=[]; seen=set()
    for a in soup.find_all('a',href=True):
        href=urljoin(BASE,a['href']).split('#')[0]
        if not href.startswith(BASE):continue
        parent=a
        for _ in range(4):
            parent=parent.parent if parent and parent.parent else parent
            txt=clean(parent.get_text(' ',strip=True) if parent else '')
            if '€' in txt:break
        txt=clean(parent.get_text(' ',strip=True) if parent else '')
        ps=PRICE_RE.findall(txt)
        if not ps:continue
        if href in seen:continue
        seen.add(href)
        refm=REF_RE.search(txt)
        rows.append({'url':href,'text':txt[:300],'merchant_reference':refm.group(1) if refm else '', 'price':money(ps[0]), 'source_listing':url})
    return rows

def main():
    out=[];errors=[]
    for u in URLS:
        try:
            r=get(u); rows=extract(u,r.text); out.extend(rows)
            print(f'[Mega listing] {u}: HTTP {r.status_code}, {len(rows)} offres',flush=True)
        except Exception as e:
            errors.append({'url':u,'error':str(e)});print('[Mega listing] ERREUR',u,e,flush=True)
    payload={'checked_at':datetime.now(timezone.utc).isoformat(),'pages':len(URLS),'offers':out,'errors':errors,'with_ref':sum(bool(x['merchant_reference']) for x in out),'with_price':sum(bool(x['price']) for x in out)}
    Path('/tmp/mega_listing_probe.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[Mega listing] RESULTAT',json.dumps({'offers':len(out),'with_ref':payload['with_ref'],'errors':len(errors)},ensure_ascii=False),flush=True)
    return 0 if out else 1
if __name__=='__main__':raise SystemExit(main())
