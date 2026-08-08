```yaml
project: free-game-tracker
stage: cloud-migration-phase-1 (portability + local verification)
baseline_commit: db8e43a
branch: cloud/free-game-production
target_environment: Linux AMD64 Docker (host TBD — no cloud host provisioned yet)
image_digest: not yet built for a pinned tag; local verification used tag free-game-tracker:test-local (disposable, removed after testing)
release_channel: experimental
operational_state: healthy (verified locally against isolated test state)
docker_build_verified: true
container_contracts_verified: true
persistent_state_verified: true
scheduler_verified: false
notifications_verified: false
backup_verified: true
restore_verified: true
tests_passed: 194
tests_failed: 0
contracts_changed: false
schema_changed: false
architecture_deviations: none
known_product_defects: see KNOWN_ISSUES.md (pre-existing, not touched)
known_portability_defects: see KNOWN_ISSUES.md (one found and fixed — alembic_home path resolution)
review_required: true
```

## What this phase covered

Portability and local Docker verification only. No cloud host has been provisioned, so
external-scheduler-over-real-time, host-reboot recovery, notification delivery from an
actual production network, and Tailscale/private-access verification remain outstanding —
they need a host decision, which requires your explicit approval on provider/cost per the
brief before I provision anything.

## What was verified, and how

All verification ran locally against Docker Desktop (Windows host, linux/amd64 target),
using disposable named volumes and a locally-tagged image (`free-game-tracker:test-local`,
removed after testing — never pushed anywhere).

| Check | Result |
|---|---|
| Existing test suite before changes | 194 passed, 0 failed |
| Existing test suite after changes | 194 passed, 0 failed |
| `docker build --platform linux/amd64` | succeeds reproducibly |
| Non-root execution | `id` inside container: `uid=10001(clank) gid=10001(clank)` |
| `newsroom version` in container | `newsroom 0.1.0` |
| `newsroom identity` in container | truthful; `release_channel: "experimental"` (not hard-coded production) |
| `newsroom health` on a fresh/empty DB | `operational_state: "degraded"`, honest `status_reasons: ["database file missing..."]` — not fabricated "healthy" |
| Safe dry run (`run --dry-run --no-notify`) | real sources fetched (Epic/Steam/GOG/GamerPower/etc.), exit 0, nothing persisted |
| Real one-shot run against isolated test volume | exit 0, 49 new + 61 new deals detected and persisted |
| Persistence across container recreation | fresh container against the same named volume reads back identical `source_health` rows |
| `docker compose config` (production + staging overlay) | both validate; no ports published, no Docker socket mounted, `restart: "no"` present |
| Backup (`scripts/backup.py`) | produced a consistent DB snapshot (sqlite3 online backup API, WAL-safe) + a reports tarball |
| Isolated restore (`scripts/restore.py`) | restored into a separate volume, `PRAGMA integrity_check` = ok (5 tables intact), never touched the source volume |
| Restored-state verification | a container pointed at the restored copy reported the same 49 stored giveaways and a truthful `healthy` state |

## Notable observation, not a defect

The dry run's real network calls from inside the Linux container succeeded against Epic,
Steam, GOG, GamerPower, PlayStation Plus, Xbox Game Pass, and GeForce Now without the
429/rate-limit behavior seen in OEM Radar's Shopify collector investigation. This doesn't
say anything about *why* OEM Radar's issue happens — it's a different collector hitting a
different storefront with different anti-bot posture — but it does rule out "all outbound
HTTP from this Docker Desktop host is broken," which is useful negative evidence for that
separate, still-open investigation.

## What still blocks a real production cutover

1. **Cloud host decision** — no provider/size/cost has been approved yet. Needed before
   external-schedule-over-time, reboot recovery, and Tailscale can be verified for real.
2. **Real webhook test** — verification here used no Discord webhook (empty/test values
   only), by design, to avoid posting to the live channel from test runs. The real webhook
   needs a validated run from the actual target network before promotion.
3. **Explicit promotion approval** — per the brief, passing tests never self-authorizes
   production. `NEWSROOM_RELEASE_CHANNEL` stays `experimental` until you say otherwise.
