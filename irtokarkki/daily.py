"""The daily check: once a morning, tell the owner's phone about sales they haven't heard of yet.

Vercel Cron calls /api/cron/daily, which runs run(). The "notified" set in storage holds the
sales already messaged; it's replaced by today's sales after a fully successful check, so a sale
that ends and later comes back is messaged again.
"""
from datetime import datetime

from . import notify, shopping


def run(storage, topic: str, server: str = "https://ntfy.sh", library: str = "tok-ilmoitukset",
        check=shopping.check_list, send=notify.ntfy_send) -> dict:
    items = storage.get("list")
    items = shopping.DEFAULT_LIST if items is None else shopping.parse_items(items)
    stores = shopping.parse_stores(storage.get("stores"))
    sales, errors = check(items, stores, library, {}) if items else ([], [])
    storage.set("last_check", datetime.now().astimezone().isoformat(timespec="minutes"))

    notified = storage.get("notified")
    known = set(notified or [])
    new = [s for s in sales if s.key not in known]
    sent = False
    if new and topic:
        try:
            send(*notify.sales_message(new), topic, server)
            sent = True
        except Exception as e:
            errors = [*errors, f"ntfy: {e}"]
            return {"sales": len(sales), "new": len(new), "sent": False, "errors": errors}
    if new and not sent:  # no topic: nothing was told, so nothing is marked as told
        return {"sales": len(sales), "new": len(new), "sent": False, "errors": errors}

    if errors:  # part of the check failed: today's list is incomplete, so keep what was known
        storage.set("notified", sorted(known | {s.key for s in new}))
    else:
        storage.set("notified", sorted({s.key for s in sales}))
    return {"sales": len(sales), "new": len(new), "sent": sent, "errors": errors}
