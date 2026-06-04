# Deployment & Operations Guide

> Everything you need to know to maintain, redeploy, or fix the automated pipeline.
> Read this before touching anything.

---

## How the System is Structured

There are two versions of the pipeline that do the same thing:

**Local version** — runs on the Vostro manually when needed
```
functions/regime_check.py   ← Nifty EMA50 gate
functions/bb_entry.py       ← entry scanner
functions/bb_exit.py        ← exit monitor
functions/notify.py         ← Gmail summary
functions/github_sync.py    ← commits data back to GitHub
main.py                     ← orchestrates all of the above
dailyrun.sh                 ← shell script to run main.py
```

**Production version** — runs automatically on DigitalOcean
```
do_functions/packages/nse_bb/daily_run/__main__.py  ← entire pipeline in one file
do_functions/project.yml                             ← DO config (NOT in GitHub)
```

The production `__main__.py` is self-contained — it does not import or reference
any other file in the repo. All logic (regime check, exit, entry, sync, notify)
is written inline in that single file.

**GitHub acts as the data layer** — `data/positions_bb.csv` and
`data/bb_trade_log.csv` are read from and written back to GitHub via the
GitHub REST API on every DO run. The Vostro does not need to be on.

---

## Files NOT in the GitHub Repo (Credentials)

These files exist only on the Vostro. You must recreate them on any new machine.

### `~/.env_nse_bb`
Stores all credentials for local runs:
```
GMAIL_SENDER=xxxx86@gmail.com
GMAIL_APP_PASSWORD=emzhacmvziIvoatf
GMAIL_RECIPIENT=xxxxxxxx86@gmail.com
GITHUB_PAT=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
GITHUB_REPO=xxxxxxxxxxxx/nse-bb-system
DO_TOKEN=dop_v1_8fc91552c52ae4583f8aae22730fdec404422ee8a146527aa7e90d6de6457b41
```

### `~/nse-bb-system/do_functions/project.yml`
DO deployment config — contains the same credentials as env vars for the function:
```yaml
packages:
  - name: nse_bb
    functions:
      - name: daily_run
        runtime: python:3.11
        limits:
          timeout: 300000
          memory: 512
        environment:
          GMAIL_SENDER: "xxxxxxx86@gmail.com"
          GMAIL_APP_PASSWORD: "emzhacmvziIvoatf"
          GMAIL_RECIPIENT: "xxxxx86@gmail.com"
          GITHUB_PAT: "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"
          GITHUB_REPO: "xxxxxxxxxxx/nse-bb-system"
```

Both files are in `.gitignore` and will never be committed to GitHub.

---

## Accounts & Services

| Service       | Account                      | Purpose                        |
|---------------|------------------------------|--------------------------------|
| GitHub        | xxxxxxxxxxxx@gmail.com       | Code repo + data layer         |
| DigitalOcean  | xxxxxxxxxxxx@gmail.com       | Hosts the serverless function  |
| Gmail (send)  | xxxxxxxx86@gmail.com         | Sends daily summary email      |
| Gmail (recv)  | xxxxxxxx86@gmail.com         | Receives daily summary email   |

---

## DO Setup Details

- **Namespace**: `python-xxxx-ns`
- **Namespace ID**: `fn-91149ee6-84d8-41bb-ad28-4648bf0e0a49`
- **API Host**: `https://faas-blr1-8177d592.doserverless.co`
- **Region**: `blr1` (Bangalore — IST-friendly)
- **Function**: `nse_bb/daily_run`
- **Runtime**: `python:3.11`
- **Trigger**: `nse-bb-trigger` — cron `00 04 * * 1-5` (Mon–Fri 4:00 AM UTC = 9:30 AM IST)
- **Timeout**: 300 seconds (5 minutes)
- **Memory**: 512 MB

---

## How to Run Locally (Manual)

```bash
cd ~/nse-bb-system
source ~/Documents/student/nifty250_work/myenv/bin/activate
python3 main.py
```

Or use the shell script:
```bash
~/nse-bb-system/dailyrun.sh
```

