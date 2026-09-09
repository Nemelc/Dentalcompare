#!/usr/bin/env python3
"""Probe public Doctor AI catalogue endpoints without bypassing access controls."""
import json, requests
from bs4 import BeautifulSoup

URLS=[
 'https://www.doctor-ai.fr/',
 'https://www.doctor-ai.fr/sitemap',
 'https://www.doctor-ai.fr/robots.txt',
 'https://www.doctor-ai.fr/sitemap.xml',
 'https://www.doctor-ai.fr/usage-unique-2.html',
 'https://www.doctor-ai.fr/specialites-1/implantologie-1.html',
 'https://www.doctor-ai.fr/specialites-1/implantologie-1.html?p=2',
]
CHALLENGE=('captcha','cloudflare','access denied','verify you are human','human verification','just a moment')
S=requests.Session();S.headers.update({'User-Agent':'Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue probe)','Accept-Language':'fr-FR,fr;q=0.9'})
for u in URLS:
    rec={'url':u}
    try:
        r=S.get(u,timeout=20,allow_redirects=True);txt=r.text or '';low=txt[:12000].lower();soup=BeautifulSoup(txt,'lxml')
        rec.update(status=r.status_code,final_url=r.url,length=len(txt),challenge=any(x in low for x in CHALLENGE),title=soup.title.get_text(' ',strip=True)[:160] if soup.title else '',product_cards=len(soup.select('.product-item, .product-item-info, li.product-item')),refs=len(soup.find_all(string=lambda x:x and 'Réf.' in x)),prices=txt.count('€'))
    except Exception as e:rec['error']=repr(e)
    print(json.dumps(rec,ensure_ascii=False),flush=True)
