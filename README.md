# Tarjoushaukka

Keeps a list of what you usually buy in S-group stores (Prisma, S-market, Sale, Alepa, ABC) and tells you which of it is on sale right now, on a web page. It doesn't send notifications: open the page to see what's on sale.

It started as a pick-and-mix (irtokarkki) deal finder, and pick-and-mix is still on the list by default.

## How it finds sales

- **Online prices** (the s-kaupat.fi API) in your favourite stores. These include the chain's flyer campaigns for packaged products and each store's own sales.
- **The cooperative's weekly flyers** on view.sok-julkaisut.fi, for things the online shop doesn't sell, like the weighed pick-and-mix from the bins. By default it reads Turun Osuuskauppa's flyers (Turku area); change `library` in the `[flyers]` section of `config.toml` for another region.

A list item is either:

- **an exact product**, picked from your favourite store's range: on sale when that product is; or
- **a word** for "any brand will do", e.g. `kahvi` or `jauheliha`: anything on sale whose name contains the word counts. Type the start of a word, since Finnish endings vary: `irtokark` also finds "irtokarkit". If a word catches too much (`kahvi` also matches "kahvikeksi"), swap it for exact products. Turn on **Also in flyers** for words whose sales only show up in the flyers, like pick-and-mix.

## Setup

Requires Python 3.11 or newer.

```
git clone https://github.com/mikugh/tarjoushaukka.git
cd tarjoushaukka
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Web UI

```
.venv\Scripts\python -m tarjoushaukka.web
```

Then open http://localhost:5000. The page has three tabs:

- **On sale**: everything on your list that's on sale now, with the sale price, the normal price, the store (or the flyer, with a link to it) and when the sale ends. "Check now" checks again.
- **My list**: add products or words, turn "Also in flyers" on or off for a word, and remove items with ✕. New lists start with the pick-and-mix words `irtokark`, `irtomakeis`, `irtonamu` and `irttari`.
- **Stores**: search any S-group store in Finland and tap ☆ to make it a favourite. Your list is checked in your favourite stores.

Use the FI / SV / EN switch in the top corner to change the language.

Your list and favourite stores are kept on the server, so they're the same on your phone and computer. Run locally, they're saved in `user_data.json` in the project folder (kept out of git). A check is reused for `cache_hours`, and "Check now" checks again once it's older than `min_refresh_minutes` (both in the `[web]` section of `config.toml`).

### Access key

Lock the app with an access key so only you can use it. Create one with

```
.venv\Scripts\python -c "import secrets; open('access_key.txt', 'w').write(secrets.token_urlsafe(18))"
```

and restart the web UI. (The key can also come from the `TARJOUSHAUKKA_ACCESS_KEY` environment variable; `access_key.txt` is kept out of git.) Then open `https://<your address>/?key=<the key>` once on each device. The first visit stores the key in the browser, so after that the plain address and home-screen shortcuts work. Anyone without it only sees a page asking for the link.

By default the server only listens on this computer; set `TARJOUSHAUKKA_HOST=0.0.0.0` (and optionally `TARJOUSHAUKKA_PORT`) to reach it from other devices on your home network.

### Vercel

Vercel runs the app for free (Hobby plan), with no computer of yours that needs to stay on. `vercel.json` runs it in Stockholm, and `.vercelignore` keeps `access_key.txt` and other local files from being uploaded.

The first time:

1. `npx vercel login`, then `npx vercel link --project tarjoushaukka`.
2. Add a free **Upstash Redis** database to the project from the Vercel Marketplace (`npx vercel integration add upstash`). It stores your list and stores. Without it, the app answers "Storage isn't connected".
3. Add the access key as a production environment variable, read from the file so it doesn't end up in your shell history: `npx vercel env add TARJOUSHAUKKA_ACCESS_KEY production --sensitive < access_key.txt`
4. Deploy with `npx vercel deploy --prod`.

## Command line

The command line tool is the original pick-and-mix checker. It doesn't use the shopping list: it searches the words in the `[search]` section of `config.toml` in your city's stores and favourites.

```
.venv\Scripts\python -m tarjoushaukka            # check once and print the deals
.venv\Scripts\python -m tarjoushaukka --watch 6  # keep running, check every 6 hours
```

Edit `config.toml` to choose your city (or specific stores) and search words. It prints a table of the deals found and the pick-and-mix offers in the flyers.

The command line favourites are listed in `favourites.json` in the project folder. Favourite stores are always checked, even outside your city. Store IDs are in the store URLs on s-kaupat.fi:

```json
[
 {"source": "s_group", "store_id": "603212622", "chain": "S-market", "name": "S-market Halinen", "location": "Turku"}
]
```

The command line output uses the `language` setting in `config.toml` (`"fi"`, `"sv"` or `"en"`).

## Limitations

- Only S-group stores. Other chains aren't supported.
- Stores sell real pick-and-mix (the weighed bins) only in the shop, not online. Pick-and-mix sales are found only when they're in the cooperative's flyers; a store's own sale announced on social media doesn't show up. Flyer offers are read from the flyer's text, so an offer is shown as it's printed, e.g. "Voim. la 21.11. Irtonamujo 3 kg/talous", and has no end date of its own (the flyer's title has the dates).
- The flyer library removes a flyer once it expires, so past sales can't be looked up.
- Word matching is plain "contains", so a short word can catch unrelated products.
- The s-kaupat.fi API and the flyer library are unofficial sources and may change without notice. This is meant for personal use, so please don't run checks more often than you need to.

## License

[MIT](LICENSE)
