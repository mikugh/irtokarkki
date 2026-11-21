"""The shopping list: what the owner usually buys, and which of it is on sale right now.

A list item is either an exact product (by EAN) or a word that any product's name may contain.
Sales come from the favourite stores' online prices and, for words with "flyers" on, from the
cooperative's flyers (pick-and-mix and other things the online shop doesn't sell).
"""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import flyers, sgroup
from .core import SOURCES
from .models import Deal, Store

MAX_ITEMS = 60  # keeps a check well inside Vercel's 300 s
MIN_WORD = 3  # shorter words would match nearly everything
MAX_WORD = 40
MAX_NAME = 120
MAX_STORES = 30
STORE_FIELDS = ("chain", "store_id", "name", "location", "map_url", "source", "location_sv")
DEFAULT_LIST = [{"type": "word", "text": t, "flyers": True} for t in ("irtokark", "irtomakeis", "irtonamu", "irttari")]


@dataclass(frozen=True)
class Sale:
    item: str  # the list item: the product's name on the list, or the word
    item_type: str  # "product" or "word"
    product: str  # the product's name in the store, or the flyer offer's text
    price: float | None  # sale price; None when a flyer offer shows no price
    regular_price: float | None  # None for flyer offers
    place: str  # store name, or flyer title (which carries the flyer's dates)
    url: str
    until: str  # ISO date the sale ends, "" when unknown (flyers)
    key: str  # identifies this exact sale, for "already notified"


def parse_items(raw) -> list[dict]:
    """A list as sent by the page, without anything malformed, duplicated or over the limit."""
    items, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "word":
            text = " ".join(str(item.get("text") or "").split()).lower()
            if not MIN_WORD <= len(text) <= MAX_WORD or ("word", text) in seen:
                continue
            seen.add(("word", text))
            items.append({"type": "word", "text": text, "flyers": bool(item.get("flyers"))})
        elif item.get("type") == "product":
            ean = str(item.get("ean") or "").strip()
            name = " ".join(str(item.get("name") or "").split())[:MAX_NAME]
            if not re.fullmatch(r"\d{8,14}", ean) or not name or ("product", ean) in seen:
                continue
            seen.add(("product", ean))
            items.append({"type": "product", "ean": ean, "name": name})
        if len(items) == MAX_ITEMS:
            break
    return items


def parse_stores(raw) -> list[Store]:
    """Favourite stores as sent by the page or kept in storage, ignoring anything malformed."""
    stores, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        if (not isinstance(item, dict) or item.get("source") not in SOURCES
                or not str(item.get("store_id") or "").isdigit()):  # ids go into the API query text
            continue
        store = Store(**{f: str(item.get(f) or "")[:200] for f in STORE_FIELDS})
        if store.key not in seen:
            seen.add(store.key)
            stores.append(store)
        if len(stores) == MAX_STORES:
            break
    return stores


def _store_sale(item: str, item_type: str, deal: Deal) -> Sale:
    return Sale(item=item, item_type=item_type, product=deal.product, price=deal.discounted_price,
                regular_price=deal.original_price, place=deal.store.name,
                url=f"https://www.s-kaupat.fi/tuote/{deal.product_id}", until=deal.valid_until,
                key="|".join([item, deal.product_id, deal.store.store_id, f"{deal.discounted_price:.2f}", deal.valid_until]))


def _flyer_sale(word: str, offer: flyers.FlyerOffer) -> Sale:
    return Sale(item=word, item_type="word", product=offer.description,
                price=float(offer.price.replace(",", ".")) if offer.price else None, regular_price=None,
                place=offer.flyer.title, url=offer.flyer.url, until="",
                key="|".join([word, "flyer", offer.flyer.doc_id, offer.text]))


def check_list(items: list[dict], stores: list[Store], library: str,
               flyer_pages: dict) -> tuple[list[Sale], list[str]]:
    """Every item on the list that's on sale in `stores` or the flyers, and any error messages.
    `flyer_pages` caches each flyer's text between checks (a published flyer doesn't change)."""
    products = [i for i in items if i["type"] == "product"]
    words = [i for i in items if i["type"] == "word"]
    by_item: dict[int, list[Sale]] = {}
    errors: list[str] = []
    store_failed = False

    found_products: set[tuple[str, str]] = set()  # (EAN, store id) already shown under an exact product
    if products and stores:
        try:
            names = {p["ean"]: p["name"] for p in products}
            for deal in sgroup.lookup_products(stores, list(names)):
                found_products.add((deal.product_id, deal.store.store_id))
                if deal.is_discounted:
                    by_item.setdefault(items.index(next(p for p in products if p["ean"] == deal.product_id)), []).append(
                        _store_sale(names[deal.product_id], "product", deal))
        except Exception as e:
            errors.append(f"s_group: {e}")
            store_failed = True

    if words and stores and not store_failed:
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda w: _search(stores, w["text"]), words))
        for word, (deals, error) in zip(words, results):
            if error:
                if not store_failed:
                    errors.append(f"s_group: {error}")
                store_failed = True
                continue
            for deal in deals:
                if (deal.is_discounted and word["text"] in deal.product.lower()
                        and (deal.product_id, deal.store.store_id) not in found_products):
                    by_item.setdefault(items.index(word), []).append(_store_sale(word["text"], "word", deal))

    flyer_words = [w for w in words if w["flyers"]]
    if flyer_words:
        try:
            offers = flyers.check(library, [w["text"] for w in flyer_words], flyer_pages)
            for word in flyer_words:
                by_item.setdefault(items.index(word), []).extend(
                    _flyer_sale(word["text"], o) for o in offers if flyers.matches(o.text, word["text"]))
        except Exception as e:
            errors.append(f"flyers: {e}")

    sales = []
    for index in sorted(by_item):
        sales += sorted(by_item[index], key=lambda s: (s.price is None, s.price or 0, s.place))
    return sales, errors


def _search(stores: list[Store], word: str) -> tuple[list[Deal], str]:
    try:
        return sgroup.find_prices(stores, word), ""
    except Exception as e:
        return [], str(e)
