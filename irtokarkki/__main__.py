"""Check Finnish grocery stores for irtokarkki discounts and notify about new ones.

Usage:
    python -m irtokarkki                 # check once
    python -m irtokarkki --watch 6       # check every 6 hours
    python -m irtokarkki --no-notify     # just print the table
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from tabulate import tabulate

from . import i18n, notify
from .core import ROOT, collect, load_config, load_favourites
from .models import Deal


def print_table(deals: list[Deal], lang: str) -> None:
    if not deals:
        print(i18n.t(lang, "no_deals"))
        return
    rows = [[
        d.store.chain, d.store.name, d.store.location_in(lang), d.product_in(lang),
        i18n.price(d.original_price, lang), i18n.price(d.discounted_price, lang), f"-{d.percent_off} %",
        i18n.date(d.valid_until, lang), i18n.note(d, lang),
    ] for d in deals]
    print(tabulate(rows, headers=i18n.t(lang, "headers"), tablefmt="github"))


def run_once(config: dict, send_notifications: bool) -> None:
    state_path = ROOT / "seen_deals.json"
    seen = set(json.loads(state_path.read_text())) if state_path.exists() else set()

    lang = config.get("language", "fi")
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] {i18n.t(lang, 'checking')}")
    favourites = load_favourites()
    _, prices, _ = collect(config, favourites)
    deals = [p for p in prices if p.is_discounted]
    print_table(deals, lang)

    if not send_notifications:
        return

    new = [d for d in deals if d.key not in seen]
    if favourites and config.get("notify", {}).get("only_favourites", True):
        new = [d for d in new if d.store.key in favourites]
    if new:
        notify_cfg = config.get("notify", {})
        if notify_cfg.get("desktop", True):
            notify.desktop(new, lang)
        if notify_cfg.get("ntfy_topic"):
            notify.ntfy(new, notify_cfg["ntfy_topic"], notify_cfg.get("ntfy_server", "https://ntfy.sh"), lang)
        print(i18n.t(lang, "notified", n=len(new)))

    # Only remember currently active deals, so a deal that ends and comes back is notified again.
    state_path.write_text(json.dumps(sorted(d.key for d in deals), indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--watch", type=float, metavar="HOURS", help="keep running, checking every HOURS")
    parser.add_argument("--no-notify", action="store_true", help="only print, don't send notifications")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # Finnish letters in the Windows console

    config = load_config(args.config)
    while True:
        run_once(config, send_notifications=not args.no_notify)
        if not args.watch:
            break
        time.sleep(args.watch * 3600)


if __name__ == "__main__":
    main()
