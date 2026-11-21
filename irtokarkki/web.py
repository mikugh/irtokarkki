"""Web UI: lists stores with irtokarkki discounts and lets you favourite stores.

Run with:  python -m irtokarkki.web   and open http://localhost:5000

Several people can use it at once. Each visitor's city and favourite stores live in their
own browser and are sent with every request. Prices are cached per store and shared by
everyone, so a store is checked at most once per `cache_hours` however many people look at it.
"""
import hmac
import os
import threading
import time
from dataclasses import asdict
from datetime import datetime

from flask import Flask, jsonify, redirect, request, send_from_directory

from .core import ROOT, SOURCES, city_stores, fetch_prices, load_config, search_stores
from .models import Deal, Store

ACCESS_KEY_PATH = ROOT / "access_key.txt"
KEY_COOKIE = "irtokarkki_key"


def load_access_key() -> str:
    """The secret that visitors need in their link, from IRTOKARKKI_ACCESS_KEY or access_key.txt.
    Empty means anyone who can reach the server may use it."""
    key = os.environ.get("IRTOKARKKI_ACCESS_KEY", "")
    if not key and ACCESS_KEY_PATH.exists():
        key = ACCESS_KEY_PATH.read_text(encoding="utf-8")
    return key.strip()

app = Flask(__name__, static_folder="static")
config = load_config()
web_cfg = config.get("web", {})
MAX_AGE = web_cfg.get("cache_hours", 3) * 3600  # prices older than this are fetched again
REFRESH_AGE = web_cfg.get("min_refresh_minutes", 15) * 60  # "Check for deals" refetches prices older than this
RETRY_AFTER = 10 * 60  # don't retry a store that failed for this long
CITY_MAX_AGE = 24 * 3600  # which stores are in a city rarely changes
MAX_FAVOURITES = 30
STORE_FIELDS = ("chain", "store_id", "name", "location", "map_url", "source", "location_sv")
ACCESS_KEY = load_access_key()

LOCKED_PAGE = """<!doctype html><html lang="fi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Irtokarkki</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f2f7;color:#2a1630;
font:17px/1.5 system-ui,"Segoe UI",sans-serif;padding:24px}main{max-width:30em}h1{font-size:26px;margin:0 0 12px}
p{margin:6px 0;color:#74627a}@media(prefers-color-scheme:dark){body{background:#1b1020;color:#f5edf6}p{color:#b5a4ba}}</style>
</head><body><main><h1>Irtokarkki</h1>
<p>Pyydä henkilökohtainen linkki palvelun ylläpitäjältä.</p>
<p>Be den som driver tjänsten om din personliga länk.</p>
<p>Ask the person who runs this for your personal link.</p></main></body></html>"""


@app.before_request
def require_access_key():
    """With an access key set, only visitors who arrived through the link with ?key=... get in.
    The key is then kept in a cookie, so the plain address and home-screen shortcuts keep working."""
    if not ACCESS_KEY:
        return None
    given = request.args.get("key")
    if given is not None and hmac.compare_digest(given.encode(), ACCESS_KEY.encode()):
        # Drop the key from the address bar, so it isn't left in history or screenshots.
        resp = redirect(request.path or "/")
        resp.set_cookie(KEY_COOKIE, ACCESS_KEY, max_age=365 * 24 * 3600, httponly=True, samesite="Lax")
        return resp
    if hmac.compare_digest(request.cookies.get(KEY_COOKIE, "").encode(), ACCESS_KEY.encode()):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "This needs the personal link from the person who runs it."}), 401
    return LOCKED_PAGE, 401, {"Content-Type": "text/html; charset=utf-8"}


