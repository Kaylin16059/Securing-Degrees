# School Partnership Dashboard — Securing Degrees

Internal dashboard for tracking charter school outreach across TX, NC, SC, and GA.

---

## Running Locally

```bash
pip install flask gunicorn
python app.py
```
Open http://127.0.0.1:5000

---

## Deploying to Railway

### Option A — Deploy via GitHub (recommended)

1. Push this folder to a GitHub repo (can be private)
2. Go to https://railway.app and log in
3. Click **New Project → Deploy from GitHub repo**
4. Select your repo — Railway will auto-detect Python and build it
5. Once deployed, click **Settings → Generate Domain** to get a public URL

That's it. Railway reads the `Procfile` and `railway.json` automatically.

### Option B — Deploy via Railway CLI

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# From inside this folder:
railway init        # creates a new project
railway up          # deploys the app
railway domain      # generates a public URL
```

### Environment Variables

No required env variables. Railway injects `PORT` automatically and the app reads it.

If you want to lock the dashboard to internal use only, you can add HTTP Basic Auth
by setting these in Railway's Variables tab:
- `DASHBOARD_USER` — username
- `DASHBOARD_PASS` — password

Then add the auth middleware below to app.py (optional, see note in app.py).

---

## What's Inside

- **1,556 schools** (1,469 charter + 87 district/network orgs) across TX, NC, SC, GA
- **2,071 contacts** loaded from the Securing Degrees contact list
- **Priority scores & ranks** from the ranked charter school list
- **Enrollment data** from NCES CCD 2024-25

## Pipeline Stages
Prospecting → Contacted → Meeting Set → Follow Up → Partnered / Not Interested

## Updating Data
Replace `data/school_partnership_dashboard.sqlite` with a new version and redeploy.
For Railway, push the updated file to GitHub and Railway will redeploy automatically.

