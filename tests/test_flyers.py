from tarjoushaukka import flyers
from tarjoushaukka.flyers import Flyer

LIBRARY_HTML = """
<div id="publications">
  <div class="publication-item publication-info">
    <div href="/tok-ilmoitukset/s-mobiiliedut-prisma-15-30112026" title="S-mobiiliedut">
      <div class="info-wrapper">
        <h3 class="publication-title">S-mobiiliedut Prisma 15.-30.11.2026</h3>
        <span class="created">Julkaistu: 15.11.2026</span>
        <div class="pdf open-btn"> <a href="/downloadpdf/68afa9c2ede530296f8d0e3e641cea73">PDF ></a> </div>
        <div class="read open-btn"><a href="/tok-ilmoitukset/s-mobiiliedut-prisma-15-30112026">Lue ></a></div>
      </div>
    </div>
  </div>
  <div class="publication-item publication-info">
    <div href="/tok-ilmoitukset/tok-prisma-182211" title="TOK Prisma 18.&ndash;22.11.">
      <div class="info-wrapper">
        <h3 class="publication-title">TOK Prisma 18.&ndash;22.11.</h3>
        <span class="created">Julkaistu: 18.11.2026</span>
        <div class="pdf open-btn"> <a href="/downloadpdf/e3ebcc25009b3c69244a8fce25e974b4">PDF ></a> </div>
        <div class="read open-btn"><a href="/tok-ilmoitukset/tok-prisma-182211">Lue ></a></div>
      </div>
    </div>
  </div>
</div>
"""

FLYER = Flyer("e3ebcc25009b3c69244a8fce25e974b4", "TOK Prisma 18.–22.11.", "2026-11-18",
              "https://view.sok-julkaisut.fi/tok-ilmoitukset/tok-prisma-182211")


def word(text, x0, y0, x1, y1):
    return {"word": text, "box": [x0, y0, x1, y1]}


# Two offer tiles side by side, laid out like a real flyer: a big price on the left of the text.
PAGE = [
    word("3", 532, 670, 586, 748), word("99", 587, 704, 645, 745),
    word("Voim.", 666, 778, 706, 795), word("18.–22.11.", 710, 778, 769, 795),
    word("Kotimaista", 666, 757, 740, 774), word("kirjolohi", 666, 734, 740, 753),
    word("5", 950, 670, 1011, 748), word("90", 1012, 704, 1071, 745),
    word("Voim.", 1091, 778, 1131, 795), word("la", 1135, 778, 1150, 795), word("21.11.", 1154, 778, 1200, 795),
    word("Irto-", 1091, 757, 1131, 774), word("makeiset", 1091, 734, 1170, 753),
    word("kg", 1091, 713, 1110, 730),
]


def test_parse_library_page():
    parsed = flyers.parse_library_page(LIBRARY_HTML, "tok-ilmoitukset")
    assert [f.title for f in parsed] == ["S-mobiiliedut Prisma 15.-30.11.2026", "TOK Prisma 18.–22.11."]
    assert parsed[0].published == "2026-11-15"  # from "Julkaistu", not the dates in the title
    assert parsed[1] == FLYER


def test_tiles_split_offers_apart():
    texts = [" ".join(w["word"] for w in tile) for tile in flyers.tiles(PAGE)]
    assert texts == ["3 99 Voim. 18.–22.11. Kotimaista kirjolohi",
                     "5 90 Voim. la 21.11. Irto- makeiset kg"]


def test_find_offers_matches_hyphenated_words():
    offers = flyers.find_offers(FLYER, [PAGE], ["irtomakeis", "irtonamu"])
    assert len(offers) == 1
    assert offers[0].price == "5,90"
    assert offers[0].text.startswith("5 90 Voim. la 21.11.")
    assert offers[0].flyer == FLYER


def test_find_offers_nothing_found():
    assert flyers.find_offers(FLYER, [PAGE], ["irtonamu"]) == []


def test_check_fetches_each_flyer_once(monkeypatch):
    fetched = []
    monkeypatch.setattr(flyers, "list_flyers", lambda library: [FLYER])
    monkeypatch.setattr(flyers, "flyer_pages", lambda library, doc_id: fetched.append(doc_id) or [PAGE])
    cache = {}
    assert len(flyers.check("tok-ilmoitukset", ["irtomakeis"], cache)) == 1
    assert len(flyers.check("tok-ilmoitukset", ["irtomakeis"], cache)) == 1
    assert fetched == [FLYER.doc_id]


OFFER = flyers.FlyerOffer(FLYER, "5 90 Voim. la 21.11. Irto- makeiset kg", "5,90")


def test_offer_description_and_printed_line():
    from tarjoushaukka.__main__ import flyer_line
    assert OFFER.description == "Voim. la 21.11. Irto- makeiset kg"
    assert flyer_line(OFFER, "fi") == "TOK Prisma 18.–22.11.: Voim. la 21.11. Irto- makeiset kg 5,90 €"
    assert flyer_line(OFFER, "en") == "TOK Prisma 18.–22.11.: Voim. la 21.11. Irto- makeiset kg 5.90 €"


def test_flyer_matches_ignores_case_hyphens_and_spaces():
    assert flyers.matches("5 90 Voim. la 21.11. Irto- makeiset kg", "irtomakeis")
    assert flyers.matches("5 90 Voim. la 21.11. Irto- makeiset kg", "Irto Makeis")
    assert not flyers.matches("Kotimaista kirjolohi", "irtomakeis")
