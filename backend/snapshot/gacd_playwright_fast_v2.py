#!/usr/bin/env python3
"""DentalCompare - GACD Playwright fast v2.
Fresh crawl only. Normal browser navigation; no CAPTCHA/WAF bypass.
Phase 1 discovers categories/listings and queues true product links.
Phase 2 opens only product pages and extracts GACD variants.
"""
import asyncio, csv, json, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag
from playwright.async_api import async_playwright

BASE='https://www.gacd.fr/'
ORIGIN='https://www.gacd.fr'
DATA=Path(__file__).parent/'data'
DB=DATA/'gacd_playwright_fast_v2.sqlite3'
PRODUCT_MARKER=re.compile(r'(?:Réf\.?|Référence)\s*GACD\s*:',re.I)
CHALLENGE=re.compile(r'captcha|verify you are human|vérifiez que vous êtes humain|access denied|security check|checking your browser|just a moment',re.I)
SKIP=re.compile(r'/(customer|checkout|cart|catalogsearch|search|contact|mentions|conditions|privacy|cookies|newsletter|login|account|wishlist)(/|$)',re.I)
PRODUCT_SELECTORS=(
    'a.product-item-link[href]',
    '.product-item-info a.product-item-link[href]',
    'li.product-item a.product-item-link[href]',
    '.products-grid a.product-item-link[href]',
    '[data-container="product-grid"] a.product-item-link[href]',
)
CATEGORY_SELECTORS=(
    '.navigation a[href]',
    '.nav-sections a[href]',
    '.categories-menu a[href]',
    '.sitemap a[href]',
    '.site-map a[href]',
    '.pages a[href]',
    'a.action.next[href]',
)

def now(): return datetime.now(timezone.utc).isoformat()
def clean(v): return re.sub(r'\s+',' ','' if v is None else str(v)).strip()
def normalize(href,base):
    if not href:return ''
    u,_=urldefrag(urljoin(base,href)); p=urlparse(u)
    if p.scheme not in ('http','https') or p.netloc.lower()!='www.gacd.fr' or SKIP.search(p.path):return ''
    return u

def valid_ref(v):
    v=clean(v).strip('|:;,.()[]{}')
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/\-]{1,60}',v,re.I):return ''
    return '' if v.lower() in {'nom','name','r','ref','reference','référence'} else v

def parse_price(text):
    m=re.search(r'([0-9][0-9\s\u00a0\u202f]*[,.][0-9]{2})\s*€',text)
    if not m:return None
    try:return float(re.sub(r'[\s\u00a0\u202f]','',m.group(1)).replace(',','.'))
    except:return None

class Store:
    def __init__(self):
        DATA.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(DB)
        self.db.execute('CREATE TABLE IF NOT EXISTS queue(url TEXT PRIMARY KEY,kind TEXT,status TEXT DEFAULT "pending")')
        self.db.execute('CREATE TABLE IF NOT EXISTS products(ref TEXT PRIMARY KEY,url TEXT,mfr TEXT,name TEXT,brand TEXT,category TEXT,price REAL,availability TEXT,image TEXT,captured TEXT)')
        self.db.commit()
    def reset(self):
        self.db.execute('DELETE FROM queue');self.db.execute('DELETE FROM products');self.db.commit()
    def add(self,urls,kind):
        rows=[(u,kind) for u in urls if u]
        self.db.executemany('INSERT OR IGNORE INTO queue(url,kind) VALUES(?,?)',rows);self.db.commit()
    def next(self,kind):
        r=self.db.execute('SELECT url FROM queue WHERE kind=? AND status="pending" ORDER BY rowid LIMIT 1',(kind,)).fetchone();return r[0] if r else None
    def done(self,u):self.db.execute('UPDATE queue SET status="done" WHERE url=?',(u,));self.db.commit()
    def save(self,rows):
        self.db.executemany('''INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ref) DO UPDATE SET url=excluded.url,mfr=COALESCE(excluded.mfr,products.mfr),name=excluded.name,brand=COALESCE(excluded.brand,products.brand),category=COALESCE(excluded.category,products.category),price=COALESCE(excluded.price,products.price),availability=COALESCE(excluded.availability,products.availability),image=COALESCE(excluded.image,products.image),captured=excluded.captured''',rows);self.db.commit()
    def counts(self):
        q=dict(self.db.execute('SELECT kind||":"||status,COUNT(*) FROM queue GROUP BY kind,status').fetchall());p=self.db.execute('SELECT COUNT(*) FROM products').fetchone()[0];return q,p
    def export(self):
        cols=['merchant_reference','source_url','manufacturer_reference','name','brand','category','price_eur','availability','image_url','captured_at']
        rows=[dict(zip(cols,r)) for r in self.db.execute('SELECT ref,url,mfr,name,brand,category,price,availability,image,captured FROM products ORDER BY ref')]
        payload={'source':'gacd_playwright_fast_fresh_v2','captured_at':now(),'total_products':len(rows),'products':[{'merchant':'GACD',**r} for r in rows]}
        (DATA/'gacd_playwright_catalog.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        with (DATA/'gacd_playwright_catalog.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['merchant']+cols);w.writeheader();[w.writerow({'merchant':'GACD',**r}) for r in rows]
        print(f'[GACD V2] Export: {len(rows)} références',flush=True)

