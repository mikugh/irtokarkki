# Shopping List Sales Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the web app into "is anything I usually buy on sale?": a server-stored shopping list (exact products and words), an On sale now page, and a daily ntfy message about new sales.

**Architecture:** A small storage layer (Upstash Redis over its REST API on Vercel, a JSON file locally) holds the list, favourite stores and the notified set. `shopping.py` checks a list against the favourite stores (S-kaupat API) and the cooperative's flyers and returns `Sale`s; the web API and the daily cron endpoint both use it. The page is rebuilt around On sale now + My list; the Stores tab stays.

**Tech Stack:** Python 3.11+, Flask, requests, pytest; Vercel (Python, Cron, Hobby), Upstash Redis via the Vercel Marketplace, ntfy.

**Spec:** `docs/superpowers/specs/2026-11-21-shopping-list-sales-design.md`

## Global Constraints

- Hosting stays on Vercel's free Hobby plan, region `arn1`; one cron per day, `0 5 * * *` (UTC).
- Every page and API endpoint stays behind the access key, except the cron endpoint, which requires `Authorization: Bearer <CRON_SECRET>`.
- No background threads on Vercel; all work happens inside the request, under 300 s.
- S-kaupat API: at most 5 stores per request (`STORES_PER_REQUEST`), at most 20 aliased product lookups per request (`PRODUCTS_PER_REQUEST`). On sale means `campaignPrice < regularPrice`.
- Word matching is plain case-insensitive "contains" on the product name; no exception words.
- Flyers are matched only for word items with `"flyers": true`; exact products are never matched in flyers.
- The ntfy message is in Finnish; the topic comes from the `NTFY_TOPIC` env var; unset means the check runs and sends nothing.
- The command line tool (`python -m irtokarkki`, `config.toml`, `favourites.json`, `core.py`, `notify.desktop/ntfy`) keeps working unchanged.
- The page keeps its current visual style and FI/SV/EN languages.
- No new Python dependencies (Upstash is spoken to with `requests`).
- Repo files use CRLF line endings; keep them.
- Never print or commit the access key, `access_key.txt`, `.env.local`, the ntfy topic or `CRON_SECRET`.

## Review Focus

1. **Redis not connected on Vercel** (env vars missing): every API endpoint answers 503 with a clear message; nothing silently writes to Vercel's read-only disk. → test in Task 1 and Task 5.
2. **Daily check runs twice the same day** (Vercel retries, or a manual run): the second run sends nothing. → test in Task 4.
3. **One source fails during the daily check** (flyers down, API up): new sales found are sent and added to the notified set; old entries are kept, so tomorrow nothing is re-sent and nothing is forgotten. → test in Task 4.
4. **A one- or two-letter word, or junk in a saved list** (e.g. "ka", 500 items, a non-numeric EAN): rejected or capped by `parse_items`, so a typo can't match every product or blow the 300 s budget. → test in Task 3.
5. **A listed product a store doesn't sell, or that has vanished** (API returns `null` for that alias): skipped for that store, no error. → test in Task 2.

---

### Task 1: Storage

**Files:**
- Create: `irtokarkki/storage.py`
- Modify: `.gitignore`, `.vercelignore` (add `user_data.json`)
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `class StorageNotConfigured(RuntimeError)`
  - `class MemoryStorage` / `class FileStorage(path: Path)` / `class RedisStorage(url: str, token: str, prefix: str = "irtokarkki:")`, each with `get(name: str) -> Any | None` and `set(name: str, value: Any) -> None` (values are JSON-serialisable).
  - `load_storage() -> MemoryStorage | FileStorage | RedisStorage`
  - Names used by later tasks: `"list"`, `"stores"`, `"notified"`, `"last_check"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_file_storage_round_trip(tmp_path):
    s = storage.FileStorage(tmp_path / "user_data.json")
    assert s.get("list") is None
    s.set("list", [{"type": "word", "text": "kahvi", "flyers": False}])
    assert storage.FileStorage(tmp_path / "user_data.json").get("list")[0]["text"] == "kahvi"

def test_redis_storage_speaks_upstash_rest(monkeypatch):
    sent = []
    def fake_post(url, json, headers, timeout):
        sent.append((url, json, headers["Authorization"]))
        return FakeResponse({"result": '["a"]' if json[0] == "GET" else "OK"})
    monkeypatch.setattr(storage.requests, "post", fake_post)
    r = storage.RedisStorage("https://x.upstash.io", "tok")
    r.set("stores", ["a"]); assert r.get("stores") == ["a"]
    assert sent[0] == ("https://x.upstash.io", ["SET", "irtokarkki:stores", '["a"]'], "Bearer tok")
    assert sent[1][1] == ["GET", "irtokarkki:stores"]

def test_load_storage_picks_backend(monkeypatch, tmp_path):
    for v in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "VERCEL"):
        monkeypatch.delenv(v, raising=False)
    assert isinstance(storage.load_storage(), storage.FileStorage)
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(storage.StorageNotConfigured):
        storage.load_storage()
    monkeypatch.setenv("KV_REST_API_URL", "https://x.upstash.io"); monkeypatch.setenv("KV_REST_API_TOKEN", "t")
    assert isinstance(storage.load_storage(), storage.RedisStorage)
```

