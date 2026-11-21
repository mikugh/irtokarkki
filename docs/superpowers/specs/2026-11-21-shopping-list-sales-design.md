# Shopping list sales: design

Date: 2026-11-21. Status: approved by the owner.

## Intent

The owner goes through the S-group flyers by hand every week to see whether the things they usually buy are on sale. The app should take over that weekly chore: the owner keeps a list of what they usually buy, and the app tells them which of those things are on sale right now, both on a page they can open and as a message on their phone when something new goes on sale.

Today the app only tracks irtokarkki. This change turns it into a general "is anything I buy on sale?" app for S-group stores. Irtokarkki stops being special and becomes items on the list.

## Goals

- The owner keeps one list of things they buy. A list item is either:
  - **an exact product**, found by searching the S-group catalog in the app and added by tapping it (identified by its EAN); or
  - **a word** for "any brand will do" items, e.g. "kahvi", "jauheliha", "irtomakeis". Anything on sale whose name contains the word counts. Each word has an "also look in flyers" setting.
- The page shows **On sale now**: every list item that is on sale in one of the owner's favourite stores or in the cooperative's current flyers, with the sale price, the normal price when known, the store or flyer, and when the sale ends.
- Once a day the app checks the list and sends a **phone message** (via the free ntfy app) listing the sales that are new since the last message. No message when nothing new went on sale.
- The list and the favourite stores are stored on the server, so they are the same on the owner's phone and computer.

## Non-goals

- More than one user. The app is for the owner only; nobody else has the link or the access key today, so the access key stays as it is. (It should not be built in a way that makes adding personal lists later impossible, but nothing for it is built now.)
  The README's "Sharing with friends and family" section and the "everyone using the same server has their own favourites" behaviour are removed.
- Other chains than S-group.
- Price history, "lowest price in 30 days", or price alerts below a chosen price.
- Shopping-trip features (ticking items off, quantities, sharing a list).
- Changing the command line tool (`python -m irtokarkki`). It keeps working as it does today, with `config.toml` and `favourites.json`. Only the web app and its daily check change.

## Anti-goals (would make this a failure even if it works)

- A noisy phone: messages every day about the same sales, or many false hits from word items. A message must only contain sales the owner hasn't been told about yet.
- Losing the list. The list is the owner's own work; it must survive redeploys, Vercel shutting the app down, and failed checks.
- The list or the owner's messages being reachable by anyone without the access key.
- Being so slow or heavy that the S-kaupat API or the flyer library gets hammered (see constraints).

## Constraints

- Hosting stays on Vercel's free Hobby plan (Python/Flask function, region `arn1`). Hobby cron jobs run at most once a day, at a time Vercel picks within the scheduled hour.
- The app is already locked with an access key (`IRTOKARKKI_ACCESS_KEY`, cookie after the first `?key=` visit). Every new page and API endpoint stays behind it. The daily-check endpoint is called by Vercel Cron, which can't log in, so it is protected separately with Vercel's `CRON_SECRET` (`Authorization: Bearer <CRON_SECRET>`).
- On Vercel, work only happens during a request (no background threads); a request may run up to 300 s.
- S-kaupat API (`https://api.s-kaupat.fi/`, unofficial, GraphQL): asking for too many stores in one request returns 500, so the current code batches 5 stores per request. Several products can be fetched in one request with aliases: `product(id: "<EAN>", storeId: "<id>") { id name pricing { campaignPrice regularPrice campaignPriceValidUntil } priceUnit }`. Text search: `store(id) { products(queryString, limit) { items {...} } }`. A product is on sale when `campaignPrice < regularPrice`.
- The flyer library (`view.sok-julkaisut.fi/library/tok-ilmoitukset`, Turun Osuuskauppa) is already read by `irtokarkki/flyers.py`: it lists current flyers and reads each flyer's text, grouped into offer tiles with prices.
- Keep the load polite: at most one full check per page visit per few minutes (reuse the existing caching ideas), and one scheduled check per day.

## Approaches considered

1. **Upstash Redis through the Vercel Marketplace** (chosen). The list, favourite stores and "already notified" set are stored in a free Upstash Redis database connected to the Vercel project; Vercel Cron triggers the daily check; ntfy delivers messages. Upstash has a plain HTTPS (REST) API, so the app talks to it with `requests`, which it already uses. Trade-off: one more service (an Upstash account created through Vercel).
2. **One private JSON file in Vercel Blob.** No third-party account, but private Blob is in beta, Python support is thin, and every change rewrites the whole file.
3. **The list as a file in the GitHub repo, checked by GitHub Actions.** No database, but the page would need a GitHub token with write access to the repo, and every list change becomes a commit.

The owner picked 1. Running everything on the owner's own computer was ruled out because the list must be on the phone too.

## Decided by the owner

- Both a page and phone messages.
- Just the owner; one list.
- List items can be exact products and words, on the same list.
- Storage: Upstash Redis via the Vercel Marketplace (approach 1).

## Proposed and accepted (owner said "looks right")

