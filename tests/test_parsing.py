from irtokarkki import sgroup
from irtokarkki.core import matches
from irtokarkki.models import Deal, Store

STORE = Store(chain="S-market", store_id="1", name="S-market Testi", location="Turku", source="s_group")


def test_product_name_translations():
    deal = Deal(STORE, "1", "Fazer Irttarit karkkipussi 400g", 3.69, 2.99,
                product_names={"sv": "Fazer Irttarit godispåse 400g"})
    assert deal.product_in("fi") == "Fazer Irttarit karkkipussi 400g"
    assert deal.product_in("sv") == "Fazer Irttarit godispåse 400g"
    assert deal.product_in("en") == "Fazer Irttarit karkkipussi 400g"  # falls back to Finnish
    assert deal.percent_off == 19


def test_s_group_prefers_big_stores_in_city(monkeypatch):
    # The API lists stores grouped by brand, small Sale shops first.
    def s(chain, n, city="Turku"):
        return Store(chain=chain, store_id=f"{chain}{n}", name=f"{chain} {n}",
                     location=f"Katu 1, 20100 {city}", source="s_group")
    results = ([s("ABC", 1, "Salo")] + [s("Sale", i) for i in range(5)]
               + [s("Prisma", i) for i in range(2)] + [s("S-market", i) for i in range(2)])
    monkeypatch.setattr(sgroup, "search_stores", lambda query: results)

    picked = sgroup.find_stores("Turku", 5)
    assert [p.store_id for p in picked] == ["Prisma0", "Prisma1", "S-market0", "S-market1", "Sale0"]


def test_name_keyword_filter():
    deal = Deal(STORE, "1", "Candy King irtomakeismix 620g", 12.95, 7.99)
    assert matches(deal, ["irtomakeis"])
    assert not matches(deal, ["salmiakki"])
    assert matches(deal, [])


STORE2 = Store(chain="Prisma", store_id="2", name="Prisma Testi", location="Turku", source="s_group")


def test_lookup_products_batches_and_skips_missing(monkeypatch):
    queries = []

    def fake_post(query, variables=None, lang=None):
        queries.append(query)
        return {"p0": {"id": "6411300000494", "name": "Juhla Mokka 500g", "priceUnit": "KPL",
                       "pricing": {"campaignPrice": 6.99, "regularPrice": 8.89,
                                   "campaignPriceValidUntil": "2026-11-24T21:59:59Z"}},
                "p1": None}  # a product this store doesn't sell, or that no longer exists

    monkeypatch.setattr(sgroup, "_post", fake_post)
    deals = sgroup.lookup_products([STORE], ["6411300000494", "0000000000000"])
    assert len(queries) == 1 and 'product(id: "6411300000494", storeId: "1")' in queries[0]
    assert [(d.store, d.product_id, d.discounted_price, d.original_price, d.valid_until) for d in deals] == [
        (STORE, "6411300000494", 6.99, 8.89, "2026-11-24")]


def test_lookup_products_uses_at_most_20_aliases_per_request(monkeypatch):
    calls = []
    monkeypatch.setattr(sgroup, "_post", lambda q, v=None, lang=None: calls.append(q.count("product(")) or {})
    sgroup.lookup_products([STORE, STORE2], [str(i).zfill(13) for i in range(15)])
    assert calls == [20, 10]


def test_search_products_returns_current_prices(monkeypatch):
    items = [{"id": str(i), "name": f"kahvi {i}", "priceUnit": "KPL",
              "pricing": {"campaignPrice": None, "regularPrice": 5.0, "campaignPriceValidUntil": None}} for i in range(30)]
    monkeypatch.setattr(sgroup, "_post", lambda q, v=None, lang=None: {"s0": {"products": {"items": items}}})
    found = sgroup.search_products(STORE, "kahvi", limit=20)
    assert len(found) == 20 and found[0].product == "kahvi 0" and not found[0].is_discounted


def test_lookup_products_stops_at_the_deadline(monkeypatch):
    import time
    import pytest
    calls = []
    monkeypatch.setattr(sgroup, "_post", lambda q, v=None, lang=None: calls.append(q) or {})
    with pytest.raises(TimeoutError):
        sgroup.lookup_products([STORE], [str(i).zfill(13) for i in range(50)], deadline=time.monotonic() - 1)
    assert calls == []
