import json
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, REQUEST_DELAY_SECONDS, USER_AGENT


class BaseScraper(ABC):
    merchant = ""
    base_url = ""

    def __init__(self, delay=REQUEST_DELAY_SECONDS):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
        })
        self._robots = None

    def robots_allowed(self, url: str) -> bool:
        if self._robots is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(urljoin(self.base_url, "/robots.txt"))
            try:
                rp.read()
                self._robots = rp
            except Exception:
                # Fail closed for large crawls; explicit single-page parsing can still be tested manually.
                return False
        return self._robots.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response:
        if not self.robots_allowed(url):
            raise PermissionError(f"robots.txt does not allow catalog fetch: {url}")
        time.sleep(self.delay)
        r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r

    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def json_ld(soup: BeautifulSoup) -> list[dict]:
        out = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.get_text(strip=True))
                if isinstance(data, list): out.extend(x for x in data if isinstance(x, dict))
                elif isinstance(data, dict): out.append(data)
            except Exception:
                pass
        return out

    @abstractmethod
    def discover_product_urls(self): ...

    @abstractmethod
    def parse_product(self, url: str, html: str): ...
