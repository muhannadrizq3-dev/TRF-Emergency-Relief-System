# TRF Emergency Relief

**Emergency Relief Operations & Dispatch System** — RIT Dubai Software Engineering Competition 2026

**School:** Al Maarifa International Private School, Sharjah
**Team (TRF-Emergency-Relief):** Muhannad Rizq, Toka Ahmed, Reima Aboamir, Fatyma Iskhakova

> Educational competition project — **not a real emergency service**. In a real emergency in the UAE call
> **999** Police · **998** Ambulance · **997** Civil Defence.

---

## 1. What it does

After a disaster, relief shelters need water, food and first aid kits, but stock is limited. This web app
organises who gets what:

- **Shelter staff** create requests — e.g. *"Shelter B needs 60 food, high priority"* — or press **SOS**.
- **Coordinators** see every request, the stock and the shelter map on one page, and **dispatch** supplies.
- **Priority raising:** a waiting request gains one priority level every 24 hours (up to *Critical*).
- **Fair sharing:** when stock runs short, it is split proportionally between requests of the same priority
  using the **largest remainder method**.
- **Alerts:** SOS and critical requests alert the team by Telegram, WhatsApp and email, with a fallback log.
- **One page for everything:** Overview, Inventory, Requests, Shelters (map), Reports, Data (CSV import/export),
  Activity history (UAE time) and Team.
- Arabic / English (right-to-left layout), light / dark mode, works on phones, cookie settings.

## 2. Roles

| Role | Can do |
|---|---|
| **Coordinator** (the four team accounts) | Everything: stock, supply types, requests, shelters, dispatch, roles, password resets, CSV import, demo reset |
| **Shelter staff** | Create requests and SOS; edit / cancel **their own** open requests |
| **Volunteer** | View only |

### Team accounts

Four Coordinator accounts are built in and created automatically every time the app starts, so they are always
there — even after Vercel restarts the app:

| Name | Username | Email (also works for log in) |
|---|---|---|
| Muhannad Rizq | `muhannad` | muhannadrizq3@gmail.com |
| Toka Ahmed | `toka` | toka82439@gmail.com |
| Reima Aboamir | `reima` | abomir.reima@gmail.com |
| Fatyma Iskhakova | `fatyma` | fatyma.isk@gmail.com |

The passwords are shared privately inside the team. Only their scrypt hashes are in `settings.py`, so the
passwords themselves are never in the code or on GitHub. Everyone else who signs up chooses Volunteer or
Shelter staff; nobody can sign up as Coordinator — the server ignores it.

People log in with their **username or email**.

