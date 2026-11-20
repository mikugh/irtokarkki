from irtokarkki import i18n, kesko, sgroup
from irtokarkki.core import matches
from irtokarkki.models import Deal, Store

STORE = Store(chain="K-Market", store_id="N1", name="K-Market Testi", location="Turku")
PRODUCT = {"id": "123", "localizedName": {"finnish": "Fazer Irttarit karkkipussi 400g",
                                          "swedish": "Fazer Irttarit godispåse 400g"}}


def normal(price):
    return {"unit": "kpl", "price": price}


def test_k_plain_discount():
    pricing = {"normal": normal(3.69), "discount": {"price": 2.99, "endDate": "2026-10-04T20:59:59.000Z",
                                                     "discountType": "STANDARD"}}
    deal = kesko._deal_from_pricing(STORE, PRODUCT, pricing)
    assert (deal.original_price, deal.discounted_price, deal.valid_until) == (3.69, 2.99, "2026-10-04")
    assert (deal.batch_amount, deal.plussa) == (1, False)
    assert i18n.note(deal, "fi") == ""
    assert deal.percent_off == 19


def test_k_batch_offer_is_per_item_price():
    pricing = {"normal": normal(2.75), "batch": {"price": 4.8, "amount": 2, "discountType": "PLUSSA"}}
    deal = kesko._deal_from_pricing(STORE, PRODUCT, pricing)
    assert deal.discounted_price == 2.4
    assert (deal.batch_amount, deal.batch_price, deal.plussa) == (2, 4.8, True)
    assert i18n.note(deal, "fi") == "2 kpl / 4,80 €, Plussa"
    assert i18n.note(deal, "sv") == "2 st / 4,80 €, Plussa"


def test_product_name_translations():
    pricing = {"normal": normal(3.69), "discount": {"price": 2.99}}
    deal = kesko._deal_from_pricing(STORE, PRODUCT, pricing)
    assert deal.product_in("fi") == "Fazer Irttarit karkkipussi 400g"
    assert deal.product_in("sv") == "Fazer Irttarit godispåse 400g"
    assert deal.product_in("en") == "Fazer Irttarit karkkipussi 400g"  # falls back to Finnish


def test_k_picks_best_offer_and_ignores_non_discounts():
    pricing = {"normal": normal(3.0), "libraryVersion": "4.0.2",
               "batch": {"price": 5.0, "amount": 2}, "discount": {"price": 2.0}}
    assert kesko._deal_from_pricing(STORE, PRODUCT, pricing).discounted_price == 2.0


def test_k_product_without_offer_has_current_price():
    deal = kesko._deal_from_pricing(STORE, PRODUCT, {"normal": normal(3.0), "libraryVersion": "x"})
    assert (deal.original_price, deal.discounted_price) == (3.0, 3.0)
    assert not deal.is_discounted
    assert deal.percent_off == 0
    assert kesko._deal_from_pricing(STORE, PRODUCT, {"libraryVersion": "x"}) is None


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
