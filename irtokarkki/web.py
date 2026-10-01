"""Web UI: lists stores with irtokarkki discounts and lets you favourite stores.

Run with:  python -m irtokarkki.web   and open http://localhost:5000
"""
import threading
from dataclasses import asdict
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory

from .core import collect, load_config, load_favourites, save_favourites, search_stores
from .models import Deal, Store

app = Flask(__name__, static_folder="static")
config = load_config()

_lock = threading.Lock()
_state = {
    "city": config["stores"]["city"],
    "loading": False,
    "rerun": False,  # a refresh was requested while one was already running
    "updated_at": None,
    "errors": [],
    "stores": [],  # list[Store]
    "deals": [],  # list[Deal]: current price of every irtokarkki product found, discounted or not
}


def _store_json(store: Store, favourites: dict, checked: bool = False) -> dict:
    return {**asdict(store), "key": store.key, "favourite": store.key in favourites, "checked": checked}


def _deal_json(deal: Deal) -> dict:
    d = asdict(deal)
    del d["store"]
    return {**d, "store_key": deal.store.key, "percent_off": deal.percent_off, "discounted": deal.is_discounted}


def _refresh() -> None:
    while True:
        try:
            stores, deals, errors = collect(config, load_favourites(), city=_state["city"])
        except Exception as e:
            stores, deals, errors = [], [], [str(e)]
        with _lock:
            _state.update(stores=stores, deals=deals, errors=errors,
                          updated_at=datetime.now().isoformat(timespec="minutes"))
            if not _state["rerun"]:
                _state["loading"] = False
                return
            _state["rerun"] = False


def start_refresh() -> None:
    with _lock:
        if _state["loading"]:
            _state["rerun"] = True
            return
        _state["loading"] = True
    threading.Thread(target=_refresh, daemon=True).start()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def get_state():
    favourites = load_favourites()
    with _lock:
        checked = {s.key: s for s in _state["stores"]}
        # Favourites are always listed, even before they've been checked.
        stores = {**favourites, **checked}
        return jsonify({
            "city": _state["city"],
            "loading": _state["loading"],
            "updated_at": _state["updated_at"],
            "errors": _state["errors"],
            "stores": [_store_json(s, favourites, s.key in checked) for s in stores.values()],
            "deals": [_deal_json(d) for d in _state["deals"]],
        })


@app.post("/api/refresh")
def refresh():
    city = (request.get_json(silent=True) or {}).get("city", "").strip()
    if city:
        _state["city"] = city
    start_refresh()
    return get_state()


@app.get("/api/stores/search")
def store_search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    favourites = load_favourites()
    return jsonify([_store_json(s, favourites) for s in search_stores(query)])


@app.put("/api/favourites/<path:key>")
def add_favourite(key):
    store = Store(**{f: request.json[f] for f in ("chain", "store_id", "name", "location", "map_url", "source")})
    if store.key != key:
        return jsonify({"error": "key mismatch"}), 400
    favourites = load_favourites()
    favourites[key] = store
    save_favourites(favourites)
    # A favourite from outside the current list hasn't been checked for deals yet.
    if not any(s.key == key for s in _state["stores"]):
        start_refresh()
    return jsonify({"ok": True})


@app.delete("/api/favourites/<path:key>")
def remove_favourite(key):
    favourites = load_favourites()
    favourites.pop(key, None)
    save_favourites(favourites)
    return jsonify({"ok": True})


def main() -> None:
    start_refresh()
    print("Irtokarkki running at http://localhost:5000")
    app.run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
