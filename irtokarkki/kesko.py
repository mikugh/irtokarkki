"""K-group stores (K-Citymarket, K-Supermarket, K-Market) via the k-ruoka.fi web API."""
import re
import time
from dataclasses import replace

from urllib.parse import quote

# k-ruoka.fi is behind Cloudflare, which blocks the plain `requests` library;
# curl_cffi makes the request look like it comes from Chrome.
from curl_cffi import requests

from .models import Deal, Store

BASE_URL = "https://www.k-ruoka.fi"
_session = requests.Session(impersonate="chrome")
_build_number: str | None = None


def _get_build_number(refresh: bool = False) -> str:
    """The API rejects requests without the current web client build number, so read it from the homepage."""
    global _build_number
    if _build_number is None or refresh:
        html = _session.get(BASE_URL, timeout=30).text
        match = re.search(r"/assets/b-(\d+)/", html)
        if not match:
            raise RuntimeError("Could not find K-Ruoka build number on homepage")
        _build_number = match.group(1)
    return _build_number


def _post(path: str, params: dict | None = None, body: dict | None = None) -> dict:
    for attempt in range(2):
        headers = {"Accept": "application/json", "X-K-Build-Number": _get_build_number(refresh=attempt > 0)}
        resp = _session.post(BASE_URL + path, params=params, json=body, headers=headers, timeout=30)
        if resp.status_code == 409 and attempt == 0:  # "Client version is too old"
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("K-Ruoka API kept rejecting the client version")


def _to_store(raw: dict) -> Store:
    geo = raw.get("geo") or {}
    map_url = (f"https://www.google.com/maps?q={geo['latitude']},{geo['longitude']}"
               if geo.get("latitude") else "")
    return Store(chain=raw.get("chainName") or "K-Ruoka", store_id=raw["id"],
                 name=raw["name"].replace("‑", "-"), location=raw.get("location") or "",
                 map_url=map_url, source="k_group")


def search_stores(query: str) -> list[Store]:
    data = _post("/kr-api/stores/search", body={"query": query, "offset": 0, "limit": 50})
    return [_to_store(s) for s in data["results"]]


def find_stores(city: str, limit: int) -> list[Store]:
    return [s for s in search_stores(city) if s.location.lower() == city.lower()][:limit]


def get_stores(store_ids: list[str]) -> list[Store]:
    data = _post("/kr-api/stores/search",
                 body={"query": "", "offset": 0, "limit": 50, "storeIds": store_ids})
    return [_to_store(s) for s in data["results"] if s["id"] in store_ids]


def _deal_from_pricing(store: Store, product: dict, pricing: dict) -> Deal | None:
    """The product's best current price: the cheapest offer, or the normal price when there's no offer."""
    normal = pricing.get("normal") or {}
    original = normal.get("price")
    if original is None:
        return None
    names = product.get("localizedName") or {}
    best = Deal(
        store=store,
        product_id=product["id"],
        product=names["finnish"],
        original_price=original,
        discounted_price=original,
        unit=normal.get("unit") or "kpl",
        product_names={k: names[v] for k, v in (("sv", "swedish"), ("en", "english")) if names.get(v)},
    )
    for kind, offer in pricing.items():
        if kind in ("normal", "libraryVersion") or not isinstance(offer, dict) or "price" not in offer:
            continue
        amount = offer.get("amount") or 1  # "batch" offers are e.g. 2 kpl for 4.80 €
        per_item = round(offer["price"] / amount, 2)
        if per_item >= best.discounted_price:
            continue
        best = replace(
            best,
            discounted_price=per_item,
            valid_until=(offer.get("endDate") or "")[:10],
            batch_amount=amount,
            batch_price=offer["price"] if amount > 1 else 0.0,
            plussa=offer.get("discountType") == "PLUSSA",
        )
    return best


def translate(deals: list[Deal]) -> list[Deal]:
    return deals  # K-Ruoka search results already include Swedish and English names


def find_prices(stores: list[Store], term: str) -> list[Deal]:
    deals = []
    for store in stores:
        data = _post(f"/kr-api/v2/product-search/{quote(term)}",
                     params={"storeId": store.store_id, "language": "fi", "offset": 0, "limit": 100})
        for hit in data.get("result", []):
            product = hit.get("product") or {}
            pricing = (product.get("mobilescan") or {}).get("pricing") or {}
            deal = _deal_from_pricing(store, product, pricing)
            if deal:
                deals.append(deal)
        time.sleep(0.3)  # be polite
    return deals