**Forgot password?** When the email settings (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`) are set, people enter
their email and get a reset link that works once and expires after 30 minutes. Without email settings, the
Coordinator presses **Reset password** in Team → Accounts & roles and gives the person a temporary password.

## 3. Project structure

```
trf-emergency-relief/
├── app.py                  # Entry point Vercel starts (imports the Flask app)
├── web_app.py              # Website: routes, login, permissions, CSRF, security headers, dashboard numbers
├── settings.py             # Roles, permissions, priorities, limits, demo data, environment settings
├── inventory.py            # Stock, low-stock levels, supply types, supplies CSV import
├── emergency_requests.py   # Requests + shelters, validation, 24h priority raising
├── dispatch.py             # fair_shares (largest remainder) + dispatch planning
├── notifier.py             # Telegram / WhatsApp / email alerts with fallback log
├── activity.py             # Activity history (who did what, UAE time)
├── data_io.py              # CSV import (shelters, requests) and all CSV exports
├── storage.py              # Saves everything in a built-in SQLite file (no database server needed)
├── translations.py         # English → Arabic interface text
├── templates/              # HTML pages (Jinja2)
├── static/                 # CSS, JavaScript, TRF logo and icons
├── tests/                  # 174 automated unit tests
├── samples/                # Example CSV files for the three imports
├── requirements.txt
└── .env.example
```

Layers: **Pages** (`templates/`) → **Website** (`web_app.py`) → **Core logic** (`inventory.py`,
`emergency_requests.py`, `dispatch.py`, `settings.py`, `activity.py`, `data_io.py` — plain Python, no Flask)
→ **Storage** (`storage.py`).

## 4. Run it on your computer

Needs Python 3.10 or newer.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python web_app.py
```

Open http://127.0.0.1:5000 and log in with one of the four team accounts. Data is saved
in `instance/trf_relief.db` (SQLite). Run the tests with:

```bash
python -m unittest
```

## 5. Put it on GitHub

1. Create a new **empty** repository on github.com (no README, no .gitignore — this project has them).
2. In this folder:

```bash
git init
git add .
git commit -m "TRF Emergency Relief"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/trf-emergency-relief.git
git push -u origin main
```

(Or on github.com use **Add file → Upload files** and drag in everything inside this folder — keep the
`templates`, `static`, `tests` and `samples` folders as folders.)

## 6. Deploy on Vercel

There is **no database to set up**. The app keeps its data in a built-in SQLite file and creates it by itself.

1. **vercel.com → Add New → Project** → import the repository. Vercel detects **Flask** by itself (leave the preset as it suggests). Deploy.
2. **Settings → Environment Variables**: add `SECRET_KEY` (a long random string —
   `python -c "import secrets; print(secrets.token_hex(32))"`), plus any alert settings from section 7.
   Without `SECRET_KEY`, people get logged out every time Vercel restarts the app.
3. **Redeploy** (Deployments → ⋯ → Redeploy) so the variables are used.
4. Open the site and log in with one of the four team accounts. The demo data (Water 100, Food 80,
   First Aid Kits 30, Shelters A–C) is created automatically.

**Good to know:** on Vercel the data file is temporary. When nobody has used the site for a while (usually
10–15 minutes) Vercel restarts the app and everything starts again from the demo data — accounts included.
The four team accounts always come back, so you can log in straight away after a restart. On your own computer (`python web_app.py`) the data is kept in
`instance/trf_relief.db` and never resets.

## 7. Alerts (optional — switch on any of them)

Each channel turns on when its variables are set. The Coordinator sees which ones are on under
*New emergency request*. If none are set, or all fail, alerts are saved and shown under Reports → Recent alerts.

| Channel | Variables | How to get them |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Talk to **@BotFather** → `/newbot`. Message the bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`. |
| WhatsApp | `WHATSAPP_PHONE`, `WHATSAPP_APIKEY` | Free **CallMeBot** service for one test phone: follow the steps on callmebot.com (send their activation message from the phone) to get an API key. Phone in `+9715…` form. |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | Gmail: `smtp.gmail.com`, port `587`, your Gmail address and a Google **App Password** (needs 2-step verification). The first four also switch on password-reset emails. |

## 8. CSV import & export (Data section)

Every row is checked first; if any row is wrong, nothing is imported. Examples are in `samples/`.

| Import | Header | Notes |
|---|---|---|
| Supplies | `item,quantity` | Adds to existing stock. New names become new supplies. |
| Shelters | `name,area,lat,lng` | Each shelter name must be new. |
| Requests | `shelter,item,quantity,priority` | Shelter and supply must exist. Imported requests don't send alerts. |

Exports: Supplies, Requests, Shelters, Activity. **Reset to demo data** and **Start empty** keep all accounts.

## 9. How the algorithms work

**Priority raising** (`emergency_requests.effective_priority`):
`effective = min(Critical, base + floor(hours_waiting / 24))`. Only pending / partly delivered requests rise.
Order: highest effective priority → SOS → oldest first.

**Dispatch & fair sharing** (`dispatch.py`): for each supply, serve priority tiers from Critical down. If a tier
can be fully served, everyone gets what they still need. If not, `fair_shares(stock, needs)`:

1. exact share = stock × need ÷ total need
2. everyone gets the whole-number part
3. leftover units go one by one to the largest fractional remainders (ties → older request)

Example: 50 food, two high requests for 60 and 40 → **30 and 20**. 7 kits, three requests of 4 → 3, 2, 2.

**Stock levels:** *Low* at or below the low-stock level (default 20), *Getting low* up to twice it, otherwise
*Good*. Inventory bars compare stock with a healthy level of five times the low-stock level.

## 10. Security

- Password hashing (Werkzeug scrypt) — passwords are never stored as plain text.
- CSRF token on every form; posts without a valid token are rejected.
- Server-side validation of every input; roles posted at sign-up are ignored; parameterised SQL (no SQL
  injection); auto-escaped HTML (no XSS); CSV exports protected against formula injection; 1 MB upload limit.
- 5 wrong passwords in a row → account locked for 15 minutes. Same error for unknown user and wrong password.
- Strict Content-Security-Policy (no inline scripts or styles), X-Frame-Options, nosniff, Referrer-Policy, HSTS
  on Vercel; HttpOnly + SameSite session cookie (Secure on Vercel); new session at login; safe redirects.
- Only one essential cookie. Theme is remembered on the device only if the visitor accepts.

## 11. Tests

`python -m unittest` runs **174 tests**:

| File | Covers |
|---|---|
| `test_dispatch.py` | fair_shares, tier planning, escalation in dispatch, the 50 → 30/20 example, manual dispatch |
| `test_requests.py` | priorities, 24h escalation, request lifecycle, ownership rules, shelters |
| `test_inventory.py` | quantity validation, stock levels and bars, stock changes, supply types, supplies CSV |
| `test_data_activity.py` | shelter/request CSV import, exports, activity history and UAE time, overview numbers |
| `test_notifier.py` | alert text, Telegram/WhatsApp/email, partial failures, fallback log |
| `test_storage_settings.py` | SQLite storage, saving to a file, seeding, reset / start empty, SQL-injection safety, permissions |
| `test_web.py` | sign-up form, username/email login, remember me, lockout, coordinator reset, email reset links, CSRF, headers, role access, XSS, every section |

## 12. Presentation split

- **Person 1 — Dispatch & logic:** priority order, 24h escalation, fair-share formula (`dispatch.py`, `emergency_requests.py`).
- **Person 2 — Inventory & storage:** stock levels, SQLite storage, CSV import/export (`inventory.py`, `storage.py`, `data_io.py`).
- **Person 3 — Security & roles:** access control, hashing, CSRF, lockout, headers, activity history (`settings.py`, `web_app.py`, `activity.py`).
- **Person 4 — UI, maps & alerts:** Arabic + RTL, dark mode, responsive design, Leaflet map, Telegram/WhatsApp/email (`templates/`, `static/`, `notifier.py`).

### Demo script (5 minutes)
1. Log in as `muhannad`. Show the overview cards and Inventory (First Aid Kits shows *Getting low*).
2. In a private window, create a Shelter staff account for Shelter B; request 60 food (high). Press **SOS** for 40 first aid kits.
3. Back as Coordinator: the SOS pill appears, the alert arrives on the team phone, Shelter A turns red on the map, Reports shows a shortage.
4. Set food to 50 (Inventory → Edit stock), request 40 more food (high) for Shelter C, press **Dispatch all fairly** → 30 / 20.
5. Show Activity history and the CSV export, switch to العربية and dark mode, then **Reset to demo data**.
