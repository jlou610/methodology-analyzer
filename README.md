# Methodology Analyzer

A multi-user web app where each trader defines their **own** trading methodology
as a structured spec, then submits a current market situation and gets an
AI-generated read graded against *their* methodology — with a record of what
actually happened.

Portfolio / demo artifact. Not a commercial product.

## Status

- **Weekend 1 (this build):** auth shell (email + password), multi-tenant schema,
  per-user data isolation, deploy config for Render. ✅
- **Weekend 2:** methodology spec builder + AI analyzer (Claude, prompt-cached)
  + outcome review. Rate limit: 10 analyses / user / day.

## Run locally

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy .env.example .env                            # then edit SECRET_KEY
python app.py                                     # http://localhost:5000
```

## Architecture

- **Flask** + **Flask-Login** (email/password, Werkzeug password hashing).
- **SQLite** via `db.py`; path from `$DB_PATH`. Every feature row carries
  `user_id`; every query is scoped to the logged-in user.
- Tables: `users`, `methodology_specs` (the spec JSON), `analysis_sessions`.

## Deploy to Render

Requires a **Starter** web service (~$7/mo) — the free tier can't mount a
persistent disk, and SQLite needs one to survive restarts.

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. `render.yaml`
   provisions the web service + a 1 GB disk at `/var/data` and sets `DB_PATH`,
   `SECRET_KEY` (auto-generated). Add `ANTHROPIC_API_KEY` manually (Weekend 2).
3. Deploy. Health check is `/healthz`.

### Backups

`scripts/backup_db.py` writes a consistent snapshot via SQLite's online-backup
API. Wire it to a nightly **Render Cron Job**. For off-disk recovery, set the
`R2_*` env vars (Cloudflare R2 free tier) and `pip install boto3`; otherwise
snapshots live on the disk under `backups/` (retains last 7).
