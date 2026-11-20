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

Your favourites and city are saved in your browser, so everyone using the same server has their own.
(The command line tool has separate favourites in `favourites.json`, see below.)

Prices are cached per store and shared between everyone using the server: a store is checked again only when its prices are older than `cache_hours`, and "Check for deals" refetches prices older than `min_refresh_minutes` (both in the `[web]` section of `config.toml`).

### Sharing with friends and family

The web UI can serve several people at once. Keep it running on a computer that stays on (set Windows to never sleep while plugged in), then pick one of these to let others reach it.

To start the web UI in the background whenever you log in to Windows, run this in PowerShell from the project folder. It adds a shortcut to your Startup folder; delete `Irtokarkki.lnk` there to undo it.

```
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Startup'))\Irtokarkki.lnk")
$s.TargetPath = "$PWD\.venv\Scripts\pythonw.exe"; $s.Arguments = "-m irtokarkki.web"; $s.WorkingDirectory = "$PWD"; $s.Save()
Start-Process "$PWD\.venv\Scripts\pythonw.exe" -ArgumentList "-m", "irtokarkki.web" -WorkingDirectory $PWD
```

- **Tailscale** (private, invite-only):
  1. Install [Tailscale](https://tailscale.com/download) (`winget install Tailscale.Tailscale`) and sign in from its tray icon.
  2. Run `tailscale serve --bg 5000`. It prints the app's address, `https://<computer-name>.<your-tailnet>.ts.net`. The first time, it may print a link for turning on HTTPS for your tailnet.
  3. In the [admin console](https://login.tailscale.com/admin/machines), open this computer's ⋯ menu, choose **Share…** and invite people by email. They accept the invite, install Tailscale, and open the address. They can reach only this computer, not the rest of your network.
- **Tailscale Funnel** (a public link, no app needed for visitors): after the Tailscale steps above, run `tailscale funnel --bg 5000` instead of `tailscale serve`. The same `https://…ts.net` address then works in any browser for anyone who has it. Run `tailscale funnel --https=443 off` to make it private again.
- **Cloudflare Tunnel** (a public link, no app needed for visitors): install `cloudflared` and run `cloudflared tunnel --url http://localhost:5000`. It prints a `https://….trycloudflare.com` address anyone with the link can open. For a permanent address, set up a named tunnel with your own domain.

With a public link, lock the app with an access key so only people you send the link to can use it. Create one with

```
.venv\Scripts\python -c "import secrets; open('access_key.txt', 'w').write(secrets.token_urlsafe(18))"
```

and restart the web UI. (The key can also come from the `IRTOKARKKI_ACCESS_KEY` environment variable; `access_key.txt` is kept out of git.) Then send people `https://<your address>/?key=<the key>`. Their first visit stores the key in their browser, so after that the plain address and home-screen shortcuts work. Anyone without it only sees a page asking for the link. To shut someone out, change the key, restart, and send the new link to everyone who should keep access. This copies your link to the clipboard (in PowerShell, from the project folder; replace the address with yours):

```
Set-Clipboard "https://desktop-7a3pi3k.tail868e29.ts.net/?key=$((Get-Content access_key.txt -Raw).Trim())"
```

Run it from a home connection rather than a cloud server if you can: k-ruoka.fi blocks many cloud servers' addresses. By default the server only listens on this computer; set `IRTOKARKKI_HOST=0.0.0.0` (and optionally `IRTOKARKKI_PORT`) to reach it from other devices on your home network.

## Command line

```
.venv\Scripts\python -m irtokarkki              # check once, notify about new deals
.venv\Scripts\python -m irtokarkki --watch 6    # keep running, check every 6 hours
.venv\Scripts\python -m irtokarkki --no-notify  # only print the table
```

You get a notification only for deals you haven't been notified about yet (tracked in `seen_deals.json`). Once you have favourite stores, you're only notified about deals in those (set `only_favourites = false` in `config.toml` to change this).

The command line favourites are listed in `favourites.json` in the project folder. Favourite stores are always checked, even outside your city. Store IDs are in the store URLs on s-kaupat.fi and k-ruoka.fi:

```json
[
 {"source": "s_group", "store_id": "603212622", "chain": "S-market", "name": "S-market Halinen", "location": "Turku"},
 {"source": "k_group", "store_id": "N168", "chain": "K-Citymarket", "name": "K-Citymarket Turku Skanssi", "location": "Turku"}
]
```

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