(`FakeResponse` is a tiny test helper with `.json()` and `.raise_for_status()`.)

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_storage.py -v` — expected: FAIL (no module `irtokarkki.storage`).

- [ ] **Step 3: Implement `irtokarkki/storage.py`**

Redis env vars: `KV_REST_API_URL`/`KV_REST_API_TOKEN` (what the Vercel Marketplace Upstash integration injects), falling back to `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`. Upstash REST: `POST <url>` with the command as a JSON array, `Authorization: Bearer <token>`, timeout 15 s, `raise_for_status()`, value stored as a JSON string. `FileStorage` path is `ROOT / "user_data.json"`, written as UTF-8 JSON with `ensure_ascii=False`. On `VERCEL` with no Redis vars, raise `StorageNotConfigured("Storage isn't connected: add Upstash Redis to the Vercel project.")`. Add `user_data.json` to `.gitignore` and `.vercelignore`.

- [ ] **Step 4: Run** the tests again — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Add storage for the shopping list (Upstash Redis or a local file)"`

### Task 2: Product lookups and flyer matching

**Files:**
- Modify: `irtokarkki/sgroup.py`, `irtokarkki/flyers.py`
- Test: `tests/test_parsing.py` (S-group), `tests/test_flyers.py` (flyers)

**Interfaces:**
- Produces:
  - `sgroup.lookup_products(stores: list[Store], eans: list[str]) -> list[Deal]` — one `Deal` per (store, EAN) the store sells.
  - `sgroup.search_products(store: Store, query: str, limit: int = 20) -> list[Deal]` — the store's catalog search, current prices.
  - `flyers.matches(text: str, keyword: str) -> bool` — the same normalised "contains" that `find_offers` uses.

- [ ] **Step 1: Write the failing tests**

```python
def test_lookup_products_batches_and_skips_missing(monkeypatch):
    queries = []
    def fake_post(query, variables=None, lang=None):
        queries.append(query)
        return {"p0": {"id": "6411300000494", "name": "Juhla Mokka 500g", "priceUnit": "KPL",
                       "pricing": {"campaignPrice": 6.99, "regularPrice": 8.89, "campaignPriceValidUntil": "2026-11-24T21:59:59Z"}},
                "p1": None}
    monkeypatch.setattr(sgroup, "_post", fake_post)
    deals = sgroup.lookup_products([STORE], ["6411300000494", "0000000000000"])
    assert len(queries) == 1 and 'product(id: "6411300000494", storeId: "603212622")' in queries[0]
    assert [(d.product_id, d.discounted_price, d.original_price, d.valid_until) for d in deals] == [
        ("6411300000494", 6.99, 8.89, "2026-11-24")]

def test_lookup_products_uses_at_most_20_aliases_per_request(monkeypatch):
    calls = []
    monkeypatch.setattr(sgroup, "_post", lambda q, v=None, lang=None: calls.append(q.count("product(")) or {})
    sgroup.lookup_products([STORE, STORE2], [str(i).zfill(13) for i in range(15)])
    assert calls == [20, 10]

def test_flyer_matches_ignores_case_hyphens_and_spaces():
    assert flyers.matches("5 90 Voim. la 21.11. Irto- makeiset kg", "irtomakeis")
    assert not flyers.matches("Kotimaista kirjolohi", "irtomakeis")
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_parsing.py tests/test_flyers.py -v` — expected: the three new tests FAIL.

