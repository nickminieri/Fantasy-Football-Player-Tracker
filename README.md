# Fantasy Football Player Tracker

Auto-syncs your **Sleeper** dynasty roster, watches each player for **news,
injuries, depth-chart moves, and team changes**, and pushes alerts to
**Telegram**. It also keeps an always-current [`data/ROSTER.md`](data/ROSTER.md)
snapshot and a SQLite database of every player you track.

Runs entirely on **free GitHub Actions** on a schedule — no server, no cost, no
machine to keep on.

## How it works

```
GitHub Actions (every 30 min)
        │
        ├─ Sleeper API ── your league → your roster → full player data
        │                 (team, position, injury, depth chart, age, exp)
        ├─ detect changes ── new injury? moved up depth chart? traded?
        ├─ ESPN news ─────── recent articles per player
        ├─ Telegram ──────── push new items to your chat
        └─ commit data/ ──── DB + ROSTER.md saved back to the repo
                             (this is how it remembers what it already sent)
```

Everything is read-only against Sleeper (no login, no API key needed). The
committed SQLite DB is what prevents duplicate notifications between runs.

## Setup

### 1. Create a Telegram bot (2 minutes)

1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts.
   It gives you a **bot token** like `123456:ABC-DEF...`.
2. Send any message to your new bot (e.g. "hi") so it has a chat with you.
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and
   find `"chat":{"id": ...}` — that number is your **chat ID**.

### 2. Find your Sleeper league ID

You need your Sleeper **username** and your dynasty **league ID**. To find the
league ID, run locally (see below) `python -m fftracker discover`, or grab it
from the Sleeper web app URL: `sleeper.com/leagues/<LEAGUE_ID>/...`.

### 3. Add GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret | Required | Example |
|--------|----------|---------|
| `SLEEPER_USERNAME` | ✅ | `nickminieri` |
| `SLEEPER_LEAGUE_ID` | recommended | `987654321098765432` |
| `TELEGRAM_BOT_TOKEN` | ✅ | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | ✅ | `12345678` |
| `SEASON` | optional | `2026` (defaults to current year) |

> If you omit `SLEEPER_LEAGUE_ID` and you're in exactly one NFL league this
> season, it's auto-detected. In multiple leagues, you must set it.

### 4. Enable the workflow

The workflow in [`.github/workflows/track.yml`](.github/workflows/track.yml)
runs every 30 minutes. Go to the **Actions** tab, enable workflows if prompted,
and click **Run workflow** on "Fantasy Tracker" to do a first run immediately.

That's it. New player news will start arriving in Telegram, and
`data/ROSTER.md` will update itself.

## Local usage (optional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SLEEPER_USERNAME=yourname
export TELEGRAM_BOT_TOKEN=...      # only needed for alerts
export TELEGRAM_CHAT_ID=...

python -m fftracker discover        # list your leagues + IDs
python -m fftracker test-telegram   # verify Telegram works
python -m fftracker run             # full sync + news + alerts
python -m fftracker report          # regenerate ROSTER.md from the DB (no network)
```

## Customizing

Copy `config.example.yaml` to `config.yaml` to:
- add a **watchlist** of players to track even if they aren't on your roster,
- toggle which alert types you want (`news`, `injuries`, `depth_chart`, `team_changes`),
- set news retention.

`config.yaml` is git-ignored so you can keep it local; for Actions, the
defaults (all alerts on) apply unless you commit a `config.yaml`.

## Notes & limitations

- **ESPN news** comes from an undocumented endpoint — it's free but has no SLA
  and can change. News failures are non-fatal; the rest of the run still works.
- **First run is quiet by design:** it snapshots your roster without firing
  alerts for pre-existing state, then only alerts on *changes* afterward.
- **Schedule latency:** GitHub may delay cron runs during peak load, so "every
  30 min" is a target, not a guarantee. Tighten the cron in `track.yml` if you
  want, but very frequent runs add commit noise.
- **Sleeper rate limit:** stay under 1000 calls/min. This app makes a handful
  per run, well within limits.

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Tests stub all network calls, so they run offline.
