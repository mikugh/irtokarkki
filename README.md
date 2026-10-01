# Irtokarkki

Checks Finnish supermarkets for discounted irtokarkki and notifies you about new deals.
For each deal it shows the supermarket chain, store, location, original price, discounted price, discount % and how long the offer lasts.

Supported chains:
- **S-group**: Prisma, S-market, Sale, Alepa, ABC (via the s-kaupat.fi API)
- **K-group**: K-Citymarket, K-Supermarket, K-Market (via the k-ruoka.fi API)

Lidl isn't supported because it doesn't publish prices per store online.

## Setup

Requires Python 3.11 or newer.

```
git clone https://github.com/mikugh/irtokarkki.git
cd irtokarkki
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Edit `config.toml` to choose your city (or specific stores), search words and notification settings.

## Web UI

```
.venv\Scripts\python -m irtokarkki.web
```

Then open http://localhost:5000. The page has two tabs:

- **Discounts**: stores that have irtokarkki on sale, each with its deals (original price, sale price, % off, end date). Below them are the stores with no discount right now, with their current prices, and last the stores that don't sell irtokarkki online. Your favourite stores are listed first, and "★ Favourites only" hides the others.
- **Stores**: tap ☆ to favourite the stores you usually go to. Search finds any S-group or K-group store in Finland, even outside your city. Favourite stores are always checked.

Use the FI / SV / EN switch in the top corner to change the language. The first time, the app picks your browser's language. City names work in Swedish too (e.g. "Åbo").

Favourites are saved in `favourites.json` and are shared with the command line tool.

## Command line

```
.venv\Scripts\python -m irtokarkki              # check once, notify about new deals
.venv\Scripts\python -m irtokarkki --watch 6    # keep running, check every 6 hours
.venv\Scripts\python -m irtokarkki --no-notify  # only print the table
```

You get a notification only for deals you haven't been notified about yet (tracked in `seen_deals.json`). Once you have favourite stores, you're only notified about deals in those (set `only_favourites = false` in `config.toml` to change this).

The command line output and notifications use the `language` setting in `config.toml` (`"fi"`, `"sv"` or `"en"`).

Notifications:
- **Desktop**: a Windows notification (on by default).
- **Phone**: install the [ntfy](https://ntfy.sh) app, subscribe to a topic name that's hard to guess, and set `ntfy_topic` in `config.toml`.

### Run automatically with Windows Task Scheduler

This checks every day at 09:00. Run it in PowerShell from the project folder:

```
schtasks /Create /SC DAILY /ST 09:00 /TN "Irtokarkki" /TR "cmd /c cd /d `"$PWD`" && .venv\Scripts\pythonw.exe -m irtokarkki" /F
```

## Limitations

- Stores sell real pick-and-mix (the weighed bins) only in the shop, not online. Store-wide campaigns like "irtomakeiset -30%" therefore don't show up. The app finds discounted packaged irtokarkki products listed in the online catalogs.
- K-group prices marked "Plussa" require a K-Plussa card. "2 kpl / 4.50 €" offers are shown as the price per item.
- Both APIs are unofficial and may change without notice. This is meant for personal use, so please don't run checks more often than you need to.

## License

[MIT](LICENSE)