---

## How to Redeploy to DO After Code Changes

```bash
cd ~/nse-bb-system

# Authenticate doctl (use --access-token flag, not interactive prompt)
doctl auth init --access-token dop_v1_8fc91552c52ae4583f8aae22730fdec404422ee8a146527aa7e90d6de6457b41

# Connect to the namespace
doctl serverless connect fn-91149ee6-84d8-41bb-ad28-4648bf0e0a49

# Deploy
doctl serverless deploy do_functions --remote-build

# Verify
doctl serverless functions list
```

**Important**: Only edit `do_functions/packages/nse_bb/daily_run/__main__.py`
for production changes. The `functions/` folder is for local use only.

---

## How to Test the DO Function Manually

```bash
# Invoke and get activation ID
doctl serverless functions invoke nse_bb/daily_run --no-wait

# Wait 2 minutes then check result
doctl serverless activations result <activation_id>

# Check logs
doctl serverless activations logs <activation_id>

# List recent activations
doctl serverless activations list --limit 5
```

---

## How to Update the Schedule Trigger

Via DO console:
1. Go to **cloud.digitalocean.com/functions**
2. Click `nse_bb/daily_run`
3. Click **Triggers** tab
4. Edit or delete `nse-bb-trigger`

Current schedule: `00 04 * * 1-5` = 9:30 AM IST, Monday to Friday

---

## How to Add/Remove Stocks from Watchlist

Edit `data/watchlist.csv` directly — add or remove rows.
Columns: `Symbol, Industry, IsBanking`

```bash
cd ~/nse-bb-system
nano data/watchlist.csv
git add data/watchlist.csv
git commit -m "Update watchlist — added XYZ"
git push
```

The next DO run will automatically pick up the new watchlist from GitHub.

---

## How to Manually Add a Position

If you place a real trade and want to track it:

```bash
nano data/positions_bb.csv
# Add a row:
# SYMBOL,YYYY-MM-DD,EntryPrice,Quantity,Real
git add data/positions_bb.csv
git commit -m "Add real position — SYMBOL"
git push
```

Use `TrackType = Real` for actual money, `Paper` for paper trades.

---

## How to View Trade History

Open in browser:
```
https://github.com/xxxxxxxxxxxx/nse-bb-system/blob/master/data/bb_trade_log.csv
```

Or locally:
```bash
cat ~/nse-bb-system/data/bb_trade_log.csv
```

---

## Gmail App Password

- Account: xxxxxxxx86@gmail.com
- App password name: nse-bb-system
- If it stops working (Google revokes it): go to myaccount.google.com →
  Security → App Passwords → delete old → create new → update
  `~/.env_nse_bb` and `do_functions/project.yml` → redeploy

---

## GitHub PAT

- Account: xxxxxxxxxxx@gmail.com
- Token name: nse-bb-system
- Scope: repo (full)
- If expired: go to github.com → Settings → Developer settings →
  Personal access tokens → regenerate → update
  `~/.env_nse_bb` and `do_functions/project.yml` → redeploy

---

## Troubleshooting

**Email not received:**
- Check DO activation logs for errors
- Verify Gmail app password is still valid
- Check spam folder

**Function not running on schedule:**
- Go to DO console → Functions → `nse_bb/daily_run` → Triggers
- Verify `nse-bb-trigger` is Enabled and shows a future Next Run time

**GitHub sync failing:**
- GitHub PAT may have expired — regenerate and redeploy
- Check if repo is accessible at github.com/xxxxxxxxxxxx/nse-bb-system

**Wrong positions showing:**
- Edit `data/positions_bb.csv` directly on GitHub or locally and push
- DO reads it fresh on every run

**To redeploy from scratch on a new machine:**
1. Clone repo: `git clone https://github.com/xxxxxxxxxxxx/nse-bb-system.git`
2. Recreate `~/.env_nse_bb` with credentials
3. Recreate `do_functions/project.yml` with credentials
4. Install doctl and authenticate
5. Connect to namespace and deploy

---

*Last updated: June 2026*
