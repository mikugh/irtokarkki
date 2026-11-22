"""Check Finnish grocery stores for irtokarkki discounts and print them.

Usage:
    python -m irtokarkki                 # check once
    python -m irtokarkki --watch 6       # check every 6 hours
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from tabulate import tabulate

from . import flyers, i18n
from .core import ROOT, collect, load_config, load_favourites
from .models import Deal


def print_table(deals: list[Deal], lang: str) -> None:
    if not deals:
        print(i18n.t(lang, "no_deals"))
        return
    rows = [[
        d.store.chain, d.store.name, d.store.location_in(lang), d.product_in(lang),
        i18n.price(d.original_price, lang), i18n.price(d.discounted_price, lang), f"-{d.percent_off} %",
        i18n.date(d.valid_until, lang),
    ] for d in deals]
    print(tabulate(rows, headers=i18n.t(lang, "headers"), tablefmt="github"))


def flyer_line(offer: flyers.FlyerOffer, lang: str) -> str:
    price = f" {i18n.price(float(offer.price.replace(',', '.')), lang)}" if offer.price else ""
    return f"{offer.flyer.title}: {offer.description}{price}"


def check_flyers(config: dict, lang: str) -> list[flyers.FlyerOffer]:
    """Pick-and-mix offers in the configured flyer library (the [flyers] section of config.toml)."""
    cfg = config.get("flyers", {})
    if not cfg.get("enabled", True):
        return []
    library = cfg.get("library", "tok-ilmoitukset")
    try:
        offers = flyers.check(library, cfg.get("keywords", ["irtomakeis", "irtokark", "irtonamu"]))
    except Exception as e:
        print(i18n.t(lang, "flyers_failed", e=e))
        return []
    print()
    if offers:
        print(i18n.t(lang, "flyers_title", source=library))
        for offer in offers:
            print(f"  {flyer_line(offer, lang)}  {offer.flyer.url}")
    else:
        print(i18n.t(lang, "flyers_none"))
    return offers


def run_once(config: dict) -> None:
    lang = config.get("language", "fi")
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] {i18n.t(lang, 'checking')}")
    _, prices, _ = collect(config, load_favourites())
    print_table([p for p in prices if p.is_discounted], lang)
    check_flyers(config, lang)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--watch", type=float, metavar="HOURS", help="keep running, checking every HOURS")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Finnish letters in the Windows console

    config = load_config(args.config)
    while True:
        run_once(config)
        if not args.watch:
            break
        time.sleep(args.watch * 3600)


if __name__ == "__main__":
    main()
