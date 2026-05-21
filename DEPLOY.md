# MKM Projects — Deployment Guide

## Why Railway zip upload fails
Railway's zip deploy wraps all files in a folder named after the zip file,
so it sees `helpdesk_flask_deploy/` instead of your app root.
**Use GitHub instead** — it's free and takes 3 minutes.

---

## Option 1 — Railway via GitHub (recommended, free)

### Step 1: Put files on GitHub
1. Go to https://github.com and sign in (or create a free account)
2. Click **+** → **New repository** → name it `mkm-projects` → **Create repository**
3. On the next screen, click **uploading an existing file**
4. Drag ALL these files/folders into the upload box:
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
   - `start.sh`
   - `railway.json`
   - `nixpacks.toml`
   - `static/` folder
   - `templates/` folder
   - `data/` folder
5. Click **Commit changes**

### Step 2: Deploy on Railway
1. Go to https://railway.app → **New Project**
2. Click **Deploy from GitHub repo**
3. Connect your GitHub account → select `mkm-projects`
4. Railway auto-detects Python and deploys in ~60 seconds
5. Click **Generate Domain** to get a public URL

### Step 3: Set environment variables (important!)
In Railway dashboard → your service → **Variables** tab, add:
```
SECRET_KEY = (generate one: python -c "import secrets; print(secrets.token_hex(32))")
```

---

## Option 2 — Render (drag-and-drop zip works here)

Render handles zip uploads correctly — no GitHub needed.

1. Go to https://render.com → sign up free
2. Click **New** → **Web Service**
3. Choose **Deploy manually** (upload a zip)
4. Upload the zip file
5. Set:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `python app.py`
6. Add environment variable: `SECRET_KEY = your-random-string`
7. Click **Deploy**

---

## Option 3 — Run locally

```bash
pip install flask flask-login werkzeug
python app.py
# Open http://localhost:5000
```

Default login: **admin / admin123** — change via My Profile after first login.

---

## Persistent data on Railway/Render

SQLite resets on redeploy on free tiers (no persistent disk).
For permanent data, either:
- **Railway**: Add a Volume in the dashboard, mount to `/app/data`
- **Render**: Add a Disk, mount to `/opt/render/project/src/data`
- Or upgrade to a paid plan (both offer persistent disk on paid tiers)
