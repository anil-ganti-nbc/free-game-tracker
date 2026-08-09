# Release runbook — Free Game Tracker

This is the repeatable procedure for shipping *any* future change — not just the
initial deployment. Follow the same steps whether it's the first release or the
fiftieth.

**Source-of-truth note (2026-08-09):** GitHub is not yet in use for this project.
There is no commit SHA to reference as deployment identity. Provenance for this phase
is an immutable, hashed source snapshot (`scripts/make_snapshot.sh`) plus a deployment
identifier of the form `free-game-tracker_<date>_<environment>-<NN>` — not a git
reference. A local git repository does exist on this machine (created before this
policy was clarified) and remains useful for diffing "what changed since baseline,"
but it is not the provenance mechanism and nothing here depends on it being pushed
anywhere. When GitHub is introduced later, these preserved snapshots establish
provenance for the initial import — see `DECISIONS.md` for the full reasoning.

**Target environment note:** current deployment target is a temporary Hetzner host
(`204.168.142.1`, hardened, Docker-ready) buying soak time until the Synology NAS is
reachable (2026-08-15). Everything below uses Hetzner's `deploy` user + systemd/cron
scheduling; `ai/handoff/NAS_DEPLOYMENT.md` covers the eventual NAS-specific
differences (DSM Task Scheduler instead of cron, Shared Folder bind-mounts) for when
that migration happens later — this runbook is the one to follow right now.

## Per-release identity (fill in every time)

| Field | Value |
|---|---|
| authoritative source | the local `Free Game Tracker` working copy on the dev machine |
| deployment identifier | `free-game-tracker_<YYYY-MM-DD>_<environment>-<NN>`, e.g. `free-game-tracker_2026-08-09_hetzner-01` |
| source snapshot | `snapshots/<deployment-id>.tar.gz` + `.sha256` (produced by `scripts/make_snapshot.sh`) — this tarball is the preserved, untouched baseline for this version |
| candidate image | `free-game-tracker:<deployment-id>` |
| deployed image digest | `docker inspect --format '{{.Id}}'` output, recorded at cutover time |
| staging state path | `~deploy/free-game-tracker-staging/data/` on Hetzner (separate directory, never the production one) |
| production state path | `~deploy/free-game-tracker/data/` on Hetzner |
| staging schedule | cron entry, disabled/commented by default, enabled only for a soak run |
| production schedule | cron entry, hourly, calls `deploy/run.sh` |
| staging notification target | none / a distinct test webhook — never the real one |
| production notification target | the real `NEWSROOM_DISCORD_WEBHOOK_URL` |
| rollback snapshot | the previous deployment identifier's tarball + image, both kept |
| state compatibility boundary | current Alembic head at release time — see below |

## Procedure

### 1. Produce a hashed source snapshot (dev machine, never on Hetzner)

```bash
cd "Free Game Tracker"
scripts/make_snapshot.sh hetzner
# -> prints deployment_id, archive path, and sha256 - record all three
```

This tarball is the exact, immutable input to the build. Nothing about the working
copy after this point affects what gets deployed — that's the point of snapshotting
before building, rather than building straight from a directory that keeps changing.

### 2. Candidate build (dev machine)

```bash
docker build --platform linux/amd64 -t free-game-tracker:<deployment-id> .
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
