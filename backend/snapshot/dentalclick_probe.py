#!/usr/bin/env python3
import json, requests
from bs4 import BeautifulSoup

CANDIDATES=[
 'https://www.dentalclick.com/',
 'https://dentalclick.com/',
 'https://www.dentalclick.fr/',
 'https://dentalclick.fr/',
 'https://www.dentalclick.fr/robots.txt',
 'https://www.dentalclick.fr/sitemap.xml',
 'https://www.dentalclick.fr/sitemap_index.xml',
 'https://www.dentalclick.com/robots.txt',
 'https://www.dentalclick.com/sitemap.xml',
]
UA='Mozilla/5.0 (compatible; DentalCompareCatalog/1.0; public catalogue probe)'

def main():
    out=[]
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'fr-FR,fr;q=0.9,en;q=0.7'})
    for u in CANDIDATES:
        rec={'url':u}
        try:
            r=s.get(u,timeout=20,allow_redirects=True)
            rec.update(status=r.status_code,final_url=r.url,length=len(r.text or ''))
            txt=(r.text or '')[:300000]
            low=txt.lower()
            rec['challenge']=any(x in low for x in ('captcha','cloudflare','verify you are human','access denied','human verification'))
            soup=BeautifulSoup(txt,'lxml')
            rec['title']=(soup.title.get_text(' ',strip=True) if soup.title else '')[:200]
            rec['sample']=txt[:500].replace('\n',' ')
            rec['links']=[a.get('href') for a in soup.find_all('a',href=True)[:30]]
        except Exception as e:
            rec['error']=repr(e)
        out.append(rec)
        print(json.dumps(rec,ensure_ascii=False),flush=True)
    open('/tmp/dentalclick_probe.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
