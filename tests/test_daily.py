from irtokarkki import daily, notify, shopping
from irtokarkki.shopping import Sale
from irtokarkki.storage import MemoryStorage

HALINEN_JSON = {"chain": "S-market", "store_id": "603212622", "name": "S-market Halinen", "location": "Turku",
                "map_url": "", "source": "s_group", "location_sv": ""}
JUHLA_SALE = Sale("Juhla Mokka 500g", "product", "Paulig Juhla Mokka kahvi 500g", 6.99, 8.89, "S-market Halinen",
                  "https://www.s-kaupat.fi/tuote/6411300000494", "2026-11-24", "Juhla|6411300000494|603212622|6.99|2026-11-24")
KAHVI_SALE = Sale("kahvi", "word", "Kulta Katriina suodatinkahvi 500g", 3.95, 5.29, "S-market Halinen",
                  "https://www.s-kaupat.fi/tuote/6410", "2026-11-22", "kahvi|6410|603212622|3.95|2026-11-22")
FLYER_SALE = Sale("irtomakeis", "word", "Voim. la 21.11. Irto- makeiset kg", None, None, "TOK Prisma 18.–22.11.",
                  "https://view.sok-julkaisut.fi/x", "", "irtomakeis|flyer|e3eb|text")


def fake_check(sales, errors=()):
    calls = []

    def check(items, stores, library, flyer_pages):
        calls.append((items, stores, library))
        return list(sales), list(errors)
    check.calls = calls
    return check


def record(sent):
    return lambda title, body, topic, server="https://ntfy.sh": sent.append((title, body, topic))


def storage_with_store():
    s = MemoryStorage()
    s.set("stores", [HALINEN_JSON])
    return s


def test_message_is_finnish():
    title, body = notify.sales_message([JUHLA_SALE, KAHVI_SALE, FLYER_SALE])
    assert title == "3 uutta tarjousta"
    assert body == ("Juhla Mokka 500g 6,99 € (S-market Halinen)\n"
                    "kahvi: Kulta Katriina suodatinkahvi 500g 3,95 € (S-market Halinen)\n"
                    "irtomakeis: Voim. la 21.11. Irto- makeiset kg (TOK Prisma 18.–22.11.)")
    assert notify.sales_message([JUHLA_SALE])[0] == "1 uusi tarjous"


def test_long_message_is_cut_short():
    many = [Sale("kahvi", "word", f"Kahvi {i}", 3.0, 4.0, "S-market Halinen", "", "", str(i)) for i in range(40)]
    _, body = notify.sales_message(many)
    lines = body.split("\n")
    assert len(lines) == notify.MAX_LINES + 1 and lines[-1] == "…ja 25 muuta"


def test_sends_only_new_and_twice_a_day_sends_nothing():
    s, sent = storage_with_store(), []
    first = daily.run(s, "topic", check=fake_check([JUHLA_SALE]), send=record(sent))
    second = daily.run(s, "topic", check=fake_check([JUHLA_SALE]), send=record(sent))
    assert first == {"sales": 1, "new": 1, "sent": True, "errors": []}
    assert second == {"sales": 1, "new": 0, "sent": False, "errors": []}
    assert len(sent) == 1 and sent[0][2] == "topic"
    assert s.get("last_check")


def test_uses_the_stored_list_or_the_default_and_the_stores():
    s = storage_with_store()
    check = fake_check([])
    daily.run(s, "topic", library="tok-ilmoitukset", check=check, send=record([]))
    items, stores, library = check.calls[0]
    assert items == shopping.DEFAULT_LIST and [st.store_id for st in stores] == ["603212622"]
    assert library == "tok-ilmoitukset"


def test_partial_failure_keeps_old_entries_and_adds_new():
    s, sent = storage_with_store(), []
    s.set("notified", ["old|key"])
    result = daily.run(s, "topic", check=fake_check([JUHLA_SALE], errors=["flyers: site down"]), send=record(sent))
    assert result["errors"] == ["flyers: site down"] and result["sent"]
    assert set(s.get("notified")) == {"old|key", JUHLA_SALE.key}


def test_full_success_replaces_the_set():
    s = storage_with_store()
    s.set("notified", ["old|key", JUHLA_SALE.key])
    daily.run(s, "topic", check=fake_check([JUHLA_SALE, KAHVI_SALE]), send=record([]))
    assert sorted(s.get("notified")) == sorted([JUHLA_SALE.key, KAHVI_SALE.key])
    daily.run(s, "topic", check=fake_check([]), send=record([]))
    assert s.get("notified") == []  # a sale that ends and comes back is notified again


def test_no_topic_does_not_mark_as_notified():
    s = storage_with_store()
    result = daily.run(s, "", check=fake_check([JUHLA_SALE]), send=record([]))
    assert result == {"sales": 1, "new": 1, "sent": False, "errors": []}
    assert s.get("notified") is None


def test_failed_send_is_reported_and_not_marked():
    s = storage_with_store()

    def broken(title, body, topic, server="https://ntfy.sh"):
        raise RuntimeError("ntfy down")
    result = daily.run(s, "topic", check=fake_check([JUHLA_SALE]), send=broken)
    assert result["sent"] is False and result["errors"] == ["ntfy: ntfy down"]
    assert s.get("notified") is None  # tomorrow it's tried again


def test_empty_list_sends_nothing():
    s = storage_with_store()
    s.set("list", [])
    check, sent = fake_check([JUHLA_SALE]), []
    assert daily.run(s, "topic", check=check, send=record(sent)) == {"sales": 0, "new": 0, "sent": False, "errors": []}
    assert check.calls == [] and sent == []
