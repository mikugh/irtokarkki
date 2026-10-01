"""Translations for the command line tool and notifications. The web UI has its own in static/index.html."""
from .models import Deal

LANGUAGES = ("fi", "sv", "en")

STRINGS = {
    "fi": {
        "checking": "Etsitään irtokarkkitarjouksia...",
        "no_deals": "Irtokarkkitarjouksia ei löytynyt juuri nyt.",
        "notified": "Ilmoitettu {n} uudesta tarjouksesta.",
        "title_one": "Irtokarkkia tarjouksessa! (1 uusi tarjous)",
        "title_many": "Irtokarkkia tarjouksessa! ({n} uutta tarjousta)",
        "headers": ["Ketju", "Kauppa", "Sijainti", "Tuote", "Normaalihinta", "Tarjoushinta", "Ale", "Voimassa", "Huom."],
        "pcs": "kpl",
    },
    "sv": {
        "checking": "Söker erbjudanden på lösgodis...",
        "no_deals": "Inga erbjudanden på lösgodis just nu.",
        "notified": "Meddelade om {n} nya erbjudanden.",
        "title_one": "Lösgodis på rea! (1 nytt erbjudande)",
        "title_many": "Lösgodis på rea! ({n} nya erbjudanden)",
        "headers": ["Kedja", "Butik", "Plats", "Produkt", "Ordinarie pris", "Erbjudande", "Rabatt", "Gäller till", "Obs."],
        "pcs": "st",
    },
    "en": {
        "checking": "Checking for irtokarkki discounts...",
        "no_deals": "No irtokarkki discounts found right now.",
        "notified": "Notified about {n} new deal(s).",
        "title_one": "Irtokarkki on sale! (1 new deal)",
        "title_many": "Irtokarkki on sale! ({n} new deals)",
        "headers": ["Chain", "Store", "Location", "Product", "Original", "Discounted", "Off", "Valid until", "Note"],
        "pcs": "pcs",
    },
}


def t(lang: str, key: str, **kwargs):
    value = STRINGS.get(lang, STRINGS["fi"])[key]
    return value.format(**kwargs) if isinstance(value, str) else value


def price(value: float, lang: str) -> str:
    text = f"{value:.2f}"
    return (text if lang == "en" else text.replace(".", ",")) + " €"


def date(iso: str, lang: str) -> str:
    if not iso:
        return ""
    y, m, d = iso.split("-")
    return f"{y}-{m}-{d}" if lang == "en" else f"{int(d)}.{int(m)}.{y}"


def note(deal: Deal, lang: str) -> str:
    parts = []
    if deal.batch_amount > 1:
        parts.append(f"{deal.batch_amount} {t(lang, 'pcs')} / {price(deal.batch_price, lang)}")
    if deal.plussa:
        parts.append("Plussa")
    return ", ".join(parts)
