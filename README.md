# Newsroom

> Status: Production ready

An internal newsroom sensor. Version 0.1 does exactly one thing: **detect newly
free PC games** on the Epic Games Store, Steam (100%-off only), and GOG.

It collects facts and evidence. It does not write articles, summaries, or
headlines, and it does not decide what is newsworthy — that is the editor's job.

## Status

**v0.3.** `run` fetches Epic, Steam (100%-off only), GOG (paid games now free),
and GamerPower (a secondary aggregator covering Prime Gaming, Humble, itch, etc.,
deduped against the first-party stores), compares against the previous run,
stores the snapshot, applies a configurable quality gate, writes Markdown + JSON
reports, and posts newly free games to Discord if a webhook is set. Each source
is fault-isolated, with per-source health tracking and a `status` command,
Discord rate-limit handling, report retention, Steam dev/publisher enrichment,
and an upcoming-giveaways heads-up section, plus a local web dashboard
(`newsroom serve`). 83 tests, ruff + mypy `--strict` clean.

## Layout

```
newsroom/
    sources/        # epic.py, steam.py, gog.py, _http.py (shared fetch)
    models.py       # the single NewsEvent domain model
    database.py     # SQLite storage (SQLAlchemy)
    config.py       # settings (env / .env)
    cli.py          # Typer commands
    main.py         # entry point
    tests/          # pytest suite
pyproject.toml
```

## Setup

```bash
uv sync --extra dev
```

## Use

```bash
uv run newsroom version      # print version
uv run newsroom init-db      # create the SQLite database and tables
uv run newsroom fetch epic   # fetch & print one source (epic | steam | gog | gamerpower)
uv run newsroom run          # full cycle: fetch all -> compare -> store -> report
uv run newsroom run --source epic --source gog   # limit to some sources
uv run newsroom run --dry-run --verbose          # preview without storing
uv run newsroom status       # last run, stored giveaways, per-source health
uv run newsroom serve        # local web dashboard (needs: uv sync --extra gui)
```

## Dashboard (GUI)

A small local web dashboard shows current giveaways, per-source health, the
upcoming heads-up, and a "Run now" button. Install the extra once, then serve:

```powershell
uv sync --extra gui
uv run newsroom serve         # then open http://127.0.0.1:8765
```

It reads the same database the CLI writes, auto-refreshes, and its "Run now"
button triggers the identical fetch/compare/report/notify cycle. It binds to
localhost only.

## Breakout new releases (Steam)

Alongside free games, each run trawls Steam's new releases for **well-reviewed
recent launches** — games released within a window (default 14 days) whose Steam
review tier meets a threshold (default "Very Positive"). These are a separate
signal from free games: they get their own dashboard panel with a **1–14 day
slider** to filter by age, and newly detected ones are posted to Discord. Tune
via `NEWSROOM_BREAKOUT_MAX_DAYS`, `NEWSROOM_BREAKOUT_MIN_REVIEW_TIER`, and
`NEWSROOM_ENABLE_BREAKOUTS`.

## Steam deals (well-reviewed discounts)

Each run also trawls Steam specials for **substantial discounts on games people
like** — at least a discount threshold (default 30%, and never 100% since that's
a free game) on titles that clear a review tier (default "Mixed" and up) *and* a
minimum review count (default 1000, to keep discounted shovelware out). They get
their own dashboard panel and Discord alerts. Tune via
`NEWSROOM_DEAL_MIN_DISCOUNT_PERCENT`, `NEWSROOM_DEAL_MIN_REVIEW_TIER`,
`NEWSROOM_DEAL_MIN_REVIEWS`, and `NEWSROOM_ENABLE_DEALS`.

Reports land in `reports/` as timestamped `report-<stamp>.{md,json}`, plus
`latest.md` / `latest.json` that always point at the most recent run.

## Scheduling (Windows, hourly)

Register a scheduled task once, from the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
```

This runs `newsroom run` every hour and appends output to `logs\run-<date>.log`.
Handy commands:

```powershell
Start-ScheduledTask -TaskName "Newsroom Free Game Tracker"        # run now
Get-ScheduledTaskInfo -TaskName "Newsroom Free Game Tracker"      # last/next run
Unregister-ScheduledTask -TaskName "Newsroom Free Game Tracker" -Confirm:$false  # remove
```

The task runs while you're logged in. To have it run when logged off, open Task
Scheduler and tick "Run whether user is logged on or not" (it will ask for your
password to store credentials).

## Discord notifications (optional)

Set a webhook URL and each run will post the **newly free** games — one card per
game, linking to the store. Because the comparison step only surfaces what's new,
each giveaway pings you exactly once (never re-posted on later runs).

In Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy URL.
Then set it in `.env` (or the environment):

```
NEWSROOM_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
NEWSROOM_NOTIFY_MIN_CONFIDENCE=0      # optional floor, 0–100
```

With no webhook set, notifications are silently disabled. A failed post is logged
and never breaks a run. Use `newsroom run --no-notify` to skip alerts for a
single run (dry runs never notify).

## Quality gate (filtering nothingburgers)

Detection stores everything, but you can control what *surfaces* to reports and
Discord so low-value freebies don't clutter the signal. Set in `.env`:

```
NEWSROOM_MIN_CONFIDENCE=70        # drop detections below this score (0–100)
NEWSROOM_REQUIRE_KNOWN_PRICE=true # drop giveaways with no real MSRP
NEWSROOM_MIN_PRICE=0              # minimum known MSRP to surface
```

The gate applies to new and ending-soon items; the database keeps the full
record regardless, and each report notes how many detections were suppressed.
Defaults are permissive (no filtering) if you leave these unset.


## Development

```bash
uv run ruff check newsroom
uv run mypy newsroom
uv run pytest
```
