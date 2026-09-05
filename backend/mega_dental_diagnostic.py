import urllib.robotparser
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT

BASE = "https://www.megadental.fr"

def main():
    robots_url = BASE + "/robots.txt"
    r = requests.get(robots_url, timeout=20, headers={"User-Agent": USER_AGENT})
    print("robots status:", r.status_code)
    print(r.text[:4000])

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    for path in ["/", "/sitemap", "/sitemap/products"]:
        url = BASE + path
        print(path, "custom UA allowed=", rp.can_fetch(USER_AGENT, url), "star allowed=", rp.can_fetch("*", url))

    for path in ["/sitemap", "/sitemap/products"]:
        url = BASE + path
        rr = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"})
        print("\n", path, "status=", rr.status_code, "content-type=", rr.headers.get("content-type"), "bytes=", len(rr.content))
        soup = BeautifulSoup(rr.text, "lxml")
        links = [a.get("href") for a in soup.select("a[href]") if a.get("href")]
        print("links:", len(links))
        for href in links[:80]:
            print(href)

if __name__ == "__main__":
    main()