- **Where sales come from:**
  - the online prices (S-kaupat API) in the owner's favourite stores. These include flyer campaigns for packaged products and each store's own sales;
  - Turun Osuuskauppa's flyers (existing `flyers.py`), for things the online shop doesn't sell, like pick-and-mix.
- **Irtokarkki** becomes plain word items. The new list starts with the word stems the app uses today, so nothing it finds today is lost: "irtokark", "irtomakeis", "irtonamu" and "irttari", all with "also look in flyers" on. (Builder's call: stems instead of whole words, because Finnish endings vary: "irtokarkit", "irtomakeisia", "Irtonamujo".)
- **Daily check** once every morning; message only when something is new since the last check.
- **Favourite stores** move from the browser to the server, next to the list.
- **The page:** roughly

  ```
  On sale now (3)
    Juhla Mokka 500 g        4,95 → 3,99 €   Prisma Itäharju · until 24.11.
    kahvi: Kulta Katriina    5,29 → 3,95 €   S-market Halinen · until 22.11.
    irtomakeiset: Irtonamujo        5,90 €   TOK Prisma flyer · Sat 21.11.

  My list
    Juhla Mokka 500 g             ✕
    Valio rasvaton maito 1 l      ✕
    kahvi (any)                   ✕
    [ Add a product or a word… ]
  ```

  plus the existing Stores tab for choosing favourite stores.

## Matching rules

- **Exact product in a store:** look the EAN up in each favourite store; on sale when `campaignPrice < regularPrice`. A product a store doesn't sell is simply skipped for that store.
- **Word in a store:** search each favourite store's catalog for the word (as the irtokarkki search does now) and keep items whose name contains the word anywhere (case-insensitive). On sale as above.
  - The owner chose plain "contains" matching (no exception words): "kahvi" also matches "kahvikeksi". When a word gets noisy, the owner swaps it for exact products. The add-word UI should hint that the beginning of a word works best ("irtokark" finds "irtokarkit" too).
  - Verify against the real API that the catalog search finds products for a stem like "irtokark"; if a stem returns nothing, search with the full word instead (builder's call), but match names on the stem.
- **Flyers:** match flyer offer tiles only against word items that have "also look in flyers" on, using the existing tile matching in `flyers.py` (lowercase, spaces and hyphens ignored). New words have it off by default; the add-word UI offers the setting with a hint that it's for things not sold online, like pick-and-mix. Reason: a packaged word like "kahvi" would otherwise show and notify the same sale twice (catalog and flyer). Exact products are never matched in flyers: flyers write names differently from the catalog, and packaged products' flyer campaigns already show up as catalog sale prices.
  - Flyer offers have no reliable end date; show the flyer title (which carries the dates) instead.
- One sale per (list item, product, store) or (list item, flyer offer). If an exact product and a word both match the same product in the same store, show it once, under the exact product.

## Notifications

- The daily check works out today's sales, compares them with the stored set of sales already notified, and sends one ntfy message listing the new ones ("3 uutta tarjousta: Juhla Mokka 500 g 3,99 € (Prisma Itäharju) …"), in Finnish.
- A sale's identity for "already notified": list item + product (EAN, or flyer doc id + tile text) + store + sale price + end date. A sale that ends and later comes back is notified again.
- The stored set is replaced with today's active sales after a successful send, so it doesn't grow forever.
- The ntfy topic is kept in a Vercel environment variable (`NTFY_TOPIC`), not in the repo. If it isn't set, the check runs but sends nothing.
- Schedule: once a day around 07:00 Finnish time (`0 5 * * *` UTC; Vercel picks the minute within the hour).

## Data stored in Redis

One small app, one user, so a few keys are enough:

- the list: ordered items, each `{"type": "product", "ean", "name"}` or `{"type": "word", "text", "flyers": bool}`;
- favourite stores: the same store fields the app uses today (`chain, store_id, name, location, map_url, source, location_sv`);
- the set of already-notified sale identities, and when the last check ran.

## Calls made after the design review

- Word items use stems, and the starting list keeps today's four stems (see above).
- "Also look in flyers" is a per-word setting, off by default.
- Flyer offers show the flyer title instead of an end date.
- The cron endpoint is exempt from the access-key check and checks `CRON_SECRET` instead.
- After a failed check (API or flyers down), the stored "already notified" set is left unchanged, so nothing is re-sent or lost; an empty successful check clears it.
- The access key stays; the README's sharing section goes.

## Left to the builder

- Exact Redis key names and value shapes, and whether to store JSON strings or Redis lists/sets.
- How the app runs without Redis locally (e.g. a JSON file in the project folder, kept out of git) so it can be developed and tested offline.
- The product search UI for adding exact products: which favourite store's catalog to search in (the API needs a store), result count, and showing the product's size/name clearly enough to pick the right one.
- Caching between page visits and how the page shows that a check is running.
- Limits that keep a check polite and within 300 s (e.g. a cap on list length or stores), and batching of product lookups.
- How the existing irtokarkki-specific web UI parts (the per-store irtokarkki price board, the city box) are replaced. The page should stay in the current visual style and FI/SV/EN languages.
- Moving existing browser favourites to the server the first time (nice to have).
- Tests, following the existing pytest style, without network access.