async def is_challenge(page):
    try:return bool(CHALLENGE.search((await page.title())+' '+(await page.locator('body').inner_text(timeout=5000))[:5000]))
    except:return False

async def hrefs(page,selectors):
    out=set()
    for sel in selectors:
        try:
            xs=await page.locator(sel).evaluate_all("els=>els.map(e=>e.href||e.getAttribute('href')).filter(Boolean)")
            for x in xs:
                u=normalize(x,page.url)
                if u:out.add(u)
        except:pass
    return out

def likely_category(u):
    p=urlparse(u); path=p.path.lower()
    if re.search(r'/article-\d+-',path):return False
    if any(x in path for x in ['/nos-marques/','/marques/','/offre-gacd/']):return False
    if p.query and not re.search(r'(^|&)(p|page)=\d+',p.query):return False
    return path.endswith('.html') or path.endswith('/') or ('?p=' in u or '?page=' in u)

async def get_body(page):
    try:
        await page.wait_for_timeout(650)
        return await page.locator('body').inner_text(timeout=10000)
    except:return ''

async def parse_product(page,url,body):
    if not PRODUCT_MARKER.search(body):return []
    try:h1=clean(await page.locator('h1').first.inner_text(timeout=2000))
    except:h1='Produit GACD'
    image=None
    for sel,attr in (("meta[property='og:image']",'content'),('.gallery-placeholder img','src'),("img[itemprop='image']",'src')):
        try:
            x=await page.locator(sel).first.get_attribute(attr,timeout=800)
            if x:image=urljoin(url,x);break
        except:pass
    brand=None
    for sel in ("[itemprop='brand']",'.product-brand','.brand','[class*=manufacturer]'):
        try:
            x=clean(await page.locator(sel).first.inner_text(timeout=800))
            if x:brand=x;break
        except:pass
    try:
        crumbs=[clean(x) for x in await page.locator('.breadcrumbs a,.breadcrumbs strong,.breadcrumb a,.breadcrumb li').all_inner_texts()]
        category=' > '.join(dict.fromkeys(x for x in crumbs if x and x.lower() not in {'accueil','home'})) or None
    except:category=None
    ms=list(PRODUCT_MARKER.finditer(body)); rows=[];seen=set()
    for i,m in enumerate(ms):
        seg=body[m.end():(ms[i+1].start() if i+1<len(ms) else min(len(body),m.end()+4500))]
        lines=[clean(x) for x in seg.splitlines() if clean(x)]
        if not lines:continue
        ref=''
        for candidate in lines[:3]:
            token=candidate.split()[0] if candidate.split() else ''
            ref=valid_ref(token)
            if ref:break
        if not ref or ref in seen:continue
        seen.add(ref)
        mm=re.search(r'Réf\.?\s*Fabricant\s*:\s*([^\r\n|]+)',seg,re.I)
        mfr=valid_ref(mm.group(1).split()[0]) if mm and mm.group(1).strip() else None
        sm=re.search(r'\b(En stock|Sur commande|En réapprovisionnement(?:\s+Disponible sous \d+ jours)?|Indisponible|Arrêté|Rupture de stock)\b',seg,re.I)
        av=clean(sm.group(1)) if sm else None
        name=h1
        for line in lines[1:8]:
            if re.search(r'Réf\.?\s*Fabricant',line,re.I):continue
            if re.match(r'^(En stock|Sur commande|En réapprovisionnement|Indisponible|Arrêté|Rupture|Ajouter|Prix|Qté|Quantité|[0-9\s,.]+\s*€)',line,re.I):continue
            if len(line)>3:name=line;break
        rows.append((ref,url,mfr,name,brand,category,parse_price(seg),av,image,now()))
    return rows

