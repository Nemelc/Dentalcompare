#!/usr/bin/env python3
"""GACD Playwright fast collector - fresh discovery, then product extraction.
No legacy GACD data is reused. Normal browser navigation only; stops on challenge.
"""
import asyncio, csv, json, re, sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from datetime import datetime, timezone
from playwright.async_api import async_playwright

BASE='https://www.gacd.fr/'
ORIGIN='https://www.gacd.fr'
DATA=Path(__file__).parent/'data'
DB=DATA/'gacd_playwright_fast.sqlite3'
PRODUCT_RE=re.compile(r'Réf\.?\s*GACD\s*:',re.I)
CHALLENGE=re.compile(r'captcha|verify you are human|vérifiez que vous êtes humain|access denied|security check|checking your browser|just a moment',re.I)
SKIP=re.compile(r'/(customer|checkout|cart|catalogsearch|search|contact|mentions|conditions|privacy|cookies|newsletter|login|account|wishlist)(/|$)',re.I)

def now(): return datetime.now(timezone.utc).isoformat()
def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def norm(h,b):
    if not h:return ''
    u,_=urldefrag(urljoin(b,h)); p=urlparse(u)
    if p.netloc.lower()!='www.gacd.fr' or SKIP.search(p.path):return ''
    return u

def ref_ok(s):
    s=clean(s).strip('|:;,.()[]{}')
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{1,60}',s,re.I):return ''
    return '' if s.lower() in {'nom','name','r','ref','reference','référence'} else s

def price(s):
    m=re.search(r'([0-9][0-9\s\u00a0\u202f]*[,.][0-9]{2})\s*€',s)
    if not m:return None
    try:return float(re.sub(r'[\s\u00a0\u202f]','',m.group(1)).replace(',','.'))
    except:return None