class PriceCache:
    """Each store's latest prices, shared by all visitors.

    request() queues stores whose prices are missing or too old; a single background thread
    fetches them one batch at a time, so the stores' sites see one polite client.
    """

    def __init__(self, fetch, clock=time.time, background: bool = True):
        self._fetch = fetch  # list[Store] -> (deals, errors, failed source names)
        self._clock = clock
        self._background = background  # False: the caller runs run_once() itself (tests)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._prices: dict[str, tuple[float, list[Deal]]] = {}  # store key -> (fetched at, prices)
        self._queued: dict[str, Store] = {}  # waiting or being fetched
        self._failed_at: dict[str, float] = {}  # store key -> last failure
        self._errors: dict[str, tuple[float, str]] = {}  # source -> (when, message)
        self._ok_at: dict[str, float] = {}  # source -> last successful fetch

    def request(self, stores: list[Store], max_age: float = MAX_AGE) -> None:
        now = self._clock()
        with self._lock:
            for store in stores:
                fetched_at = self._prices.get(store.key, (None,))[0]
                fresh = fetched_at is not None and now - fetched_at < max_age
                failed_recently = now - self._failed_at.get(store.key, -RETRY_AFTER) < RETRY_AFTER
                if not fresh and not failed_recently:
                    self._queued.setdefault(store.key, store)
            if self._background and self._queued and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        self._wake.set()

    def snapshot(self, stores: list[Store]) -> dict:
        """What's known about `stores` right now."""
        with self._lock:
            cached = {s.key: self._prices[s.key] for s in stores if s.key in self._prices}
            sources = {s.source for s in stores}
            errors = [msg for source, (when, msg) in self._errors.items()
                      if source in sources and when > self._ok_at.get(source, 0)]
            return {
                "checked": set(cached),
                "deals": [d for _, deals in cached.values() for d in deals],
                "loading": any(s.key in self._queued for s in stores),
                "updated_at": min((at for at, _ in cached.values()), default=None),
                "errors": errors,
            }

    def run_once(self) -> bool:
        """Fetch everything queued so far. Returns False when there was nothing to do."""
        with self._lock:
            batch = list(self._queued.values())
        if not batch:
            return False
        try:
            deals, errors, failed = self._fetch(batch)
        except Exception as e:
            deals, errors, failed = [], [str(e)], {s.source for s in batch}
        now = self._clock()
        by_store: dict[str, list[Deal]] = {}
        for deal in deals:
            by_store.setdefault(deal.store.key, []).append(deal)
        with self._lock:
            for store in batch:
                if store.source in failed:
                    self._failed_at[store.key] = now  # keep any older prices
                else:
                    self._prices[store.key] = (now, by_store.get(store.key, []))
                    self._failed_at.pop(store.key, None)
                self._queued.pop(store.key, None)
            for source in {s.source for s in batch}:
                if source in failed:
                    msg = next((e for e in errors if e.startswith(source)), f"{source}: failed")
                    self._errors[source] = (now, msg)
                else:
                    self._ok_at[source] = now
        return True

    def _run(self) -> None:
        while True:
            self._wake.wait(timeout=60)
            self._wake.clear()
            while self.run_once():
                pass
            with self._lock:
                if not self._queued:
                    self._thread = None
                    return


# Serverless hosts like Vercel may pause a function once it has answered, so a background
# thread never finishes there. Fetch during the request instead.
SERVERLESS = bool(os.environ.get("VERCEL"))
prices = PriceCache(lambda stores: fetch_prices(config, stores), background=not SERVERLESS)
_cities: dict[str, tuple[float, list[Store], list[str]]] = {}  # city (lowercase) -> (when, stores, errors)
_cities_lock = threading.Lock()


def stores_in_city(city: str) -> tuple[list[Store], list[str]]:
    key = city.strip().lower()
    with _cities_lock:
        hit = _cities.get(key)
    max_age = CITY_MAX_AGE if hit and not hit[2] else 300  # retry failed lookups sooner
    if hit and time.time() - hit[0] < max_age:
        return hit[1], hit[2]
    stores, errors = city_stores(config, city)
    with _cities_lock:
        _cities[key] = (time.time(), stores, errors)
    return stores, errors


def parse_favourites(raw) -> list[Store]:
    """The favourite stores a browser sent, ignoring anything malformed."""
    stores = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_FAVOURITES]:
        if not isinstance(item, dict) or item.get("source") not in SOURCES or not item.get("store_id"):
            continue
        stores.append(Store(**{f: str(item.get(f) or "")[:200] for f in STORE_FIELDS}))
    return stores


def _store_json(store: Store, favourite_keys: set, checked: bool = False) -> dict:
    return {**asdict(store), "key": store.key, "favourite": store.key in favourite_keys, "checked": checked}


def _deal_json(deal: Deal) -> dict:
    d = asdict(deal)
    del d["store"]
    return {**d, "store_key": deal.store.key, "percent_off": deal.percent_off, "discounted": deal.is_discounted}


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/state")
def get_state():
    """Body: {"city": "Turku", "favourites": [store, ...], "refresh": false}"""
    body = request.get_json(silent=True) or {}
    city = str(body.get("city") or "").strip()[:60] or config["stores"]["city"]
    favourites = parse_favourites(body.get("favourites"))
    in_city, errors = stores_in_city(city)

    # Favourite stores are always checked, even when they're in another city.
    stores = {s.key: s for s in in_city}
    for fav in favourites:
        stores.setdefault(fav.key, fav)
    stores = list(stores.values())

    prices.request(stores, REFRESH_AGE if body.get("refresh") else MAX_AGE)
    if SERVERLESS:
        prices.run_once()
    snap = prices.snapshot(stores)
    favourite_keys = {f.key for f in favourites}
    updated = snap["updated_at"]
    return jsonify({
        "city": city,
        "city_found": bool(in_city) or bool(errors),  # False: no stores in this city, e.g. a typo
        "loading": snap["loading"],
        "updated_at": datetime.fromtimestamp(updated).astimezone().isoformat(timespec="minutes") if updated else None,
        "errors": errors + snap["errors"],
        "stores": [_store_json(s, favourite_keys, s.key in snap["checked"]) for s in stores],
        "deals": [_deal_json(d) for d in sorted(snap["deals"], key=lambda d: (d.discounted_price, d.store.name))],
    })


@app.get("/api/stores/search")
def store_search():
    query = request.args.get("q", "").strip()[:60]
    if len(query) < 2:
        return jsonify([])
    return jsonify([_store_json(s, set()) for s in search_stores(query)])


def main() -> None:
    host = os.environ.get("IRTOKARKKI_HOST", "127.0.0.1")
    port = int(os.environ.get("IRTOKARKKI_PORT", "5000"))
    print(f"Irtokarkki running at http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
