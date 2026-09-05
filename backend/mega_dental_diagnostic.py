import urllib.robotparser
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT

BASE = "https://www.megadental.fr"
SITEMAP = BASE + "/media/sitemap/sitemap_14.xml"

def main():
    robots_url = BASE + "/robots.txt"
    r = requests.get(robots_url, timeout=20, headers={"User-Agent": USER_AGENT})
    print("robots status:", r.status_code)
    print(r.text[:4000])

    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    for url in [BASE + "/", BASE + "/sitemap", BASE + "/sitemap/products", SITEMAP]:
        print(url, "custom UA allowed=", rp.can_fetch(USER_AGENT, url), "star allowed=", rp.can_fetch("*", url))

    print("\n--- SITEMAP XML DECLARE DANS ROBOTS.TXT ---")
    rr = requests.get(
        SITEMAP,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        },
    )
    print("sitemap status=", rr.status_code)
    print("content-type=", rr.headers.get("content-type"))
    print("bytes=", len(rr.content))
    print("final url=", rr.url)
    print("first 1000 chars:")
    print(rr.text[:1000])

    soup = BeautifulSoup(rr.text, "xml")
    locs = [x.get_text(strip=True) for x in soup.find_all("loc")]
    print("loc count=", len(locs))
    for loc in locs[:40]:
        print("LOC", loc)

    if rr.status_code != 200:
        print("Sitemap non accessible depuis GitHub Actions.")
    elif not locs:
        print("Sitemap accessible mais aucun <loc> reconnu.")

if __name__ == "__main__":
    main()
