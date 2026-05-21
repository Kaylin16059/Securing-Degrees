# HelpDesk — IT Ticketing System

A Flask-based ticketing system styled after the Securing Degrees dashboard.
Navy + teal navbar, CMYK accent colors (cyan, magenta, yellow), clean panels, and inline bar charts.

## File Structure

```
helpdesk_flask/
├── app.py                      ← Flask routes and logic
├── requirements.txt            ← Python dependencies (flask only)
├── Procfile                    ← For Railway / Heroku
├── railway.json                ← Railway deployment config
├── nixpacks.toml               ← Nixpacks build config
├── data/
│   └── helpdesk.sqlite         ← SQLite database (auto-created on first run)
├── static/
│   └── style.css               ← All styles — CMYK design system
└── templates/
    ├── base.html               ← Shared navbar + layout
    ├── index.html              ← Ticket list with filters
    ├── ticket_detail.html      ← Ticket detail + notes
    ├── new_ticket.html         ← Create ticket form
    ├── edit_ticket.html        ← Edit ticket form
    ├── dashboard.html          ← Bar chart analytics
    └── categories.html         ← Manage categories
```

## Run Locally

```bash
# 1. Install Python 3.10+

# 2. Install Flask
pip install flask

# 3. Run the app
python app.py

# 4. Open in browser
http://localhost:5000
```

No other dependencies — SQLite is built into Python.

---

## Deploy to Railway (recommended — free tier available)

1. Go to https://railway.app and sign up
2. Click **New Project → Deploy from GitHub repo**
3. Push this folder to a GitHub repo, connect it
4. Railway auto-detects Python via nixpacks — no config needed
5. Your app is live at a `*.railway.app` URL in ~60 seconds

Optional: add env vars `HELPDESK_USER` and `HELPDESK_PASS` in the Railway Variables tab to password-protect the app.

## Deploy to Render (free tier)

1. Go to https://render.com → New Web Service
2. Connect your GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python app.py`
5. Done

## Deploy to Heroku

```bash
heroku create my-helpdesk
git push heroku main
heroku open
```

---

## Customizing Colors

All CMYK colors are CSS variables at the top of `static/style.css`:

```css
--cyan:    #00B4C8;
--magenta: #E0007A;
--yellow:  #F5C800;
```

Change any of these to instantly retheme the entire app.

## Persistent Data

The SQLite database lives at `data/helpdesk.sqlite` and persists on disk.
On Railway/Render free tier, the filesystem resets on redeploy — for
permanent storage, mount a volume or swap SQLite for PostgreSQL
(change `sqlite3.connect(DB_PATH)` to use `psycopg2` + `DATABASE_URL`).