- [ ] **Step 3: Implement.** In `sgroup.py`, pull the item→`Deal` conversion out of `_find_prices_batch` into `_to_deal(store: Store, item: dict) -> Deal | None` and reuse it in both new functions; `search_products` is `_find_prices_batch([store], query)` capped to `limit`. `lookup_products` builds `p{i}: product(id: "<ean>", storeId: "<id>") { id name priceUnit pricing {...} }` aliases over all (store, EAN) pairs, 20 per request. In `flyers.py`, add `matches` and make `find_offers` call it.

- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Look up products by EAN and match flyer text per word"`

### Task 3: Checking the list

**Files:**
- Create: `irtokarkki/shopping.py`
- Test: `tests/test_shopping.py`

**Interfaces:**
- Consumes: `sgroup.lookup_products`, `sgroup.find_prices`, `flyers.check`, `flyers.matches` (Task 2).
- Produces:
  - `MAX_ITEMS = 60`, `MIN_WORD = 3`, `MAX_WORD = 40`
  - `DEFAULT_LIST: list[dict]` = words `irtokark`, `irtomakeis`, `irtonamu`, `irttari`, each `{"type": "word", "text": ..., "flyers": True}`
  - `parse_items(raw) -> list[dict]` — items are `{"type": "product", "ean": str, "name": str}` or `{"type": "word", "text": str, "flyers": bool}`
  - `@dataclass(frozen=True) class Sale: item: str; item_type: str; product: str; price: float | None; regular_price: float | None; place: str; url: str; until: str; key: str` — `place` is the store name or the flyer title; `until` is an ISO date or `""` for flyers.
  - `check_list(items: list[dict], stores: list[Store], library: str, flyer_pages: dict) -> tuple[list[Sale], list[str]]` — the sales and any error messages (`"s_group: ..."`, `"flyers: ..."`).

- [ ] **Step 1: Write the failing tests** (fake `sgroup.lookup_products`, `sgroup.find_prices` and `flyers.check` with monkeypatch)

```python
def test_parse_items_rejects_junk_and_caps():
    items = shopping.parse_items([
        {"type": "word", "text": "  Kahvi ", "flyers": False},
        {"type": "word", "text": "ka"},                       # too short: would match everything
        {"type": "word", "text": "kahvi"},                    # duplicate
        {"type": "product", "ean": "6411300000494", "name": "Juhla Mokka 500g"},
        {"type": "product", "ean": "abc", "name": "x"},
        "nope",
    ])
    assert items == [{"type": "word", "text": "kahvi", "flyers": False},
                     {"type": "product", "ean": "6411300000494", "name": "Juhla Mokka 500g"}]
    assert len(shopping.parse_items([{"type": "word", "text": f"sana{i}"} for i in range(500)])) == shopping.MAX_ITEMS

def test_product_and_word_sales_with_dedupe(fakes):
    # fakes: Juhla Mokka on sale 6.99/8.89 in S-market Halinen; Kulta Katriina 3.95/5.29; a full-price kahvi
    sales, errors = shopping.check_list(
        [{"type": "product", "ean": JUHLA, "name": "Juhla Mokka 500g"}, {"type": "word", "text": "kahvi", "flyers": False}],
        [HALINEN], "tok-ilmoitukset", {})
    assert errors == []
    assert [(s.item, s.item_type, s.product, s.price, s.regular_price) for s in sales] == [
        ("Juhla Mokka 500g", "product", "Paulig Juhla Mokka kahvi 500g", 6.99, 8.89),
        ("kahvi", "word", "Kulta Katriina suodatinkahvi 500g", 3.95, 5.29)]  # Juhla Mokka not repeated under "kahvi"

def test_flyers_only_for_words_with_flyers_on(fakes):
    sales, _ = shopping.check_list([{"type": "word", "text": "irtomakeis", "flyers": True},
                                    {"type": "word", "text": "kirjolohi", "flyers": False}],
                                   [HALINEN], "tok-ilmoitukset", {})
    flyer_sales = [s for s in sales if s.url.startswith("https://view.sok-julkaisut.fi")]
    assert [(s.item, s.price, s.place, s.until) for s in flyer_sales] == [("irtomakeis", 5.9, "TOK Prisma 18.–22.11.", "")]
    assert fakes.flyer_keywords == [["irtomakeis"]]

def test_source_failure_is_reported_and_others_still_count(fakes):
    fakes.flyers_fail = True
    sales, errors = shopping.check_list([{"type": "word", "text": "kahvi", "flyers": True}], [HALINEN], "tok-ilmoitukset", {})
    assert errors == ["flyers: site down"] and sales  # the store sale still shows

def test_sale_keys_change_with_price_and_end_date():
    ...  # same item/product/store, different price or until -> different key
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_shopping.py -v` — expected: FAIL (no module).

