"""The web API: the shopping list, favourite stores, sales, behind the access key."""
import pytest

from tarjoushaukka import shopping, web
from tarjoushaukka.models import Deal, Store
from tarjoushaukka.shopping import Sale
from tarjoushaukka.storage import MemoryStorage, StorageNotConfigured

HALINEN = {"source": "s_group", "store_id": "603212622", "name": "S-market Halinen", "chain": "S-market",
           "location": "Turku"}
SALE = Sale("kahvi", "word", "Kulta Katriina 500g", 3.95, 5.29, "S-market Halinen", "https://x", "2026-11-22")


class FakeCheck:
    def __init__(self):
        self.calls = 0

    def __call__(self, items, stores, library, flyer_pages, prices=None):
        self.calls += 1
        if prices is not None:
            prices["6411300000494"] = {"regular_price": 8.89, "store": "S-market Halinen"}
        return [SALE], []


@pytest.fixture
def fake_check(monkeypatch):
    check = FakeCheck()
    monkeypatch.setattr(shopping, "check_list", check)
    return check


@pytest.fixture
def client(monkeypatch, fake_check):
    store = MemoryStorage()
    monkeypatch.setattr(web, "get_storage", lambda: store)
    monkeypatch.setattr(web, "ACCESS_KEY", "")  # the access key has its own tests below
    web.sales_cache.clear()
    return web.app.test_client()


def test_list_round_trip_and_default(client):
    assert client.get("/api/list").json["items"] == shopping.DEFAULT_LIST
    saved = client.put("/api/list", json={"items": [{"type": "word", "text": "Kahvi"}, {"type": "word", "text": "ka"}]}).json
    assert saved["items"] == [{"type": "word", "text": "kahvi", "flyers": False}]
    assert client.get("/api/list").json == saved
    assert client.put("/api/list", json={"items": []}).json["items"] == []
    assert client.get("/api/list").json["items"] == []  # an emptied list stays empty


def test_favourites_round_trip_ignores_junk(client):
    assert client.get("/api/favourites").json["stores"] == []
    saved = client.put("/api/favourites", json={"stores": [HALINEN, {"source": "evil", "store_id": "1"}, "nope"]}).json
    assert [s["key"] for s in saved["stores"]] == ["s_group:603212622"]
    assert saved["stores"][0]["favourite"] is True
    assert client.get("/api/favourites").json == saved


def test_sales_are_cached_until_list_or_stores_change(client, fake_check):
    client.put("/api/favourites", json={"stores": [HALINEN]})
    first = client.post("/api/sales", json={}).json
    assert first["sales"][0]["product"] == "Kulta Katriina 500g" and first["errors"] == []
    assert first["items"] == len(shopping.DEFAULT_LIST) and first["stores"] == 1 and first["checked_at"]
    assert first["prices"] == {"6411300000494": {"regular_price": 8.89, "store": "S-market Halinen"}}
    assert client.post("/api/sales", json={}).json["prices"] == first["prices"]  # kept with the cached check
    assert fake_check.calls == 1
    client.put("/api/list", json={"items": [{"type": "word", "text": "maito"}]})
    client.post("/api/sales", json={})
    assert fake_check.calls == 2


def test_refresh_rechecks_only_after_the_short_wait(client, fake_check, monkeypatch):
    now = [1_795_000_000.0]
    monkeypatch.setattr(web, "clock", lambda: now[0])
    client.post("/api/sales", json={})
    client.post("/api/sales", json={"refresh": True})
    assert fake_check.calls == 1
    now[0] += web.REFRESH_AGE
    client.post("/api/sales", json={"refresh": True})
    assert fake_check.calls == 2


PRISMA = {"source": "s_group", "store_id": "590784583", "name": "Prisma Itäharju", "chain": "Prisma",
          "location": "Turku"}