class Store:
    def __init__(self):
        DATA.mkdir(parents=True,exist_ok=True); self.c=sqlite3.connect(DB)
        self.c.execute('CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, kind TEXT, status TEXT DEFAULT "pending")')
        self.c.execute('CREATE TABLE IF NOT EXISTS products(ref TEXT PRIMARY KEY,url TEXT,mfr TEXT,name TEXT,brand TEXT,category TEXT,price REAL,availability TEXT,image TEXT,captured TEXT)'); self.c.commit()
    def reset(self): self.c.execute('DELETE FROM pages'); self.c.execute('DELETE FROM products'); self.c.commit()
    def add(self,urls,kind): self.c.executemany('INSERT OR IGNORE INTO pages(url,kind) VALUES(?,?)',[(u,kind) for u in urls if u]); self.c.commit()
    def pending(self,kind): return [x[0] for x in self.c.execute('SELECT url FROM pages WHERE kind=? AND status="pending"',(kind,))]
    def done(self,u): self.c.execute('UPDATE pages SET status="done" WHERE url=?',(u,)); self.c.commit()
    def save(self,rows):
        self.c.executemany('INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ref) DO UPDATE SET url=excluded.url,mfr=COALESCE(excluded.mfr,products.mfr),name=excluded.name,brand=COALESCE(excluded.brand,products.brand),category=COALESCE(excluded.category,products.category),price=COALESCE(excluded.price,products.price),availability=COALESCE(excluded.availability,products.availability),image=COALESCE(excluded.image,products.image),captured=excluded.captured',rows); self.c.commit()
    def export(self):
        cols=['merchant_reference','source_url','manufacturer_reference','name','brand','category','price_eur','availability','image_url','captured_at']; rows=[dict(zip(cols,r)) for r in self.c.execute('SELECT ref,url,mfr,name,brand,category,price,availability,image,captured FROM products ORDER BY ref')]
        (DATA/'gacd_playwright_catalog.json').write_text(json.dumps({'source':'gacd_playwright_fast_fresh_v2','captured_at':now(),'total_products':len(rows),'products':[{'merchant':'GACD',**r} for r in rows]},ensure_ascii=False,indent=2),encoding='utf-8')
        with (DATA/'gacd_playwright_catalog.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=['merchant']+cols);w.writeheader();[w.writerow({'merchant':'GACD',**r}) for r in rows]
        print(f'[GACD FAST] Export: {len(rows)} références')

async def challenge(page):
    try:return bool(CHALLENGE.search((await page.title())+' '+(await page.locator('body').inner_text())[:4000]))
    except:return False

async def links(page):
    hrefs=await page.locator('a[href]').evaluate_all("els=>els.map(e=>e.href).filter(Boolean)")
    return {norm(x,page.url) for x in hrefs if norm(x,page.url)}

async def product_links(page):
    sels='.product-item-link[href],a.product-item-link[href],.products a[href],.product-items a[href],[class*=product] a[href]'
    try: hrefs=await page.locator(sels).evaluate_all("els=>els.map(e=>e.href).filter(Boolean)")
    except: hrefs=[]
    return {norm(x,page.url) for x in hrefs if norm(x,page.url)}

async def parse_product(page,url):
    body=await page.locator('body').inner_text()
    if not PRODUCT_RE.search(body):return []
    try:h1=clean(await page.locator('h1').first.inner_text())
    except:h1='Produit GACD'
    try:image=await page.locator("meta[property='og:image']").first.get_attribute('content')
    except:image=None
    brand=None
    for sel in ("[itemprop=brand]",'.product-brand','.brand','[class*=manufacturer]'):
        try:
            t=clean(await page.locator(sel).first.inner_text(timeout=700))
            if t:brand=t;break
        except:pass
    try:
        cr=[clean(x) for x in await page.locator('.breadcrumbs a,.breadcrumbs strong,.breadcrumb a,.breadcrumb li').all_inner_texts()]; category=' > '.join(dict.fromkeys(x for x in cr if x and x.lower() not in {'accueil','home'})) or None
    except:category=None
    ms=list(PRODUCT_RE.finditer(body)); out=[];seen=set()
    for i,m in enumerate(ms):
        seg=body[m.end():(ms[i+1].start() if i+1<len(ms) else min(len(body),m.end()+3500))]; ls=[clean(x) for x in seg.splitlines() if clean(x)]
        if not ls:continue
        ref=ref_ok(ls[0].split()[0])
        if not ref or ref in seen:continue
        seen.add(ref); mm=re.search(r'Réf\.?\s*Fabricant\s*:\s*([^\s\r\n|]+)',seg,re.I); mfr=ref_ok(mm.group(1)) if mm else None
        sm=re.search(r'\b(En stock|Sur commande|En réapprovisionnement(?:\s+Disponible sous \d+ jours)?|Indisponible|Arrêté|Rupture de stock)\b',seg,re.I); av=clean(sm.group(1)) if sm else None
        variant=None
        for x in ls[1:]:
            if re.search(r'Réf\.?\s*Fabricant',x,re.I):break
            if not re.match(r'^(En stock|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture|Ajouter|Prix|Qté|Quantité|[0-9\s,.]+\s*€)',x,re.I) and len(x)>2: variant=x;break
        out.append((ref,url,mfr,variant or h1,brand,category,price(seg),av,urljoin(url,image) if image else None,now()))
    return out

async def main():
    s=Store(); s.reset(); print('[GACD FAST] Nouveau catalogue: aucune ancienne donnée réutilisée.')
    seeds=[BASE,ORIGIN+'/catalogue.html',ORIGIN+'/plan-du-site.html',ORIGIN+'/sitemap.html',ORIGIN+'/produits.html']; s.add(seeds,'listing')
    async with async_playwright() as p:
        ctx=await p.chromium.launch_persistent_context(str(DATA/'browser-profile-fast'),headless=False,locale='fr-FR',viewport={'width':1400,'height':950})
        page=ctx.pages[0] if ctx.pages else await ctx.new_page(); page.set_default_timeout(15000)
        # Phase 1: listing/category discovery only. Product-like links are queued but not recursively crawled.
        seen_listing=0
        while True:
            q=s.pending('listing')
            if not q or seen_listing>=1200:break
            u=q[0]; seen_listing+=1; print(f'[GACD FAST] Découverte {seen_listing} | {u}')
            try:
                r=await page.goto(u,wait_until='domcontentloaded',timeout=25000)
                if (r and r.status in (403,429)) or await challenge(page): print('[GACD FAST] Protection détectée. Arrêt propre.');break
                pls=await product_links(page); s.add(pls,'product')
                # Only expand links that look like catalogue/category/pagination pages.
                alls=await links(page); listing={x for x in alls if ('?p=' in x or '?page=' in x or re.search(r'/(catalogue|produits|dentaire|materiel|consommable|instrument|hygiene|endo|implant|orthodont|prothese|anesth|empreinte|amenagement)',urlparse(x).path,re.I)) and x not in pls}
                s.add(listing,'listing'); s.done(u)
            except Exception as e: print('[GACD FAST] Erreur découverte:',type(e).__name__,u);s.done(u)
            await asyncio.sleep(.25)
        products=s.pending('product'); print(f'[GACD FAST] Découverte terminée: {len(products)} fiches produit à analyser.')
        # Phase 2: product pages only.
        for i,u in enumerate(products,1):
            print(f'[GACD FAST] Produit {i}/{len(products)} | {u}')
            try:
                r=await page.goto(u,wait_until='domcontentloaded',timeout=25000)
                if (r and r.status in (403,429)) or await challenge(page): print('[GACD FAST] Protection détectée. Arrêt propre.');break
                rows=await parse_product(page,u)
                if rows:s.save(rows); print(f'[GACD FAST] +{len(rows)} référence(s)')
                s.done(u)
            except Exception as e: print('[GACD FAST] Erreur produit:',type(e).__name__,u)
            if i%25==0:s.export()
            await asyncio.sleep(.35)
        s.export(); await ctx.close()

if __name__=='__main__': asyncio.run(main())
