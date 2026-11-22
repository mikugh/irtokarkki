"""Pick-and-mix offers in S-group's weekly flyers.

Pick-and-mix (the weighed bins) isn't sold online, so its campaigns never show up in the
S-kaupat catalog. Each regional S-group cooperative publishes its flyers in a library on
view.sok-julkaisut.fi, e.g. Turun Osuuskauppa's at /library/tok-ilmoitukset. Every flyer
there comes with a content.json holding the text of each page, word by word with its
position, so the offers can be read without looking at the images.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape

import requests

BASE_URL = "https://view.sok-julkaisut.fi"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
# Words closer than this (in page points) belong to the same offer tile.
MAX_GAP_X = 30
MAX_GAP_Y = 20


@dataclass(frozen=True)
class Flyer:
    doc_id: str
    title: str  # e.g. "TOK Prisma 18.–22.11."
    published: str  # ISO date
    url: str  # the flyer's page in the online reader


@dataclass(frozen=True)
class FlyerOffer:
    flyer: Flyer
    text: str  # the offer's words, e.g. "5 90 Voim. la 21.11. Irtonamujo ..."
    price: str = ""  # e.g. "5,90", when the tile starts with one

    @property
    def description(self) -> str:
        """The offer's text without the price at its start."""
        return re.sub(r"^\d{1,3} \d{2}\b\s*", "", self.text) if self.price else self.text


def _get(url: str, **kwargs) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=30, **kwargs)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp


def library_name(library: str) -> str:
    """The library's heading, e.g. "Turun Osuuskaupan edut ja kampanjat"."""
    html = _get(f"{BASE_URL}/library/{library}").text
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    return unescape(match.group(1)).strip() if match else library


def parse_library_page(html: str, library: str) -> list[Flyer]:
    flyers = []
    for item in html.split('class="publication-item')[1:]:
        doc = re.search(r'/downloadpdf/([0-9a-f]{32})', item)
        title = re.search(r'class="publication-title">(.*?)</h3>', item, re.S)
        slug = re.search(rf'href="(/{re.escape(library)}/[^"]+)"', item)
        date = re.search(r'class="created">[^<]*?(\d{1,2})\.(\d{1,2})\.(\d{4})', item)
        if not (doc and title and slug):
            continue
        published = f"{date.group(3)}-{int(date.group(2)):02d}-{int(date.group(1)):02d}" if date else ""
        flyers.append(Flyer(doc_id=doc.group(1), title=unescape(title.group(1)).strip(),
                            published=published, url=BASE_URL + slug.group(1)))
    return flyers


def list_flyers(library: str) -> list[Flyer]:
    """The library's current flyers. Expired ones are removed from the library."""
    root = _get(f"{BASE_URL}/library/{library}").text
    categories = sorted(set(re.findall(r'data-cid=(\d+)', root))) or ["-1"]
    flyers: dict[str, Flyer] = {}
    for cat in categories:
        page = _get(f"{BASE_URL}/library/{library}", params={"cat": cat}).text
        for flyer in parse_library_page(page, library):
            flyers.setdefault(flyer.doc_id, flyer)
    return list(flyers.values())


def flyer_pages(library: str, doc_id: str) -> list[list[dict]]:
    """Each page's words, as {"word": str, "box": [x0, y0, x1, y1]}."""
    url = f"{BASE_URL}/sites/all/files/public_files/documents/{library}/{doc_id}/content.json"
    pages = _get(url).json()
    return [[w for paragraph in page.get("paragraphs", []) for w in paragraph] for page in pages]


def _near(a: list[float], b: list[float]) -> bool:
    gap_x = max(0, b[0] - a[2], a[0] - b[2])
    gap_y = max(0, b[1] - a[3], a[1] - b[3])
    return gap_x <= MAX_GAP_X and gap_y <= MAX_GAP_Y


def tiles(words: list[dict]) -> list[list[dict]]:
    """Group a page's words into offer tiles: words that sit close together."""
    parent = list(range(len(words)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(words):
        for j in range(i + 1, len(words)):
            if _near(a["box"], words[j]["box"]):
                parent[root(i)] = root(j)
    groups: dict[int, list[dict]] = {}
    for i, word in enumerate(words):  # keeps the flyer's own reading order within a tile
        groups.setdefault(root(i), []).append(word)
    return list(groups.values())


def _normalise(text: str) -> str:
    """Lowercase and without spaces or hyphens, so "Irto-\nmakeiset" still matches."""
    return re.sub(r"[\s\-­]", "", text.lower())


def matches(text: str, keyword: str) -> bool:
    """Whether a flyer tile's text mentions `keyword` (case, spaces and hyphens ignored)."""
    return _normalise(keyword) in _normalise(text)


def find_offers(flyer: Flyer, pages: list[list[dict]], keywords: list[str]) -> list[FlyerOffer]:
    offers = []
    for words in pages:
        for tile in tiles(words):
            text = " ".join(w["word"] for w in tile)
            if any(matches(text, k) for k in keywords):
                price = re.match(r"(\d{1,3}) (\d{2})\b", text)  # flyers print 5,90 as big "5" and small "90"
                offers.append(FlyerOffer(flyer, text, f"{price.group(1)},{price.group(2)}" if price else ""))
    return offers


def check(library: str, keywords: list[str], cache: dict | None = None) -> list[FlyerOffer]:
    """Pick-and-mix offers in the library's current flyers.

    `cache` (doc_id -> pages) avoids fetching the same flyer again; flyers don't change once published.
    """
    cache = {} if cache is None else cache
    flyers = list_flyers(library)
    missing = [f for f in flyers if f.doc_id not in cache]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for flyer, pages in zip(missing, pool.map(lambda f: flyer_pages(library, f.doc_id), missing)):
            cache[flyer.doc_id] = pages
    offers = []
    for flyer in flyers:
        offers += find_offers(flyer, cache[flyer.doc_id], keywords)
    return offers
