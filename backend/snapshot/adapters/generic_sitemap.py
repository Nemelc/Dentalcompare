import urllib.robotparser
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

UA = "DentalCompareCatalogSnapshot/1.0"
TIMEOUT = 20

def robots_allows(url):
    u=urlparse(url); rp=urllib.robotparser.RobotFileParser(); rp.set_url(f"{u.scheme}://{u.netloc}/robots.txt")
    try:
        rp.read(); return rp.can_fetch(UA,url)
    except Exception:
        return False

def sitemap_urls(sitemap_url):
    if not robots_allows(sitemap_url): raise RuntimeError("robots.txt n'autorise pas cette collecte automatique.")
    r=requests.get(sitemap_url,headers={"User-Agent":UA},timeout=TIMEOUT); r.raise_for_status(); soup=BeautifulSoup(r.text,"xml")
    locs=[x.get_text(strip=True) for x in soup.find_all("loc")]
    if any(u.endswith(".xml") for u in locs):
        out=[]
        for u in locs:
            if u.endswith(".xml"): out.extend(sitemap_urls(u))
        return out
    return locs

def fetch_html(url):
    if not robots_allows(url): return None
    r=requests.get(url,headers={"User-Agent":UA,"Accept-Language":"fr-FR,fr;q=0.9"},timeout=TIMEOUT)
    return r.text if r.status_code==200 else None
