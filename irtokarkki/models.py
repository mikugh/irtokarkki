from dataclasses import dataclass, field


@dataclass(frozen=True)
class Store:
    chain: str  # e.g. "Prisma", "S-market"
    store_id: str
    name: str
    location: str  # street address and/or city
    map_url: str = ""
    source: str = ""  # "s_group"
    location_sv: str = ""  # Swedish version of `location`, when the store provides one

    @property
    def key(self) -> str:
        return f"{self.source}:{self.store_id}"

    def location_in(self, lang: str) -> str:
        return (self.location_sv if lang == "sv" else "") or self.location


@dataclass(frozen=True)
class Deal:
    """A product's current price in a store. It's on sale when discounted_price < original_price."""
    store: Store
    product_id: str
    product: str  # Finnish name
    original_price: float
    discounted_price: float  # current price per item; same as original_price when not on sale
    unit: str = "kpl"
    valid_until: str = ""  # ISO date, if known
    product_names: dict = field(default_factory=dict, compare=False)  # {"sv": ..., "en": ...}

    def product_in(self, lang: str) -> str:
        return self.product_names.get(lang) or self.product

    @property
    def is_discounted(self) -> bool:
        return self.discounted_price < self.original_price

    @property
    def percent_off(self) -> int:
        if self.original_price <= 0:
            return 0
        return round(100 * (1 - self.discounted_price / self.original_price))