async def main():
    s=Store();s.reset();print('[GACD V2] Nouveau départ à zéro.',flush=True)
    seeds={BASE,ORIGIN+'/catalogue.html',ORIGIN+'/plan-du-site.html',ORIGIN+'/sitemap.html',ORIGIN+'/produits.html'};s.add(seeds,'listing')
    async with async_playwright() as p:
        ctx=await p.chromium.launch_persistent_context(str(DATA/'browser-profile-v2'),headless=False,locale='fr-FR',viewport={'width':1400,'height':950})
        page=ctx.pages[0] if ctx.pages else await ctx.new_page();page.set_default_timeout(15000)
        discovered=0
        while discovered<900:
            u=s.next('listing')
            if not u:break
            discovered+=1;print(f'[GACD V2] Découverte {discovered} | {u}',flush=True)
            try:
                r=await page.goto(u,wait_until='domcontentloaded',timeout=25000)
                if (r and r.status in (403,429)) or await is_challenge(page):print('[GACD V2] Protection détectée. Arrêt propre.',flush=True);break
                body=await get_body(page)
                if PRODUCT_MARKER.search(body):
                    s.add({u},'product');s.done(u);continue
                pls=await hrefs(page,PRODUCT_SELECTORS);s.add(pls,'product')
                cats=await hrefs(page,CATEGORY_SELECTORS)
                # On ajoute les catégories/paginations uniquement, jamais les liens produit génériques.
                s.add({x for x in cats if x not in pls and likely_category(x)},'listing')
                # Le plan du site contient parfois des catégories hors sélecteurs dédiés.
                if 'plan-du-site' in u or 'sitemap' in u or u==BASE:
                    try:
                        allh=await page.locator('a[href]').evaluate_all("els=>els.map(e=>e.href).filter(Boolean)")
                        s.add({normalize(x,u) for x in allh if normalize(x,u) and likely_category(normalize(x,u))},'listing')
                    except:pass
                s.done(u)
            except Exception as e:
                print(f'[GACD V2] Erreur découverte {type(e).__name__}: {u}',flush=True);s.done(u)
            await asyncio.sleep(.2)
        q,_=s.counts(); total_products=len(s.db.execute('SELECT url FROM queue WHERE kind="product"').fetchall())
        print(f'[GACD V2] Découverte terminée: {total_products} fiches produit uniques.',flush=True)
        i=0
        while True:
            u=s.next('product')
            if not u:break
            i+=1;print(f'[GACD V2] Produit {i}/{total_products} | {u}',flush=True)
            try:
                r=await page.goto(u,wait_until='domcontentloaded',timeout=25000)
                if (r and r.status in (403,429)) or await is_challenge(page):print('[GACD V2] Protection détectée. Arrêt propre.',flush=True);break
                body=await get_body(page);rows=await parse_product(page,u,body)
                if rows:s.save(rows);print(f'[GACD V2] +{len(rows)} référence(s)',flush=True)
                else:print('[GACD V2] 0 référence sur cette page',flush=True)
                s.done(u)
            except Exception as e:print(f'[GACD V2] Erreur produit {type(e).__name__}: {u}',flush=True)
            if i%25==0:s.export()
            await asyncio.sleep(.3)
        s.export();await ctx.close()

if __name__=='__main__':asyncio.run(main())
