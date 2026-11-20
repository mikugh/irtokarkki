"""The web UI serves several people at once: shared price cache, per-visitor city and favourites."""
import pytest

from irtokarkki import web
from irtokarkki.models import Deal, Store
from irtokarkki.web import RETRY_AFTER, PriceCache


def store(n, source="s_group", city="Turku"):
    return Store(chain="Prisma", store_id=str(n), name=f"Prisma {n}", location=city, source=source)


class FakeFetch:
    """Stands in for the store APIs: every store has one product at 3 €."""

    def __init__(self):
        self.calls = []
        self.fail = set()

    def __call__(self, stores):
        self.calls.append(sorted(s.key for s in stores))
        deals = [Deal(s, "p1", "Irttarit 400g", 3.0, 3.0) for s in stores if s.source not in self.fail]
        return deals, [f"{src}: blocked" for src in self.fail], set(self.fail)


class Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


def make_cache():
    fetch, clock = FakeFetch(), Clock()
    return PriceCache(fetch, clock=clock, background=False), fetch, clock


def test_visitors_share_cached_prices():
    cache, fetch, clock = make_cache()
    cache.request([store(1), store(2)])
    assert cache.snapshot([store(1)])["loading"]
    cache.run_once()
    cache.request([store(1)])  # a second visitor looking at the same store
    assert not cache.run_once()
    assert fetch.calls == [["s_group:1", "s_group:2"]]
    snap = cache.snapshot([store(1)])
    assert snap["checked"] == {"s_group:1"} and len(snap["deals"]) == 1 and not snap["loading"]


def test_old_prices_are_fetched_again():
    cache, fetch, clock = make_cache()
    cache.request([store(1)])
    cache.run_once()
    clock.now += 600
    cache.request([store(1)], max_age=3600)
    assert not cache.run_once()  # still fresh
    cache.request([store(1)], max_age=300)  # "Check for deals" wants newer prices
    assert cache.run_once()
    assert len(fetch.calls) == 2


def test_failed_chain_keeps_old_prices_and_waits_before_retrying():
    cache, fetch, clock = make_cache()
    cache.request([store(1)])
    cache.run_once()
    fetch.fail = {"s_group"}
    clock.now += 4 * 3600
    cache.request([store(1)])
    cache.run_once()
    snap = cache.snapshot([store(1)])
    assert snap["errors"] == ["s_group: blocked"]
    assert len(snap["deals"]) == 1  # the older prices are still shown

    cache.request([store(1)])  # page polling right after the failure
    assert not cache.run_once()
    clock.now += RETRY_AFTER
    fetch.fail = set()
    cache.request([store(1)])
    assert cache.run_once()
    assert cache.snapshot([store(1)])["errors"] == []


def test_parse_favourites_ignores_junk():
    favs = web.parse_favourites([
        {"source": "k_group", "store_id": "N168", "name": "K-Citymarket Skanssi", "chain": "K-Citymarket"},
        {"source": "evil", "store_id": "1"},
        {"source": "s_group"},
        "nope",
    ])
    assert [f.key for f in favs] == ["k_group:N168"]
    assert web.parse_favourites({"not": "a list"}) == []
    assert len(web.parse_favourites([{"source": "s_group", "store_id": str(i)} for i in range(100)])) == web.MAX_FAVOURITES


@pytest.fixture
def client(monkeypatch):
    cities = {"turku": [store(1), store(2)], "tampere": [store(3, city="Tampere")]}
    monkeypatch.setattr(web, "stores_in_city", lambda city: (cities.get(city.lower(), []), []))
    cache, fetch, _ = make_cache()
    monkeypatch.setattr(web, "prices", cache)
    return web.app.test_client(), cache


def test_each_visitor_gets_their_own_city_and_favourites(client):
    http, cache = client
    tampere_fav = {"source": "s_group", "store_id": "3", "name": "Prisma 3", "chain": "Prisma", "location": "Tampere"}

    first = http.post("/api/state", json={"city": "Turku", "favourites": [tampere_fav]}).json
    assert first["loading"]
    cache.run_once()
    me = http.post("/api/state", json={"city": "Turku", "favourites": [tampere_fav]}).json
    friend = http.post("/api/state", json={"city": "Tampere", "favourites": []}).json

    assert me["city"] == "Turku" and not me["loading"]
    assert {s["key"]: s["favourite"] for s in me["stores"]} == {
        "s_group:1": False, "s_group:2": False, "s_group:3": True}
    assert friend["city"] == "Tampere"
    assert [(s["key"], s["favourite"], s["checked"]) for s in friend["stores"]] == [("s_group:3", False, True)]
    assert {d["store_key"] for d in friend["deals"]} == {"s_group:3"}


def test_unknown_city_is_reported(client):
    http, _ = client
    assert http.post("/api/state", json={"city": "Turku"}).json["city_found"]
    unknown = http.post("/api/state", json={"city": "Xyzzyvaara"}).json
    assert not unknown["city_found"] and unknown["stores"] == []


def test_missing_city_falls_back_to_config(client):
    http, _ = client
    assert http.post("/api/state", json={}).json["city"] == web.config["stores"]["city"]
