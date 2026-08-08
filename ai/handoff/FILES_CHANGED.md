# Files changed — cloud/free-game-production, commit 421c28f

## Added
- `Dockerfile` — Linux AMD64, non-root (uid 10001), one-shot entrypoint, HEALTHCHECK
- `.dockerignore`
- `docker-compose.yml` — production (named volume `fgt_production_data`, requires `IMAGE_TAG` and a real webhook to be set, no ports, no socket)
- `docker-compose.staging.yml` — overlay: separate container name, separate volume (`fgt_staging_data`), webhook empty unless a distinct staging webhook is supplied
- `scripts/entrypoint.sh` — routes CLI subcommands, no browser launch
- `scripts/backup.py` — stdlib-only, sqlite3 online backup API (WAL-safe)
- `scripts/restore.py` — restores to an isolated target dir only, runs `PRAGMA integrity_check`
- `newsroom/runtime_bridge.py` — version/identity/health payload construction
- `deploy/crontab.example`, `deploy/free-game-tracker-run.service.example`, `deploy/free-game-tracker-run.timer.example`, `deploy/run.sh` — external one-shot scheduling, hourly (preserves existing cadence)
- `ai/handoff/` (this directory)

## Modified
- `newsroom/cli.py` — added `identity` and `health` commands (additive; `version`/`run`/`status`/etc. unchanged)
- `newsroom/config.py` — added `release_channel` (default `"experimental"`) and `alembic_home` (default unchanged from prior behavior) settings fields
- `newsroom/database.py` — `init_db()` now resolves alembic.ini/alembic/ via `settings.alembic_home` instead of always assuming `PROJECT_ROOT`

## Explicitly left unchanged
- All source/collector/detection logic (`newsroom/sources/*`, `newsroom/compare.py`, `newsroom/quality.py`)
- Notification logic (`newsroom/notify.py`)
- Database schema and all Alembic migrations
- `version` command's existing human-readable output format
- Windows launchers (`Run Newsroom*.bat`, `Install-HourlyTask.ps1`) — left in place for transitional rollback, not used by the container path
