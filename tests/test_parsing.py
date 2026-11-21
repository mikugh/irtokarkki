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
