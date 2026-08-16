# Release runbook — Free Game Tracker

This is the repeatable procedure for shipping *any* future change — not just the
initial deployment. Follow the same steps whether it's the first release or the
fiftieth.

**Source-of-truth note (2026-08-09, superseded 2026-08-16):** GitHub was not in use
for this project at the time this note was first written, and deployment identity for
the first several releases (through `free-game-tracker_2026-08-12_hetzner-03`,
inclusive) is an immutable, hashed source snapshot (`scripts/make_snapshot.sh`)
recorded in `DEPLOYMENT_LEDGER.md` — not a git SHA. That history is real and is not
being rewritten; see `DECISIONS.md` for why the snapshot model was chosen originally.

**As of the 2026-08-16 provenance/run-lock hardening pass, GitHub is the deployment
identity mechanism**, per the fleet-wide standard already proven on OEM Radar and
others. `free-game-tracker_2026-08-12_hetzner-03` — the production release
immediately prior to this pass — was confirmed byte-for-byte identical (modulo one
file's line-ending representation) to git commit `840641fe83b4`, closing the gap
between the old snapshot-based history and git before switching mechanisms, rather
than just asserting the two were equivalent. Every release from this pass forward
uses the model in the next section.

### Git provenance (current model)

```
accepted Git full SHA
        =
Docker OCI label org.opencontainers.image.revision
        =
runtime identity/version source_revision
```

- The Dockerfile's `ARG GIT_REVISION` (default `unknown`) is baked into the
  `org.opencontainers.image.revision` label and the `NEWSROOM_SOURCE_REVISION` env var
  at build time — never derived from a `.git` directory inside the image (none is
  copied in).
- Build with `--build-arg GIT_REVISION=$(git rev-parse HEAD)` (or via
  `docker-compose.yml`'s `build.args.GIT_REVISION`, sourced from a `GIT_REVISION` env
  var at build time).
- `newsroom version` / `newsroom identity` report `source_revision` — `"unknown"` for
  any local build that didn't supply one, never a fabricated value.
- The deployment identifier / image tag (`IMAGE_TAG`, read from `.deployed-id`) is now
  the short Git SHA, e.g. `free-game-tracker:a1b2c3d` — not a date-stamped snapshot
  identifier and never `latest`.
- Always build from a merged commit on `main` (feature branch → PR → merge → build the
  resulting SHA) — never from uncommitted working-tree changes, and never hot-patch
  Hetzner directly.

### Run lock (cross-process single-instance protection)

`newsroom run` acquires an OS-level advisory lock (`newsroom/run_lock.py`, `fcntl.flock`)
on `<database directory>/newsroom.lock` before doing any work, and releases it
automatically on exit — including on an exception. If another `run` already holds it
(e.g. an hourly cron tick firing while the previous one is still going), the new
invocation logs a clear message, prints `Skipped: ...`, and exits `0` without touching
the database — a lock refusal is deliberately not recorded as a collector failure in
`source_health`. This closes a real architectural gap: the dashboard's existing
`threading.Lock` (`newsroom/webapp.py`) only ever protected concurrent requests inside
one running process, not two independent `docker compose run` invocations, which is
exactly what an hourly cron entry can produce if a run ever takes longer than an hour.
An flock (not a PID-file-and-liveness-check) was chosen deliberately: every
`docker compose run --rm` invocation gets its own PID namespace, so a stale-lock check
based on "is the old PID still alive" would always see its own trivially-alive PID 1
and never correctly detect a genuinely dead run — the kernel-level flock sidesteps that
by releasing automatically when the holding process's file descriptor closes, for any
reason, without needing any liveness heuristic at all.

**Target environment note:** current deployment target is a temporary Hetzner host
(`204.168.142.1`, hardened, Docker-ready) buying soak time until the Synology NAS is
reachable (2026-08-15). Everything below uses Hetzner's `deploy` user + systemd/cron
scheduling; `ai/handoff/NAS_DEPLOYMENT.md` covers the eventual NAS-specific
differences (DSM Task Scheduler instead of cron, Shared Folder bind-mounts) for when
that migration happens later — this runbook is the one to follow right now.

## Per-release identity (fill in every time)

| Field | Value |
|---|---|
| authoritative source | the accepted full Git SHA on `main` (merged via PR — never a local working copy) |
| deployment identifier | the short Git SHA, e.g. `a1b2c3d` |
| candidate image | `free-game-tracker:<short-sha>` |
| deployed image digest | `docker inspect --format '{{.Id}}'` output, recorded at cutover time |
| staging state path | `~deploy/free-game-tracker-staging/data/` on Hetzner (separate directory, never the production one) |
| production state path | `~deploy/free-game-tracker/data/` on Hetzner |
| staging schedule | cron entry, disabled/commented by default, enabled only for a soak run |
| production schedule | cron entry, hourly, calls `deploy/run.sh` |
| staging notification target | none / a distinct test webhook — never the real one |
| production notification target | the real `NEWSROOM_DISCORD_WEBHOOK_URL` |
| rollback image | the previous short-SHA's image, kept on Hetzner (not pruned) |
| state compatibility boundary | current Alembic head at release time — see below |

## Procedure

### 1. Confirm the accepted Git revision

Merge the feature branch's PR first. The accepted revision is `main`'s HEAD full SHA
after merge — `git rev-parse HEAD`. Never build from uncommitted changes or an
unmerged branch.

### 2. Candidate build (dev machine, or wherever Docker is available)

```bash
GIT_REVISION=$(git rev-parse HEAD)
docker build --platform linux/amd64 \
  --build-arg GIT_REVISION="$GIT_REVISION" \
  -t "free-game-tracker:${GIT_REVISION:0:7}" .
# Verify before going further:
docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
  "free-game-tracker:${GIT_REVISION:0:7}"   # must equal $GIT_REVISION
```

### 3. Local validation (dev machine, same checks already proven this session)

Re-run the checklist that's already known to work: non-root, `identity`/`health`
in-container, a dry run, persistence-across-recreation on a throwaway volume. Don't
skip this because "it worked last time" — a new snapshot is a new candidate.

### 4. Transfer to Hetzner

```bash
docker save free-game-tracker:<deployment-id> | gzip > <deployment-id>.tar.gz
scp -i ~/.ssh/hetzner_clank_fleet <deployment-id>.tar.gz deploy@204.168.142.1:~/
ssh -i ~/.ssh/hetzner_clank_fleet deploy@204.168.142.1 \
  "gunzip -c ~/<deployment-id>.tar.gz | docker load"
```

### 5. Staging validation, on Hetzner, against isolated state

```bash
IMAGE_TAG=<deployment-id> docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  run --rm free-game-tracker run --dry-run --no-notify
```

Never point this at the production data directory. If the change affects detection,
notifications, scheduling semantics, or the database schema, treat it as a full
product release — run the existing test suite and a non-dry-run against the staging
volume, not just a dry run.

### 6. Explicit promotion decision

Passing validation does not self-authorize production. Confirm explicitly (with
yourself, since this is a one-operator project — but still make it a deliberate step,
not an automatic one) before touching the production schedule or data directory.

### 7. Cutover — prevent duplicate/overlapping runs

1. Disable the production cron entry (`crontab -e` on Hetzner, comment the line) or
   wait if it's mid-run — check `docker ps` for a currently-running
   `free-game-tracker-production` container; a one-shot job finishes in well under a
   minute against real sources, so waiting is cheap.
2. Update `.deployed-id` (read by `deploy/run.sh`) to the new deployment identifier.
   This is the *only* file the scheduler's invocation depends on — no cron edit needed
   for a routine release.
3. Run once manually against the production volume:
   `IMAGE_TAG=<deployment-id> docker compose run --rm free-game-tracker run`
4. Check `newsroom status` / `newsroom health` against production state before
   re-enabling.
5. Re-enable the production cron entry.
6. Record the deployment — identifier, source SHA-256, image digest, config revision,
   timestamp, checks performed, result — in `DEPLOYMENT_LEDGER.md` (this directory).

### 8. Rollback (if step 7 or later monitoring reveals a problem)

The previous image and source tarball are both still present on Hetzner (never
pruned automatically — that's what makes rollback a normal operation, not an
emergency rebuild). Reverse step 7: disable the cron entry → set `.deployed-id` back
to the prior deployment identifier → run once manually → verify → re-enable. State is
untouched by an image rollback unless the bad release also changed the schema.

## Schema-change releases are a different, heavier process

Nothing in this repo's history to date has changed the schema. If a future release
ever does:
1. Back up production state first (`scripts/backup.py`), independent of the release.
2. Treat the migration itself as product development requiring its own review, not
   routine deployment plumbing.
3. Test the migration against a **restored copy** of production data
   (`scripts/restore.py` into an isolated path), never against production directly.
4. Only then apply it to production, immediately followed by another backup.
5. Confirm the rollback image can still start against the **pre-migration** backup if
   the schema change needs to be reverted — don't assume backward compatibility
   without checking Alembic's downgrade path.

## No live editing on Hetzner

Hetzner is a deployment target, not a workspace. Feature development happens in the
local authoritative source only; Hetzner ever only receives built images produced
from a hashed snapshot of that source. If a fix is needed, it goes back through
steps 1-7 from the local copy — never a direct edit on the host, even for something
small. Otherwise the most current version of this clank ends up existing only on a
$5 VPS, which defeats the entire point of keeping a preserved, hashed provenance
trail.

## What "seamless" means here in practice

- The scheduler's job (`deploy/run.sh`) never changes between releases — only
  `.deployed-id`'s contents change. No cron edits for a routine release.
- The production data directory is never touched by a build or a staging run — only
  by step 7.3's explicit production invocation.
- Every release leaves the previous image and source tarball in place, and
  `.deployed-id`'s prior value recoverable from `DEPLOYMENT_LEDGER.md`, so rollback is
  "change one file back," not "figure out what the last working state was."
