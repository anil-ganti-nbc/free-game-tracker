# Test results — Free Game Tracker cloud migration

## Native (Windows, .venv), before any change
`pytest -q` → **194 passed**, 1 non-fatal deprecation warning (httpx/starlette TestClient), in 50.29s.

## Native (Windows, .venv), after config.py/database.py/cli.py changes
`pytest -q` → **194 passed**, same warning, 50.26s. No regressions from the additive
identity/health commands or the alembic_home path-resolution fix.

## In-container (Linux AMD64, Docker Desktop)
Not run via pytest inside the image (no dev/test dependencies installed in the production
image by design — keeps the image lean). Verified instead via direct CLI invocation:

- `newsroom version` → `newsroom 0.1.0`
- `newsroom identity` → valid JSON, `release_channel: "experimental"`
- `newsroom health` (empty DB) → `operational_state: "degraded"`, exit 0
- `newsroom init-db` → succeeds after the alembic_home fix (failed before it, see KNOWN_ISSUES.md)
- `newsroom run --dry-run --no-notify` → exit 0, real sources fetched, nothing persisted
- `newsroom run --no-notify` (isolated test volume) → exit 0, 49 new + 61 new deals persisted
- `newsroom status` (fresh container, same volume) → identical data after recreation
- `python scripts/backup.py` → DB snapshot + reports tarball produced
- `python scripts/restore.py` → isolated restore, `PRAGMA integrity_check` = ok
- `newsroom status` / `newsroom health` against the restored copy → same 49 giveaways, `healthy`

## Not run
- Load/soak testing — not applicable to a one-shot hourly job at this scale
- SIGTERM-during-long-run test — `run` typically completes in well under a minute against
  real sources in this environment; deferred as low-value for a job this short, not because
  it's expected to be needed