- [ ] **Step 3: Implement `irtokarkki/shopping.py`.** Word text is stored stripped and lowercased; EAN is 8–14 digits; product name capped at 120 chars. In `check_list`: products via one `lookup_products` call; each word via `sgroup.find_prices(stores, word)` keeping names that contain the word (lowercase); skip a word sale whose (product_id, store_id) was already a product sale; flyers via one `flyers.check(library, flyer_words, flyer_pages)` call, then each offer assigned to every flyer word it `matches`; flyer price `"5,90"` → `5.9`, missing → `None`. Run the word searches in a `ThreadPoolExecutor(4)`. Catch exceptions per source and report them as `"s_group: <e>"` / `"flyers: <e>"`. Sort: list order first, then price. Keys: store sale `f"{item}|{product_id}|{store_id}|{price:.2f}|{until}"`, flyer sale `f"{item}|flyer|{doc_id}|{text}"`. `url` is the s-kaupat product page `https://www.s-kaupat.fi/tuote/{ean}` for store sales, the flyer URL for flyer sales.

Stem search was checked against the live API while planning: "irtokark", "irttari", "kahvi" and "jauheliha" return products as stems, so no fallback search is needed ("irtonamu" returns nothing online, which is expected: it's flyer-only).

- [ ] **Step 4: Run** the tests again — expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Check a shopping list against favourite stores and flyers"`

### Task 4: Daily check and the phone message

**Files:**
- Create: `irtokarkki/daily.py`
- Modify: `irtokarkki/notify.py` (add functions only; existing ones unchanged)
- Test: `tests/test_daily.py`

**Interfaces:**
- Consumes: `storage` names `"list"`, `"stores"`, `"notified"`, `"last_check"` (Task 1); `shopping.check_list`, `shopping.DEFAULT_LIST`, `Sale` (Task 3).
- Produces:
  - `notify.sales_message(sales: list[Sale]) -> tuple[str, str]`
  - `notify.ntfy_send(title: str, body: str, topic: str, server: str = "https://ntfy.sh") -> None` (raises on HTTP error)
  - `daily.run(storage, topic: str, server: str = "https://ntfy.sh", library: str = "tok-ilmoitukset", check=shopping.check_list, send=notify.ntfy_send) -> dict` returning `{"sales": int, "new": int, "sent": bool, "errors": list[str]}`.

- [ ] **Step 1: Write the failing tests** (a fake `check` returning fixed sales/errors, a recording `send`, `MemoryStorage`)

```python
def test_message_is_finnish():
    title, body = notify.sales_message([JUHLA_SALE, KAHVI_WORD_SALE])
    assert title == "2 uutta tarjousta"
    assert body == ("Juhla Mokka 500g 6,99 € (S-market Halinen)\n"
                    "kahvi: Kulta Katriina suodatinkahvi 500g 3,95 € (S-market Halinen)")
    assert notify.sales_message([JUHLA_SALE])[0] == "1 uusi tarjous"

def test_sends_only_new_and_twice_a_day_sends_nothing():
    s = MemoryStorage(); s.set("stores", [HALINEN_JSON]); sent = []
    first = daily.run(s, "topic", check=fake_check([JUHLA_SALE]), send=record(sent))
    second = daily.run(s, "topic", check=fake_check([JUHLA_SALE]), send=record(sent))
    assert first == {"sales": 1, "new": 1, "sent": True, "errors": []} and second["new"] == 0 and len(sent) == 1
    assert s.get("last_check")

def test_partial_failure_keeps_old_entries_and_adds_new():
    s = MemoryStorage(); s.set("notified", ["old|key"]); s.set("stores", [HALINEN_JSON])
    daily.run(s, "topic", check=fake_check([JUHLA_SALE], errors=["flyers: site down"]), send=record([]))
    assert set(s.get("notified")) == {"old|key", JUHLA_SALE.key}

def test_full_success_replaces_the_set():
    ...  # notified == keys of today's sales only; an empty successful check leaves []

def test_no_topic_or_failed_send_does_not_mark_as_notified():
    ...  # topic "" -> sent False, notified unchanged; send raising -> error reported, notified unchanged

def test_empty_list_or_no_stores_sends_nothing():
    ...  # list [] -> check not called for stores, {"sales": 0, ...}
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_daily.py -v` — expected: FAIL.

- [ ] **Step 3: Implement.** Message lines use `i18n.price(price, "fi")`; label is the product name for product items, `f"{item}: {product}"` for words; a flyer sale with no price leaves the price out. Title header for ntfy is UTF-8 encoded like `notify.ntfy` does; tag `shopping_cart`. `daily.run`: list from storage (`DEFAULT_LIST` when `None`), stores from storage (parsed into `Store`), run `check`, compute new = keys not in notified; send when there are new ones and a topic; after a successful send (or nothing new), set notified = today's keys if there were no errors, else old ∪ sent keys; if sending failed or there's no topic, leave notified unchanged. Always set `"last_check"` to an ISO timestamp.

- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Daily check: message new sales once via ntfy"`

### Task 5: Web API and the cron endpoint

**Files:**
- Modify: `irtokarkki/web.py`, `vercel.json`
- Modify: `tests/test_web.py` (drop `PriceCache`/`/api/state` tests; keep and repoint the access-key tests), `tests/test_flyers.py` (drop the `FlyerCache` test)

**Interfaces:**
- Consumes: Tasks 1, 3, 4.
- Produces (JSON over HTTP, used by Task 6):
  - `GET /api/list` → `{"items": [...]}` (`DEFAULT_LIST` when nothing is stored); `PUT /api/list` body `{"items": [...]}` → `{"items": parsed}`
  - `GET /api/favourites` → `{"stores": [store, ...]}`; `PUT /api/favourites` body `{"stores": [...]}` → `{"stores": parsed}` (each store as `_store_json`)
  - `GET /api/products/search?q=<text>&store=<store_id>` → `[{"ean", "name", "price", "regular_price", "unit"}]`; `q` under 2 chars → `[]`; `store` defaults to the first favourite; no stores → `[]`
  - `POST /api/sales` body `{"refresh": bool}` → `{"sales": [Sale as dict], "checked_at": iso | null, "errors": [...], "items": n, "stores": n}`
  - `GET /api/cron/daily` → `daily.run(...)` result; 401 without the right bearer
  - `GET /api/stores/search` unchanged
  - any endpoint → 503 `{"error": ...}` when `StorageNotConfigured`

- [ ] **Step 1: Write the failing tests** (`client` fixture: `MemoryStorage` monkeypatched in as `web.storage`, `ACCESS_KEY = ""`, fake `shopping.check_list`)

```python
def test_list_round_trip_and_default(client):
    assert client.get("/api/list").json["items"] == shopping.DEFAULT_LIST
    saved = client.put("/api/list", json={"items": [{"type": "word", "text": "Kahvi"}]}).json
    assert saved["items"] == [{"type": "word", "text": "kahvi", "flyers": False}]
    assert client.get("/api/list").json == saved

def test_favourites_round_trip_ignores_junk(client): ...
def test_sales_are_cached_until_list_or_stores_change(client, fake_check):
    client.post("/api/sales", json={}); client.post("/api/sales", json={})
    assert fake_check.calls == 1
    client.put("/api/list", json={"items": [{"type": "word", "text": "maito"}]})
    client.post("/api/sales", json={}); assert fake_check.calls == 2

def test_cron_needs_the_secret_and_skips_the_access_key(client, monkeypatch):
    monkeypatch.setattr(web, "ACCESS_KEY", "s3cret-key"); monkeypatch.setenv("CRON_SECRET", "cron-s3cret")
    assert client.get("/api/cron/daily").status_code == 401
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer cron-s3cret"}).status_code == 200
    assert client.get("/api/list").status_code == 401  # everything else still needs the key
    monkeypatch.delenv("CRON_SECRET")
    assert client.get("/api/cron/daily", headers={"Authorization": "Bearer "}).status_code == 401

def test_storage_not_connected_gives_503(client, monkeypatch): ...
```

Repoint the existing access-key tests from `/api/state` to `/api/list`.

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_web.py -v` — expected: new tests FAIL.

- [ ] **Step 3: Implement.** Remove `PriceCache`, `stores_in_city`, `FlyerCache`, `/api/state`, `/api/flyers` and the now-unused config values; keep the access key, `parse_favourites`, `_store_json`, store search. Storage is created lazily through `get_storage()` so a missing Upstash only fails requests, not the import. Sales cache: one entry `(fingerprint of items+stores, checked_at, sales, errors)`, reused while younger than `cache_hours` (or `min_refresh_minutes` when `refresh`), and a flyer-pages dict kept across requests. Cron: compare `Authorization` with `f"Bearer {CRON_SECRET}"` via `hmac.compare_digest`; an unset secret always refuses; topic from `NTFY_TOPIC`, library from `config["flyers"]["library"]`. `vercel.json` gets `"crons": [{"path": "/api/cron/daily", "schedule": "0 5 * * *"}]`.

- [ ] **Step 4: Run** `.venv\Scripts\python -m pytest -q` — expected: all PASS.
- [ ] **Step 5: Commit** — `git commit -m "Web API for the shopping list, sales and the daily cron"`

### Task 6: The page

**Files:**
- Modify: `irtokarkki/static/index.html`

**Interfaces:**
- Consumes: the Task 5 endpoints.

- [ ] **Step 1: Rebuild the Deals tab as "On sale now" + "My list"** (tab labels FI "Tarjoukset"/"Lista", SV "Erbjudanden"/"Lista", EN "On sale"/"My list"; keep "Kaupat" tab). Remove the city box, the per-store price board and `#flyerList`. Hero: headline "{n} tarjousta listaltasi" style count (FI/SV/EN), status "Tarkistettu {time}", and the existing check button calling `POST /api/sales {refresh: true}`.
  - On sale now rows, as in the spec sketch: label (product name, or `word: product`), `regular → price`, place, "until {date}" or the flyer title; the row links to `url`. Empty states: no favourite stores → point to the Stores tab; nothing on sale → "Nothing on your list is on sale right now".
  - My list: each item with ✕ (saves via `PUT /api/list`); words show "(any)" and a 📰 toggle for "also look in flyers". One add box: typing shows "Add word "…"" plus matching products from `/api/products/search` (name, size, current price); tapping a product adds it, the word option adds a word with flyers off. Hint under the box: "Tip: type the start of a word: "irtokark" also finds "irtokarkit"." Flyer toggle hint: "For things not sold online, like pick-and-mix."
- [ ] **Step 2: Stores tab** reads and writes favourites via `/api/favourites` instead of localStorage. First load: if the server has no stores and localStorage has the old favourites, `PUT` them once and clear the old key.
- [ ] **Step 3: Verify in the browser preview** (`irtokarkki-web` launch config, local `user_data.json`): add a product and a word, toggle flyers, remove an item, reload and see them kept; favourite a store and see sales load; check FI/SV/EN, dark mode, and 375 px width without horizontal scroll; no console errors.
- [ ] **Step 4: Commit** — `git commit -m "Page: On sale now and My list"`

### Task 7: Docs

**Files:**
- Modify: `README.md`, `config.toml` (comments only, if the web UI no longer uses a setting)

- [ ] **Step 1: Update `README.md`**: what the app does now (your shopping list, S-group, flyers for words with flyers on); the web UI section (On sale now, My list, Stores); Vercel setup (Upstash Redis from the Marketplace, `CRON_SECRET`, `NTFY_TOPIC`, the daily 07:00 message); local runs use `user_data.json`. Remove "Sharing with friends and family" and "everyone using the same server has their own favourites". Command line section unchanged.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest -q` — expected: all PASS.
- [ ] **Step 3: Commit** — `git commit -m "README: shopping list, storage and daily message"`

### Task 8: Connect Upstash and deploy (needs the owner)

- [ ] **Step 1: Ask the owner** for the OK to create the free Upstash Redis database through the Vercel Marketplace, and for their ntfy topic (or offer to generate a hard-to-guess one they subscribe to in the ntfy app).
- [ ] **Step 2:** `npx vercel@latest integration add upstash` for project `irtokarkki` (free plan, region closest to `arn1`); confirm `KV_REST_API_URL`/`KV_REST_API_TOKEN` appear in `npx vercel@latest env ls`.
- [ ] **Step 3:** Add `CRON_SECRET` (random, `--sensitive`) and `NTFY_TOPIC` (`--sensitive`) to production via stdin, never on the command line or in output.
- [ ] **Step 4:** `npx vercel@latest deploy --prod --yes`.
- [ ] **Step 5: Verify live:** the page loads with the key, the default list shows, adding an item survives a reload; `/api/cron/daily` returns 401 without the secret; calling it once with the secret returns a result and (if anything is on sale) the phone gets the message; a second call sends nothing. Crons tab in the Vercel dashboard shows the daily job.
- [ ] **Step 6:** Push the commits (`git push`).
