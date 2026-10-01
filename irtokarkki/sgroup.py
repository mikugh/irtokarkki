"""S-group stores (Prisma, S-market, Sale, Alepa, ABC) via the public S-kaupat GraphQL API."""
from dataclasses import replace

import requests

from .models import Deal, Store

API_URL = "https://api.s-kaupat.fi/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://www.s-kaupat.fi",
}
STORES_PER_REQUEST = 5
PRODUCTS_PER_REQUEST = 20
BRAND_NAMES = {
    "prisma": "Prisma", "s-market": "S-market", "sale": "Sale",
    "alepa": "Alepa", "abc": "ABC", "food-market-herkku": "Food Market Herkku",
}

LOCATION_FIELDS = "location { address { street { default } postcode postcodeName { default sv } } coordinates { lat lon } }"


# Product names in other languages, by (EAN, language). Names don't change, so keep them for the whole run.
_name_cache: dict[tuple[str, str], str] = {}


def _post(query: str, variables: dict | None = None, lang: str | None = None) -> dict:
    headers = {**HEADERS, "Accept-Language": lang} if lang else HEADERS
    resp = requests.post(API_URL, json={"query": query, "variables": variables or {}},
                         headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors") and not body.get("data"):
        raise RuntimeError(f"S-kaupat API error: {body['errors'][0].get('message')}")
    return body["data"]


def _to_store(raw: dict) -> Store:
    addr = (raw.get("location") or {}).get("address") or {}
    street = (addr.get("street") or {}).get("default") or ""
    city = (addr.get("postcodeName") or {}).get("default") or ""
    city_sv = (addr.get("postcodeName") or {}).get("sv") or ""
    location = ", ".join(p for p in [street, f"{addr.get('postcode') or ''} {city}".strip()] if p)
    location_sv = location.replace(city, city_sv) if city_sv and city_sv != city else ""
    coords = (raw.get("location") or {}).get("coordinates") or {}
    map_url = (f"https://www.google.com/maps?q={coords['lat']},{coords['lon']}"
               if coords.get("lat") else "")
    brand = raw.get("brand") or ""
    return Store(chain=BRAND_NAMES.get(brand, brand.title()), store_id=raw["id"],
                 name=raw["name"], location=location, map_url=map_url, source="s_group",
                 location_sv=location_sv)


def search_stores(query: str) -> list[Store]:
    data = _post(
        "query($q: String!) { searchStores(query: $q) { stores { id name brand "
        + LOCATION_FIELDS + " } } }",
        {"q": query},
    )
    return [_to_store(s) for s in data["searchStores"]["stores"]]


def finnish_city_name(city: str) -> str:
    """Turn a Swedish city name into the Finnish one ("Åbo" -> "Turku"), using the store addresses."""
    data = _post("query($q: String!) { searchStores(query: $q) { stores { location { address { "
                 "postcodeName { default sv } } } } } }", {"q": city})
    for store in data["searchStores"]["stores"]:
        names = ((store.get("location") or {}).get("address") or {}).get("postcodeName") or {}
        if (names.get("sv") or "").lower() == city.lower() and names.get("default"):
            return names["default"]
    return city


def find_stores(city: str, limit: int) -> list[Store]:
    # The store search is fuzzy, so keep only stores actually in the requested city.
    in_city = [s for s in search_stores(city) if city.lower() in s.location.lower()]
    return in_city[:limit]


def get_stores(store_ids: list[str]) -> list[Store]:
    fields = "{ id name brand " + LOCATION_FIELDS + " }"
    query = "{ " + " ".join(f's{i}: store(id: "{sid}") {fields}' for i, sid in enumerate(store_ids)) + " }"
    data = _post(query)
    return [_to_store(v) for v in data.values() if v]


def find_prices(stores: list[Store], term: str) -> list[Deal]:
    # The API returns 500 when one request asks for too many stores, so batch a few at a time.
    deals = []
    for i in range(0, len(stores), STORES_PER_REQUEST):
        deals += _find_prices_batch(stores[i:i + STORES_PER_REQUEST], term)
    return deals


def translate(deals: list[Deal]) -> list[Deal]:
    """Look up Swedish and English product names. Searching only returns Finnish names,
    but a product looked up by EAN comes back in the language asked for."""
    for lang in ("sv", "en"):
        missing = list({d.product_id: d.store.store_id for d in deals
                        if (d.product_id, lang) not in _name_cache}.items())
        for start in range(0, len(missing), PRODUCTS_PER_REQUEST):
            parts = [f'p{i}: product(id: "{ean}", storeId: "{store_id}") {{ id name }}'
                     for i, (ean, store_id) in enumerate(missing[start:start + PRODUCTS_PER_REQUEST])]
            try:
                data = _post("{ " + " ".join(parts) + " }", lang=lang)
            except Exception:
                continue  # fall back to the Finnish name
            for product in data.values():
                if product and product.get("name"):
                    _name_cache[(product["id"], lang)] = product["name"]
    return [
        replace(d, product_names={lang: _name_cache[(d.product_id, lang)]
                                  for lang in ("sv", "en") if (d.product_id, lang) in _name_cache})
        for d in deals
    ]


def _find_prices_batch(stores: list[Store], term: str) -> list[Deal]:
    """Search several stores for `term` in one request (using GraphQL aliases) and return each item's price."""
    product_fields = ("{ items { id name priceUnit pricing { campaignPrice regularPrice "
                      "campaignPriceValidUntil } } }")
    parts = [
        f's{i}: store(id: "{s.store_id}") {{ products(queryString: $term, limit: 50) {product_fields} }}'
        for i, s in enumerate(stores)
    ]
    data = _post("query($term: String!) { " + " ".join(parts) + " }", {"term": term})

    deals = []
    for i, store in enumerate(stores):
        items = (((data.get(f"s{i}") or {}).get("products")) or {}).get("items") or []
        for item in items:
            pricing = item.get("pricing") or {}
            campaign, regular = pricing.get("campaignPrice"), pricing.get("regularPrice")
            if regular is None:
                continue
            on_sale = campaign is not None and campaign < regular
            deals.append(Deal(
                store=store,
                product_id=item["id"],
                product=item["name"],
                original_price=regular,
                discounted_price=campaign if on_sale else regular,
                unit="kg" if item.get("priceUnit") == "KGM" else "kpl",
                valid_until=(pricing.get("campaignPriceValidUntil") or "")[:10] if on_sale else "",
            ))
    return deals
