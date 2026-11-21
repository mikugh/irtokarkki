"""Web UI: the owner's shopping list and which of it is on sale in their favourite S-group stores.

Run with:  python -m irtokarkki.web   and open http://localhost:5000

The list and favourite stores are kept on the server (see storage.py), so they're the same on
every device. Vercel Cron calls /api/cron/daily once a morning to message new sales to the phone.
"""
import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import asdict
from datetime import datetime

from flask import Flask, jsonify, redirect, request, send_from_directory

from . import daily, sgroup, shopping
from .core import ROOT, load_config, search_stores
from .models import Store
from .storage import StorageNotConfigured, load_storage

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
MAX_AGE = web_cfg.get("cache_hours", 3) * 3600  # sales older than this are checked again
REFRESH_AGE = web_cfg.get("min_refresh_minutes", 15) * 60  # "Check" rechecks sales older than this
LIBRARY = config.get("flyers", {}).get("library", "tok-ilmoitukset")
ACCESS_KEY = load_access_key()
CRON_PATH = "/api/cron/daily"

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
    if not ACCESS_KEY or request.path == CRON_PATH:  # Vercel Cron can't log in; it has CRON_SECRET instead
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


clock = time.time
_storage = None


def get_storage():
    """The storage, created on first use so a missing database only fails requests, not the app."""
    global _storage
    if _storage is None:
        _storage = load_storage()
    return _storage


@app.errorhandler(StorageNotConfigured)
def storage_missing(e):
    return jsonify({"error": str(e)}), 503


def _store_json(store: Store, favourite: bool = False) -> dict:
    return {**asdict(store), "key": store.key, "favourite": favourite}


def _items() -> list[dict]:
    items = get_storage().get("list")
    return shopping.DEFAULT_LIST if items is None else shopping.parse_items(items)


def _stores() -> list[Store]:
    return shopping.parse_stores(get_storage().get("stores"))


class SalesCache:
    """The latest check of the list, reused until the list or stores change or it gets old."""

    def __init__(self):
        self._lock = threading.Lock()
        self.clear()

    def clear(self) -> None:
        self._fingerprint = None
        self._checked_at = 0.0
        self._sales: list[shopping.Sale] = []
        self._errors: list[str] = []
        self.flyer_pages: dict = {}  # each flyer's text, kept: a published flyer doesn't change

    def get(self, items: list[dict], stores: list[Store], refresh: bool) -> dict:
        fingerprint = hashlib.sha256(json.dumps([items, [s.key for s in stores]]).encode()).hexdigest()
        with self._lock:  # one request checks; others wait and share the result
            age = clock() - self._checked_at
            if fingerprint != self._fingerprint or age >= (REFRESH_AGE if refresh else MAX_AGE):
                self._sales, self._errors = shopping.check_list(items, stores, LIBRARY, self.flyer_pages)
                self._fingerprint, self._checked_at = fingerprint, clock()
            return {
                "sales": [asdict(s) for s in self._sales],
                "errors": self._errors,
                "checked_at": datetime.fromtimestamp(self._checked_at).astimezone().isoformat(timespec="minutes"),
                "items": len(items),
                "stores": len(stores),
            }


sales_cache = SalesCache()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/list")
def get_list():
    return jsonify({"items": _items()})


@app.put("/api/list")
def put_list():
    items = shopping.parse_items((request.get_json(silent=True) or {}).get("items"))
    get_storage().set("list", items)
    return jsonify({"items": items})


@app.get("/api/favourites")
def get_favourites():
    return jsonify({"stores": [_store_json(s, True) for s in _stores()]})


@app.put("/api/favourites")
def put_favourites():
    stores = shopping.parse_stores((request.get_json(silent=True) or {}).get("stores"))
    get_storage().set("stores", [asdict(s) for s in stores])
    return jsonify({"stores": [_store_json(s, True) for s in stores]})


@app.post("/api/sales")
def get_sales():
    refresh = bool((request.get_json(silent=True) or {}).get("refresh"))
    return jsonify(sales_cache.get(_items(), _stores(), refresh))


@app.get("/api/products/search")
def product_search():
    """Products to add to the list, from one favourite store's catalog (the API needs a store)."""
    query = request.args.get("q", "").strip()[:60]
    store_id = request.args.get("store", "").strip()
    stores = _stores()
    if len(query) < 2 or not (stores or store_id):
        return jsonify([])
    store = next((s for s in stores if s.store_id == store_id), None) or (
        Store("", store_id, "", "", source="s_group") if store_id.isdigit() else stores[0])
    return jsonify([{"ean": d.product_id, "name": d.product, "price": d.discounted_price,
                     "regular_price": d.original_price, "unit": d.unit}
                    for d in sgroup.search_products(store, query)])


@app.get("/api/stores/search")
def store_search():
    query = request.args.get("q", "").strip()[:60]
    if len(query) < 2:
        return jsonify([])
    favourite_keys = {s.key for s in _stores()}
    return jsonify([_store_json(s, s.key in favourite_keys) for s in search_stores(query)])


@app.get(CRON_PATH)
def cron_daily():
    secret = os.environ.get("CRON_SECRET", "")
    given = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(given.encode(), f"Bearer {secret}".encode()):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(daily.run(get_storage(), os.environ.get("NTFY_TOPIC", ""),
                             server=os.environ.get("NTFY_SERVER", "https://ntfy.sh"), library=LIBRARY))


def main() -> None:
    host = os.environ.get("IRTOKARKKI_HOST", "127.0.0.1")
    port = int(os.environ.get("IRTOKARKKI_PORT", "5000"))
    print(f"Irtokarkki running at http://{'localhost' if host == '127.0.0.1' else host}:{port}")
    from waitress import serve
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
