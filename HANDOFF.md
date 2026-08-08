# Newsroom — project notes & resume guide

Single source of truth for picking the project back up. The README is the
user-facing "how to run it"; this file is the developer/context map.

---

## Status

**v0.7 shipped.** Free games + Steam breakouts + Steam deals + local dashboard.
- **99 tests pass; `ruff check` clean; `mypy --strict` clean (34 files).**
- v0.7 added a THIRD sensor lane: `sources/steam_deals.py` — Steam specials
  discounted >= threshold (default 30%, < 100%) on games with review tier >= floor
  (default "Mixed", full ladder now in steam_breakouts `_TIER_ORDER`) AND
  >= min reviews (default 1000). Own model (`SteamDeal`), table (`steam_deals`),
  dashboard panel, Discord alerts. `_run_deals` in run_pipeline, fault-isolated,
  health source "steam_deals". Reuses `parse_review_summary`/`tier_meets` from
  steam_breakouts. Config: enable_deals, deal_min_discount_percent,
  deal_min_review_tier, deal_min_reviews.
- v0.6 added a SECOND sensor lane: `sources/steam_breakouts.py` finds recently
  released, well-reviewed games (appdetails release date + appreviews tier).
  Own model (`NewRelease`), own table (`new_releases`), own dashboard panel with
  a 1-14 day slider, Discord alerts on new ones. Config: `enable_breakouts`,
  `breakout_max_days`, `breakout_min_review_tier`. Trawled inside `run_pipeline`
  (`_run_breakouts`), fault-isolated + health-tracked as source "steam_breakouts".
- Verify on a real Python 3.12 machine:
  `uv sync --extra dev && uv run pytest && uv run ruff check newsroom && uv run mypy newsroom`
- Sandbox caveat: the build environment only has Python 3.10 and can't download
  3.12, so it was verified under 3.10 with a startup shim for `UTC`/`StrEnum`.
  That shim is NOT in the project — real verification happens on the user's 3.12
  box. `datetime.fromisoformat`/`strptime` code was written to work on both.

## What it does (one paragraph)

Every run: fetch current free PC games from several sources → dedupe → compare
against the previous run (new / ending-soon / expired) → store the full snapshot
in SQLite → apply a quality gate for what surfaces → write Markdown + JSON
reports (+ an upcoming-giveaways heads-up) → post newly free games to Discord if
configured. It collects facts and evidence only; the human editor decides what's
newsworthy and writes the articles. Designed to run unattended on an hourly
Windows scheduled task.

## Architecture map (newsroom/)

- `models.py` — the single `NewsEvent` (Pydantic) + `Confidence` value object
  (score 0-100 + reasons) + `UpcomingGame` (lightweight dataclass). Enums:
  `Source` (epic/steam/gog/gamerpower), `Category` (game_promotion),
  `PromotionType` (giveaway/free_weekend/permanently_free/full_discount).
  `NewsEvent.event_key` = `"{source}:{url}"` — the cross-run identity.
- `config.py` — `Settings` (pydantic-settings, env prefix `NEWSROOM_`, reads
  `.env`). Singleton `settings`. Holds DB path, HTTP retry knobs, reports dir,
  retention, staleness, quality-gate thresholds, Discord webhook, GamerPower tz.
- `database.py` — SQLite via SQLAlchemy. `NewsEventRow` + `to_row`/`to_event`;
  `UtcDateTime` type keeps datetimes UTC-aware across the round trip; lazy
  `get_engine`/`get_session_factory`/`reset_engine`; `session_scope`;
  `sync_events` (insert/update/delete to match latest run); `load_all_events`;
  `SourceHealthRow` + `record_source_result`/`load_source_health`.
- `compare.py` — pure `compare(previous, current, ending_soon_hours)` → `RunDiff`
  (disjoint new / ending_soon / expired). `deduplicate(events)`.
- `quality.py` — pure `passes_quality_gate` / `filter_events`
  (min_confidence, min_price, require_known_price). Gates what SURFACES only.
- `report.py` — `render_markdown` / `build_report_data` / `write_reports`
  (Markdown + JSON, facts-only "NEW STORY CANDIDATE" layout, `latest.*` copies,
  suppressed count, upcoming section) + `prune_old_reports`.
- `notify.py` — Discord: `build_discord_payload` (one embed/game, cap 10),
  `post_discord` (429-aware, fault-isolated), `notify_new_giveaways`.
- `sources/_http.py` — shared `SourceError` + `fetch_json` (retries/backoff).
- `sources/epic.py` — Epic `freeGamesPromotions`: live giveaways
  (`parse_free_games`) + upcoming (`parse_upcoming_free_games`). Rule: active
  promotional offer with `discountPercentage == 0`. Excludes ADD_ON/BUNDLE.
- `sources/steam.py` — featuredcategories `specials`, `discount_percent == 100`
  only; enriches dev/publisher via `appdetails`.
- `sources/gog.py` — catalog `price=between:0,0`, keep `base>0 && final==0`
  (paid game now free); excludes F2P/demos.
- `sources/gamerpower.py` — secondary aggregator (Prime Gaming, Humble, itch,
  Fanatical…). Skips Epic/Steam/GOG platforms (complement, not duplicate).
  Confidence capped at 90 with "verify at store".
- `cli.py` — Typer app. Commands: `version`, `init-db`, `fetch <source>`,
  `run` (flags: `--source` repeatable, `--ending-soon-hours`, `--dry-run`,
  `--no-notify`, `--verbose`), `status`. `_execute_run` is the testable seam
  (no network). `_fetch_all_sources` isolates each source + records health.
