"""Logic shared by the command line tool and the web UI."""
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

from . import kesko, sgroup
from .models import Deal, Store

ROOT = Path(__file__).resolve().parent.parent
FAVOURITES_PATH = ROOT / "favourites.json"
SOURCES = {"s_group": sgroup, "k_group": kesko}


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
    """Search stores from all chains by name or city."""
    stores = []
    for source in SOURCES.values():
        try:
            stores += source.search_stores(query)
        except Exception as e:
            print(f"store search failed: {e}")
    return stores


def collect(config: dict, favourites: dict[str, Store], city: str | None = None,
            log=print) -> tuple[list[Store], list[Deal], list[str]]:
    """Find irtokarkki prices in the configured stores plus all favourite stores.

    Returns every store that was checked, the current price of each irtokarkki product
    in them (discounted or not, see Deal.is_discounted) and any errors.
    """
    stores_cfg, search_cfg = config["stores"], config["search"]
    city = city or stores_cfg["city"]
    try:
        city = sgroup.finnish_city_name(city)
    except Exception:
        pass  # use the name as given
    all_stores: list[Store] = []
    found: dict[tuple, Deal] = {}
    errors: list[str] = []

    for source_name, source in SOURCES.items():
        source_cfg = stores_cfg.get(source_name, {})
        if not source_cfg.get("enabled", True):
            continue
        try:
            ids = source_cfg.get("store_ids") or []
            stores = (source.get_stores(ids) if ids
                      else source.find_stores(city, stores_cfg.get("max_stores_per_chain", 10)))
            # Always check favourite stores, even when they're in another city.
            checked = {s.store_id for s in stores}
            missing = [f.store_id for f in favourites.values()
                       if f.source == source_name and f.store_id not in checked]
            if missing:
                stores += source.get_stores(missing)
            log(f"{source_name}: checking {len(stores)} stores")
            all_stores += stores

            source_found: dict[tuple, Deal] = {}
            for term in search_cfg["terms"]:
                for deal in source.find_prices(stores, term):
                    if matches(deal, search_cfg.get("name_keywords", [])):
                        # The same product shows up under several search terms; keep one per store.
                        source_found[(deal.store.key, deal.product_id)] = deal
            for deal in source.translate(list(source_found.values())):
                found[(deal.store.key, deal.product_id)] = deal
        except Exception as e:  # one chain failing shouldn't stop the other
            errors.append(f"{source_name}: {e}")
            log(f"{source_name}: failed: {e}")

    deals = sorted(found.values(), key=lambda d: (d.discounted_price, d.store.name))
    return all_stores, deals, errors
