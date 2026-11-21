# Irtokarkki

Keeps a list of what you usually buy in S-group stores (Prisma, S-market, Sale, Alepa, ABC) and tells you which of it is on sale right now: on a web page, and as a message on your phone every morning when something new goes on sale.

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
git clone https://github.com/mikugh/irtokarkki.git
cd irtokarkki
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Web UI

```
.venv\Scripts\python -m irtokarkki.web
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

and restart the web UI. (The key can also come from the `IRTOKARKKI_ACCESS_KEY` environment variable; `access_key.txt` is kept out of git.) Then open `https://<your address>/?key=<the key>` once on each device. The first visit stores the key in the browser, so after that the plain address and home-screen shortcuts work. Anyone without it only sees a page asking for the link.

By default the server only listens on this computer; set `IRTOKARKKI_HOST=0.0.0.0` (and optionally `IRTOKARKKI_PORT`) to reach it from other devices on your home network.

### Vercel

Vercel runs the app for free (Hobby plan), with no computer of yours that needs to stay on. `vercel.json` runs it in Stockholm and schedules the daily check, and `.vercelignore` keeps `access_key.txt` and other local files from being uploaded.

The first time:

1. `npx vercel login`, then `npx vercel link --project irtokarkki`.
2. Add a free **Upstash Redis** database to the project from the Vercel Marketplace (`npx vercel integration add upstash`). It stores your list, stores and which sales you've already been told about. Without it, the app answers "Storage isn't connected".
3. Add the secrets as production environment variables, each read from a file or typed when asked, so they don't end up in your shell history:
   - `npx vercel env add IRTOKARKKI_ACCESS_KEY production --sensitive < access_key.txt`
   - `CRON_SECRET`: any long random text. Vercel sends it with the daily check, and the check refuses to run without it.
   - `NTFY_TOPIC`: your ntfy topic (see Notifications below). Without it, the daily check runs but sends nothing.
4. Deploy with `npx vercel deploy --prod`.

The daily check runs once a morning around 07:00 Finnish time (Vercel picks the minute). It sends one message listing sales that are new since the last message, and nothing on days when nothing new went on sale.

## Notifications

Install the [ntfy](https://ntfy.sh) app on your phone and subscribe to a topic name that's hard to guess. Anyone who knows the topic name can read the messages, so treat it like a password. For the web app, put it in the `NTFY_TOPIC` environment variable on Vercel; for the command line tool, in `ntfy_topic` in `config.toml`.

## Command line

The command line tool is the original pick-and-mix checker. It doesn't use the shopping list: it searches the words in the `[search]` section of `config.toml` in your city's stores and favourites.

```
.venv\Scripts\python -m irtokarkki              # check once, notify about new deals
.venv\Scripts\python -m irtokarkki --watch 6    # keep running, check every 6 hours
.venv\Scripts\python -m irtokarkki --no-notify  # only print the table
```

Edit `config.toml` to choose your city (or specific stores), search words and notification settings. You get a notification only for deals you haven't been notified about yet (tracked in `seen_deals.json`). Once you have favourite stores, you're only notified about deals in those (set `only_favourites = false` in `config.toml` to change this). Pick-and-mix offers from the flyers are always notified, since they apply to all of the cooperative's stores.

The command line favourites are listed in `favourites.json` in the project folder. Favourite stores are always checked, even outside your city. Store IDs are in the store URLs on s-kaupat.fi:

```json
[
 {"source": "s_group", "store_id": "603212622", "chain": "S-market", "name": "S-market Halinen", "location": "Turku"}
]
```

The command line output and notifications use the `language` setting in `config.toml` (`"fi"`, `"sv"` or `"en"`). Notifications go to the Windows desktop (on by default) and, with `ntfy_topic` set, to your phone.

### Run automatically with Windows Task Scheduler

This checks every day at 09:00. Run it in PowerShell from the project folder:

```
schtasks /Create /SC DAILY /ST 09:00 /TN "Irtokarkki" /TR "cmd /c cd /d `"$PWD`" && .venv\Scripts\pythonw.exe -m irtokarkki" /F
```

## Limitations

- Only S-group stores. Other chains aren't supported.
- Stores sell real pick-and-mix (the weighed bins) only in the shop, not online. Pick-and-mix sales are found only when they're in the cooperative's flyers; a store's own sale announced on social media doesn't show up. Flyer offers are read from the flyer's text, so an offer is shown as it's printed, e.g. "Voim. la 21.11. Irtonamujo 3 kg/talous", and has no end date of its own (the flyer's title has the dates).
- The flyer library removes a flyer once it expires, so past sales can't be looked up.
- Word matching is plain "contains", so a short word can catch unrelated products.
- The s-kaupat.fi API and the flyer library are unofficial sources and may change without notice. This is meant for personal use, so please don't run checks more often than you need to.

## License

[MIT](LICENSE)