def test_product_search_shows_the_cheapest_favourite_store(client, monkeypatch):
    seen = []

    def fake_find(stores, query):
        seen.append(([s.store_id for s in stores], query))
        halinen, prisma = stores[0], stores[-1]
        return [
            Deal(halinen, "6414893386969", "Kotimaista maitorahka 250g rasvaton laktoositon", 1.05, 1.05),
            Deal(prisma, "6414893386969", "Kotimaista maitorahka 250g rasvaton laktoositon", 0.74, 0.74),
            Deal(halinen, "6411300000494", "Juhla Mokka 500g", 8.89, 6.99),
        ]
    monkeypatch.setattr(web.sgroup, "find_prices", fake_find)
    assert client.get("/api/products/search?q=rahka").json == []  # no favourite stores yet
    client.put("/api/favourites", json={"stores": [HALINEN, PRISMA]})
    assert client.get("/api/products/search?q=r").json == []  # too short
    found = client.get("/api/products/search?q=rahka").json
    assert seen == [(["603212622", "590784583"], "rahka")]
    assert found == [
        {"ean": "6414893386969", "name": "Kotimaista maitorahka 250g rasvaton laktoositon", "price": 0.74,
         "regular_price": 0.74, "unit": "kpl", "store": "Prisma Itäharju"},
        {"ean": "6411300000494", "name": "Juhla Mokka 500g", "price": 6.99, "regular_price": 8.89, "unit": "kpl",
         "store": "S-market Halinen"},
    ]


def test_storage_not_connected_gives_503(client, monkeypatch):
    def broken():
        raise StorageNotConfigured("Storage isn't connected: add Upstash Redis to the Vercel project.")
    monkeypatch.setattr(web, "get_storage", broken)
    for resp in (client.get("/api/list"), client.post("/api/sales", json={}), client.get("/api/favourites")):
        assert resp.status_code == 503 and "Upstash" in resp.json["error"]


def test_access_key_locks_out_visitors_without_the_link(client, monkeypatch):
    monkeypatch.setattr(web, "ACCESS_KEY", "s3cret-key")
    for path in ("/", "/static/index.html"):
        page = client.get(path)
        assert page.status_code == 401 and b"personal link" in page.data
    assert client.get("/api/list").status_code == 401
    assert client.post("/api/sales", json={}).status_code == 401
    assert client.get("/api/stores/search?q=Prisma").status_code == 401
    assert client.get("/?key=wrong").status_code == 401


def test_link_with_access_key_lets_the_browser_in(client, monkeypatch):
    monkeypatch.setattr(web, "ACCESS_KEY", "s3cret-key")
    first = client.get("/?key=s3cret-key")
    assert first.status_code == 302 and first.headers["Location"] == "/"  # key removed from the address bar
    assert "tarjoushaukka_key=s3cret-key" in first.headers["Set-Cookie"] and "HttpOnly" in first.headers["Set-Cookie"]
    assert client.get("/").status_code == 200
    assert client.get("/api/list").status_code == 200


def test_access_key_is_read_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TARJOUSHAUKKA_ACCESS_KEY", raising=False)
    monkeypatch.setattr(web, "ACCESS_KEY_PATH", tmp_path / "access_key.txt")
    assert web.load_access_key() == ""
    (tmp_path / "access_key.txt").write_text("from-file\n", encoding="utf-8")
    assert web.load_access_key() == "from-file"
    monkeypatch.setenv("TARJOUSHAUKKA_ACCESS_KEY", "from-env")
    assert web.load_access_key() == "from-env"


def test_page_has_the_hawk_logo(client):
    page = client.get("/").get_data(as_text=True)
    logo = page[page.index('id="logo"'):page.index("</svg>", page.index('id="logo"'))]
    assert 'class="hawk"' in logo and 'class="hawk-tag"' in logo
    assert 'class="tag"' not in logo  # .tag is the sales list's price tag style, with its own clip shape
    assert "<ellipse" not in logo and "<rect" not in logo  # the old candies are gone
    icon = page[page.index('rel="icon"'):page.index('">', page.index('rel="icon"'))]
    assert "scale(.88)" in icon and "rotate(-30)" in icon  # the tab icon is the hawk too
