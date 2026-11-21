"""Logic shared by the command line tool and the web UI."""
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

from . import sgroup
from .models import Deal, Store

ROOT = Path(__file__).resolve().parent.parent
FAVOURITES_PATH = ROOT / "favourites.json"
SOURCES = {"s_group": sgroup}


def load_config(path: Path = ROOT / "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_favourites() -> dict[str, Store]:
    if not FAVOURITES_PATH.exists():
        return {}
    stores = [Store(**s) for s in json.loads(FAVOURITES_PATH.read_text(encoding="utf-8"))]
    return {s.key: s for s in stores}


def save_favourites(favourites: dict[str, Store]) -> None:
    FAVOURITES_PATH.write_text(
        json.dumps([asdict(s) for s in favourites.values()], indent=1, ensure_ascii=False),
        encoding="utf-8",
    )


def matches(deal: Deal, keywords: list[str]) -> bool:
    if not keywords:
        return True
    name = deal.product.lower()
    return any(k.lower() in name for k in keywords)


def search_stores(query: str) -> list[Store]:
    """Search stores by name or city."""
    stores = []
    for source in SOURCES.values():
        try:
            stores += source.search_stores(query)
        except Exception as e:
            print(f"store search failed: {e}")
    return stores


def enabled_sources(config: dict) -> dict:
    stores_cfg = config["stores"]
    return {name: source for name, source in SOURCES.items()
            if stores_cfg.get(name, {}).get("enabled", True)}


def city_stores(config: dict, city: str | None = None) -> tuple[list[Store], list[str]]:
    """The stores to check in `city` (or the configured store_ids), and any errors."""
    stores_cfg = config["stores"]
    city = city or stores_cfg["city"]
    try:
        city = sgroup.finnish_city_name(city)
    except Exception:
        pass  # use the name as given
    stores: list[Store] = []
    errors: list[str] = []
    for source_name, source in enabled_sources(config).items():
        try:
            ids = stores_cfg.get(source_name, {}).get("store_ids") or []
            stores += (source.get_stores(ids) if ids
                       else source.find_stores(city, stores_cfg.get("max_stores_per_chain", 10)))
        except Exception as e:  # one chain failing shouldn't stop the other
            errors.append(f"{source_name}: {e}")
    return stores, errors


def fetch_prices(config: dict, stores: list[Store], log=print) -> tuple[list[Deal], list[str], set[str]]:
    """The current price of each irtokarkki product in `stores` (discounted or not, see
    Deal.is_discounted), any errors, and the sources (chains) that failed."""
    search_cfg = config["search"]
    found: dict[tuple, Deal] = {}
    errors: list[str] = []
    failed: set[str] = set()
    for source_name, source in enabled_sources(config).items():
        source_stores = [s for s in stores if s.source == source_name]
        if not source_stores:
            continue
        log(f"{source_name}: checking {len(source_stores)} stores")
        try:
            source_found: dict[tuple, Deal] = {}
            for term in search_cfg["terms"]:
                for deal in source.find_prices(source_stores, term):
                    if matches(deal, search_cfg.get("name_keywords", [])):
                        # The same product shows up under several search terms; keep one per store.
                        source_found[(deal.store.key, deal.product_id)] = deal
            for deal in source.translate(list(source_found.values())):
                found[(deal.store.key, deal.product_id)] = deal
        except Exception as e:  # one chain failing shouldn't stop the other
            errors.append(f"{source_name}: {e}")
            failed.add(source_name)
            log(f"{source_name}: failed: {e}")
    deals = sorted(found.values(), key=lambda d: (d.discounted_price, d.store.name))
    return deals, errors, failed


def collect(config: dict, favourites: dict[str, Store], city: str | None = None,
            log=print) -> tuple[list[Store], list[Deal], list[str]]:
    """Find irtokarkki prices in the configured stores plus all favourite stores.

    Returns every store that was checked, the current price of each irtokarkki product
    in them (discounted or not, see Deal.is_discounted) and any errors.
    """
    stores, errors = city_stores(config, city)
    # Always check favourite stores, even when they're in another city.
    for source_name, source in enabled_sources(config).items():
        checked = {s.store_id for s in stores if s.source == source_name}
        missing = [f.store_id for f in favourites.values()
                   if f.source == source_name and f.store_id not in checked]
        if missing:
            try:
                stores += source.get_stores(missing)
            except Exception as e:
                errors.append(f"{source_name}: {e}")
    deals, price_errors, _ = fetch_prices(config, stores, log)
    return stores, deals, errors + price_errors
