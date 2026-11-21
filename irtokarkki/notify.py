import requests

from . import i18n
from .flyers import FlyerOffer
from .models import Deal


def flyer_line(offer: FlyerOffer, lang: str) -> str:
    price = f" {i18n.price(float(offer.price.replace(',', '.')), lang)}" if offer.price else ""
    return f"{offer.flyer.title}: {offer.description}{price}"


def _summary(deals: list[Deal], lang: str, flyer_offers: list[FlyerOffer] = ()) -> tuple[str, str]:
    n = len(deals) + len(flyer_offers)
    title = i18n.t(lang, "title_one") if n == 1 else i18n.t(lang, "title_many", n=n)
    # Pick-and-mix from the flyers first: that's what people most want to hear about.
    lines = [flyer_line(o, lang) for o in flyer_offers] + [
        f"{d.store.name}: {d.product_in(lang)} "
        f"{i18n.price(d.original_price, lang)} → {i18n.price(d.discounted_price, lang)}"
        for d in sorted(deals, key=lambda d: d.discounted_price)
    ]
    return title, "\n".join(lines)


def desktop(deals: list[Deal], lang: str = "fi", flyer_offers: list[FlyerOffer] = ()) -> None:
    try:
        from plyer import notification
    except ImportError:
        print("(plyer not installed, skipping desktop notification)")
        return
    title, body = _summary(deals, lang, flyer_offers)
    # Windows toasts are limited to ~256 characters.
    if len(body) > 250:
        body = body[:247] + "..."
    notification.notify(title=title, message=body, app_name="Irtokarkki", timeout=15)


def ntfy(deals: list[Deal], topic: str, server: str = "https://ntfy.sh", lang: str = "fi",
         flyer_offers: list[FlyerOffer] = ()) -> None:
    """Push to a phone via the ntfy app (https://ntfy.sh). Subscribe to the same topic in the app."""
    title, body = _summary(deals, lang, flyer_offers)
    requests.post(f"{server.rstrip('/')}/{topic}", data=body.encode("utf-8"),
                  headers={"Title": title.encode("utf-8"), "Tags": "candy"}, timeout=30)
