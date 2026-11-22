import pytest

from irtokarkki import flyers, sgroup, shopping
from irtokarkki.flyers import Flyer, FlyerOffer
from irtokarkki.models import Deal, Store

HALINEN = Store(chain="S-market", store_id="603212622", name="S-market Halinen", location="Turku", source="s_group")
JUHLA = "6411300000494"
FLYER = Flyer("e3eb", "TOK Prisma 18.–22.11.", "2026-11-18", "https://view.sok-julkaisut.fi/tok-ilmoitukset/tok-prisma-182211")


class Fakes:
    def __init__(self):
        self.flyer_keywords = []
        self.flyers_fail = False
        self.catalog = [
            Deal(HALINEN, JUHLA, "Paulig Juhla Mokka kahvi 500g", 8.89, 6.99, valid_until="2026-11-24"),
            Deal(HALINEN, "6410", "Kulta Katriina suodatinkahvi 500g", 5.29, 3.95, valid_until="2026-11-22"),
            Deal(HALINEN, "6420", "Presidentti kahvi 500g", 6.49, 6.49),  # not on sale
            Deal(HALINEN, "6430", "Fazer Remix Irttarit karkkipussi 400g", 3.69, 2.99, valid_until="2026-11-30"),
        ]

    def lookup(self, stores, eans, deadline=None):
        return [d for d in self.catalog if d.product_id in eans and d.store in stores]

    def find_prices(self, stores, term):
        # The real search is fuzzy: it returns more than the word, so the code must filter by name.
        return [d for d in self.catalog if d.store in stores]

    def check(self, library, keywords, cache=None):
        self.flyer_keywords.append(list(keywords))
        if self.flyers_fail:
            raise RuntimeError("site down")
        return [FlyerOffer(FLYER, "5 90 Voim. la 21.11. Irto- makeiset kg", "5,90"),
                FlyerOffer(FLYER, "3 99 Kotimaista kirjolohi", "3,99")]


@pytest.fixture
def fakes(monkeypatch):
    f = Fakes()
    monkeypatch.setattr(sgroup, "lookup_products", f.lookup)
    monkeypatch.setattr(sgroup, "find_prices", f.find_prices)
    monkeypatch.setattr(flyers, "check", f.check)
    return f


def test_parse_items_rejects_junk_and_caps():
    items = shopping.parse_items([
        {"type": "word", "text": "  Kahvi ", "flyers": False},
        {"type": "word", "text": "ka"},  # too short: would match nearly everything
        {"type": "word", "text": "kahvi"},  # duplicate
        {"type": "word", "text": "x" * 41},  # too long
        {"type": "product", "ean": JUHLA, "name": "Juhla Mokka 500g"},
        {"type": "product", "ean": "abc", "name": "x"},
        {"type": "product", "ean": JUHLA, "name": "again"},  # duplicate
        {"type": "nope"},
        "nope",
    ])
    assert items == [{"type": "word", "text": "kahvi", "flyers": False},
                     {"type": "product", "ean": JUHLA, "name": "Juhla Mokka 500g"}]
    assert shopping.parse_items([{"type": "word", "text": "maito"}]) == [{"type": "word", "text": "maito", "flyers": False}]
    assert len(shopping.parse_items([{"type": "word", "text": f"sana{i}"} for i in range(500)])) == shopping.MAX_ITEMS
    assert shopping.parse_items({"not": "a list"}) == []


def test_default_list_is_todays_pick_and_mix_stems():
    assert shopping.DEFAULT_LIST == [{"type": "word", "text": t, "flyers": True}
                                     for t in ("irtokark", "irtomakeis", "irtonamu", "irttari")]
    assert shopping.parse_items(shopping.DEFAULT_LIST) == shopping.DEFAULT_LIST


def test_product_and_word_sales_with_dedupe(fakes):
    sales, errors = shopping.check_list(
        [{"type": "product", "ean": JUHLA, "name": "Juhla Mokka 500g"},
         {"type": "word", "text": "kahvi", "flyers": False}],
        [HALINEN], "tok-ilmoitukset", {})
    assert errors == []
    assert [(s.item, s.item_type, s.product, s.price, s.regular_price, s.place, s.until) for s in sales] == [
        ("Juhla Mokka 500g", "product", "Paulig Juhla Mokka kahvi 500g", 6.99, 8.89, "S-market Halinen", "2026-11-24"),
        ("kahvi", "word", "Kulta Katriina suodatinkahvi 500g", 3.95, 5.29, "S-market Halinen", "2026-11-22"),
    ]  # Juhla Mokka isn't repeated under "kahvi"; Presidentti isn't on sale
    assert fakes.flyer_keywords == []  # no word has flyers on: flyers aren't read at all


def test_flyers_only_for_words_with_flyers_on(fakes):
    sales, _ = shopping.check_list([{"type": "word", "text": "irtomakeis", "flyers": True},
                                    {"type": "word", "text": "kirjolohi", "flyers": False}],
                                   [HALINEN], "tok-ilmoitukset", {})
    flyer_sales = [s for s in sales if s.url == FLYER.url]
    assert [(s.item, s.price, s.regular_price, s.place, s.until) for s in flyer_sales] == [
        ("irtomakeis", 5.9, None, "TOK Prisma 18.–22.11.", "")]
    assert fakes.flyer_keywords == [["irtomakeis"]]


def test_source_failure_is_reported_and_others_still_count(fakes):
    fakes.flyers_fail = True
    sales, errors = shopping.check_list([{"type": "word", "text": "kahvi", "flyers": True}],
                                        [HALINEN], "tok-ilmoitukset", {})
    assert errors == ["flyers: site down"]
    assert [s.product for s in sales] == ["Kulta Katriina suodatinkahvi 500g", "Paulig Juhla Mokka kahvi 500g"]  # cheapest first


def test_no_stores_still_checks_flyers(fakes):
    sales, errors = shopping.check_list([{"type": "word", "text": "irtomakeis", "flyers": True}], [], "tok-ilmoitukset", {})
    assert errors == [] and [s.item for s in sales] == ["irtomakeis"]


def test_parse_stores_accepts_only_numeric_ids():
    good = {"source": "s_group", "store_id": "603212622", "name": "S-market Halinen"}
    bad = {"source": "s_group", "store_id": '1") { id } x: store(id: "2', "name": "x"}
    assert [s.store_id for s in shopping.parse_stores([good, bad, good])] == ["603212622"]
    assert len(shopping.parse_stores([{**good, "store_id": str(i)} for i in range(100)])) == shopping.MAX_STORES


def test_words_need_three_letters_or_digits():
    assert shopping.parse_items([{"type": "word", "text": "- -"}, {"type": "word", "text": "a b"},
                                 {"type": "word", "text": "--x"}]) == []
    assert shopping.parse_items([{"type": "word", "text": "irto-k"}])[0]["text"] == "irto-k"


def test_check_stops_at_the_deadline(fakes, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(shopping.time, "monotonic", lambda: now[0])

    def slow_find(stores, term):
        now[0] += 60  # each word search takes a minute
        return fakes.find_prices(stores, term)
    monkeypatch.setattr(sgroup, "find_prices", slow_find)
    words = [{"type": "word", "text": f"kahvi{i}", "flyers": False} for i in range(10)]
    sales, errors = shopping.check_list(words, [HALINEN], "tok-ilmoitukset", {}, budget=150)
    assert errors == ["s_group: timed out"]
    assert now[0] <= 100 + 150 + 60 * 4  # stops starting searches once the budget is spent (4 threads in flight)