- `webapp.py` — FastAPI dashboard (optional `gui` extra). `get_state()` reads
  DB + health + `latest.json`; `/api/state`, `/api/run` (thread-locked), `/`
  serves one self-contained HTML page. Launched by `newsroom serve`.
- `main.py` — entry point (`newsroom.main:app`). `newsroom/tests/` — pytest +
  `fixtures/*.json` (each source has a hand-built fixture).

`cli.run_pipeline()` is the shared orchestration used by both the `run` command
and the dashboard's "Run now".

## Pipeline order (important)

load previous snapshot → compare → `sync_events` (store full) → quality-gate the
surfaced diff → write reports → notify. Comparison reads the OLD state before it
is overwritten. Storage keeps EVERYTHING; the gate only affects what the editor
sees.

## Config / .env reference (all prefixed NEWSROOM_)

`DATABASE_PATH`, `DATABASE_ECHO`, `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RETRIES`,
`HTTP_RETRY_BACKOFF_SECONDS`, `REPORTS_DIR`, `REPORT_RETENTION_DAYS` (30),
`SOURCE_STALE_HOURS` (6), `GAMERPOWER_UTC_OFFSET_HOURS` (0), `LOG_LEVEL`,
`DISCORD_WEBHOOK_URL`, `MIN_CONFIDENCE`, `MIN_PRICE`, `REQUIRE_KNOWN_PRICE`.
The user's live `.env` currently sets: webhook (real, gitignored),
`MIN_CONFIDENCE=70`, `REQUIRE_KNOWN_PRICE=true`, `MIN_PRICE=0`.

## Scheduling

`scripts/register-task.ps1` registers a Windows task running `newsroom run`
**hourly** (calls `scripts/run-newsroom.ps1`, which logs to `logs/`). Re-run the
register script after any cadence change. Runs while logged in by default.

## Design principles held throughout

Boring, explicit, readable. One normalized model. No source knows about DB/
reporting/notifications. No abstraction added before duplication existed (the
shared `_http.py` was extracted only when the 3rd source needed it). Every
detection explains WHY (confidence + reasons). Fault isolation everywhere — one
broken source/notify/upcoming-fetch never aborts a run. Research each source's
real schema before writing a parser; never build blind (GamerPower/3.12 were the
only "verify-live-on-your-machine" exceptions, both with stable known schemas).

## Known limitations / intentional debt

- Steam `specials` is a curated subset — won't catch every 100%-off game (user
  accepted this).
- GamerPower behind Cloudflare (can't fetch from the build sandbox); its tz is
  assumed via the offset knob; its `end_date` display tz still to be calibrated.
- Prime Gaming/Humble/itch/Fanatical have no clean first-party API — reached only
  via GamerPower. Prime-direct would need a headless browser (rejected: account
  risk + fragility).
- Reports are timestamped files (now pruned); no web view yet (→ GUI).
- Upcoming = Epic only (the only source exposing it).

---

## GUI (DONE — v0.5)

Built as chosen: an interactive, clean-minimal local web dashboard.
`newsroom serve` (needs `uv sync --extra gui`) → `http://127.0.0.1:8765`. Shows
current giveaways, source health, upcoming heads-up, and a "Run now" button that
calls `run_pipeline`. Localhost-only; reads the live DB; auto-refreshes. Tested
with FastAPI TestClient over a temp DB (no browser). Original design notes kept
below for reference.

<details><summary>Original GUI planning notes (superseded by the build)</summary>


**What a GUI would show:** current free games (from `newsroom.db` /
`latest.json`), run history, per-source health (we already track it), upcoming
giveaways, and ideally a "trigger a run now" button + config editing.

**Design forks to decide with the user (ask before building):**
1. **Shape** — (a) local desktop web dashboard served by the tool
   (`newsroom serve` → FastAPI/Flask + a single HTML page reading the DB); (b) a
   native desktop app; (c) a static HTML report viewer (just prettify
   `latest.json`). A local web dashboard (a) is the most natural fit for the
   existing Python/CLI architecture and stays "boring."
2. **Read-only vs interactive** — just view data, or also trigger runs / edit
   config / manage the quality gate from the UI?
3. **Live vs snapshot** — poll the DB live, or render the latest report?
4. **Tech** — keep it dependency-light (stdlib `http.server` or FastAPI + one
   vanilla HTML/JS page, no heavy frontend framework) to match the project's
   "boring architecture" ethos. Avoid a build step if possible.

**Recommended starting point (proposal to run past the user):** a `newsroom
serve` command that runs a tiny local FastAPI (or stdlib) server exposing the DB
as JSON + one self-contained HTML page: a table of active giveaways, source-health
panel, upcoming section, and a "run now" button. Read-only first, add actions
later. Reuses everything already built; no new data model.

**Implementation notes when we build it:**
- The data is already there: `load_all_events()`, `load_source_health()`,
  `latest.json`. A GUI is mostly a read layer + optional "run now" that calls the
  same `run` path in a thread.
- Keep the pure/IO split: a `webapp.py` (or `server.py`) module; endpoints call
  existing functions; one HTML template. Add `fastapi`/`uvicorn` under an
  optional extra (like the browser idea) so core stays lean.
- Tests: endpoint tests with FastAPI TestClient over a temp DB; no browser.
- Follow the same milestone discipline: propose plan → approve → build one
  milestone → verify (pytest/ruff/mypy) → stop for approval.

</details>

## Housekeeping

- Old `newsroom_intelligence/` folder (first-attempt scaffold) still sits in the
  project, unused — deletion was blocked from the sandbox; user can remove it.
- The user's Discord webhook is real and lives in the gitignored `.env`; treat as
  a secret, never echo it.
