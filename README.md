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

## RIT Phase 2 — Medical dispatch

The dashboard includes a **Medical dispatch – RIT Phase 2** section. Create a request by selecting a shelter
and specialty. The system filters for doctors whose status is `Available`, calculates the Euclidean distance
`sqrt((x2-x1)^2+(y2-y1)^2)`, and assigns the nearest eligible doctor. The assigned doctor is changed to
`Dispatched/Busy`. If no eligible doctor is available, the request is marked
`Pending Medical Dispatch - High Urgency`. The dashboard shows the request, doctor ID, specialty, hospital,
distance and status. Medical dispatch records are available as CSV and JSON exports.

**Demo-data notice:** the three hospitals and four doctors are fictional sample records added only to
demonstrate the workflow because no official hospital/doctor dataset was supplied. The displayed distance
is Euclidean coordinate distance using longitude as x and latitude as y; it is not a road distance or ETA.
The physical-supply dispatch system remains separate and unchanged.

## 2. Roles

| Role | Can do |
|---|---|
| **Coordinator** (the first account created) | Everything: stock, supply types, requests, shelters, dispatch, roles, password resets, CSV import, demo reset |
| **Shelter staff** | Create requests and SOS; edit / cancel **their own** open requests |
| **Volunteer** | View only |

People log in with their **username or email**. Nobody can sign up as Coordinator — the server ignores it.
Forgot password? The Coordinator presses **Reset password** in Team → Accounts & roles and gives the person a
temporary password.

## 3. Project structure

```
trf-emergency-relief/
├── api/index.py            # Vercel entry point (imports the Flask app)
├── web_app.py              # Website: routes, login, permissions, CSRF, security headers, dashboard numbers
├── settings.py             # Roles, permissions, priorities, limits, demo data, environment settings
├── inventory.py            # Stock, low-stock levels, supply types, supplies CSV import
├── emergency_requests.py   # Requests + shelters, validation, 24h priority raising
├── dispatch.py             # fair_shares (largest remainder) + supply dispatch
├── medical_dispatch.py     # nearest eligible hospital/doctor assignment (RIT Phase 2)
├── notifier.py             # Telegram / WhatsApp / email alerts with fallback log
├── activity.py             # Activity history (who did what, UAE time)
├── data_io.py              # CSV import (shelters, requests) and all CSV exports
├── storage.py              # SQLite/PostgreSQL + medical dispatch tables
├── translations.py         # English → Arabic interface text
├── templates/              # HTML pages (Jinja2)
├── static/                 # CSS, JavaScript, TRF logo and icons
├── tests/                  # automated unit tests (including medical dispatch)
├── samples/                # Example CSV files for the three imports
├── requirements.txt
├── vercel.json
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

Open http://127.0.0.1:5000, click **Create account** — the first account becomes the Coordinator. Data is saved
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
`api`, `templates`, `static`, `tests` and `samples` folders as folders.)

## 6. Deploy on Vercel

1. **vercel.com → Add New → Project** → import the repository. Framework preset: **Other**. Deploy.
2. **Add a database (important).** Vercel's servers forget files, so use Neon: in the project open
   **Storage → Create Database → Neon (Postgres)** and connect it. This adds `DATABASE_URL` automatically.
3. **Settings → Environment Variables**: add `SECRET_KEY` (a long random string —
   `python -c "import secrets; print(secrets.token_hex(32))"`), plus any alert settings from section 7.
4. **Redeploy** (Deployments → ⋯ → Redeploy) so the variables are used.
5. Open the site and create the first account (the Coordinator). Tables and demo data (Water 100, Food 80,
   First Aid Kits 30, Shelters A–C) are created automatically. `https://your-site.vercel.app/healthz` should
   say `"database": "PostgreSQL"`.

## 7. Alerts (optional — switch on any of them)

Each channel turns on when its variables are set. The Coordinator sees which ones are on under
*New emergency request*. If none are set, or all fail, alerts are saved and shown under Reports → Recent alerts.

| Channel | Variables | How to get them |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Talk to **@BotFather** → `/newbot`. Message the bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`. |
| WhatsApp | `WHATSAPP_PHONE`, `WHATSAPP_APIKEY` | Free **CallMeBot** service for one test phone: follow the steps on callmebot.com (send their activation message from the phone) to get an API key. Phone in `+9715…` form. |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | Gmail: `smtp.gmail.com`, port `587`, your Gmail address and a Google **App Password** (needs 2-step verification). |

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

`python -m unittest` runs **159 tests**:

| File | Covers |
|---|---|
| `test_dispatch.py` | fair_shares, tier planning, escalation in dispatch, the 50 → 30/20 example, manual dispatch |
| `test_requests.py` | priorities, 24h escalation, request lifecycle, ownership rules, shelters |
| `test_inventory.py` | quantity validation, stock levels and bars, stock changes, supply types, supplies CSV |
| `test_data_activity.py` | shelter/request CSV import, exports, activity history and UAE time, overview numbers |
| `test_notifier.py` | alert text, Telegram/WhatsApp/email, partial failures, fallback log |
| `test_storage_settings.py` | SQLite/PostgreSQL wrapper, seeding, reset / start empty, SQL-injection safety, permissions |
| `test_web.py` | sign-up, username/email login, remember me, lockout, password reset, CSRF, headers, role access, XSS, every section |

## 12. Presentation split

- **Person 1 — Dispatch & logic:** priority order, 24h escalation, fair-share formula (`dispatch.py`, `emergency_requests.py`).
- **Person 2 — Inventory & storage:** stock levels, SQLite/PostgreSQL wrapper, CSV import/export (`inventory.py`, `storage.py`, `data_io.py`).
- **Person 3 — Security & roles:** access control, hashing, CSRF, lockout, headers, activity history (`settings.py`, `web_app.py`, `activity.py`).
- **Person 4 — UI, maps & alerts:** Arabic + RTL, dark mode, responsive design, Leaflet map, Telegram/WhatsApp/email (`templates/`, `static/`, `notifier.py`).

### Demo script (5 minutes)
1. Log in as the Coordinator. Show the overview cards and Inventory (First Aid Kits shows *Getting low*).
2. In a private window, create a Shelter staff account for Shelter B; request 60 food (high). Press **SOS** for 40 first aid kits.
3. Back as Coordinator: the SOS pill appears, the alert arrives on the team phone, Shelter A turns red on the map, Reports shows a shortage.
4. Set food to 50 (Inventory → Edit stock), request 40 more food (high) for Shelter C, press **Dispatch all fairly** → 30 / 20.
5. Show Activity history and the CSV export, switch to العربية and dark mode, then **Reset to demo data**.
