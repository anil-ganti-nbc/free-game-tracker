# Release runbook — Free Game Tracker on the Synology NAS

This is the repeatable procedure for shipping *any* future change — not just the
initial deployment. Follow the same steps whether it's the first release or the
fiftieth. Nothing here has been executed against the real NAS yet (no access until
2026-08-15) — this is the procedure to execute once it exists, and to keep using
after.

## Per-release identity (fill in every time)

| Field | Value |
|---|---|
| development branch | `cloud/free-game-production` (or a future feature branch merged into it) |
| candidate tag | the reviewed commit SHA, e.g. `421c28f` |
| production release tag | same SHA, once promoted — never a separate floating tag |
| candidate image | `free-game-tracker:<sha>` |
| deployed image digest | `docker inspect --format '{{.Id}}'` output, recorded at cutover time |
| staging state path | `/volume1/docker-data/free-game-tracker-staging/` (separate Shared Folder, never the production one) |
| production state path | `/volume1/docker-data/free-game-tracker/` |
| staging schedule | DSM Task Scheduler task, disabled by default, enabled only for a soak run |
| production schedule | DSM Task Scheduler task, hourly, calls `deploy/run.sh` |
| staging notification target | none / a distinct test webhook — never the real one |
| production notification target | the real `NEWSROOM_DISCORD_WEBHOOK_URL` |
| rollback image | the previous `deployed image digest`, kept loaded on the NAS |
| state compatibility boundary | current Alembic head at release time — see below |

## Procedure

### 1. Candidate build (dev machine, never on the NAS)

```bash
git -C "Free Game tracker" log -1 --oneline   # confirm the exact commit being released
docker build --platform linux/amd64 -t free-game-tracker:<sha> .
```

### 2. Local validation (dev machine, same checks already proven this session)

Re-run the checklist that's already known to work: non-root, `identity`/`health`
in-container, a dry run, persistence-across-recreation on a throwaway volume. Don't
skip this because "it worked last time" — a new commit is a new candidate.

### 3. Transfer to the NAS

```bash
docker save free-game-tracker:<sha> | gzip > free-game-tracker-<sha>.tar.gz
# copy to the NAS, then on the NAS:
gunzip -c free-game-tracker-<sha>.tar.gz | docker load
```

### 4. Staging validation, on the NAS, against isolated state

```bash
IMAGE_TAG=<sha> docker compose -f docker-compose.yml -f docker-compose.staging.yml \
  run --rm free-game-tracker run --dry-run --no-notify
```

Never point this at the production Shared Folder. If the change affects detection,
notifications, scheduling semantics, or the database schema, treat it as a full
product release per the brief — run the existing test suite and a non-dry-run against
the staging volume, not just a dry run.

### 5. Explicit promotion decision

Passing validation does not self-authorize production. Confirm explicitly (with
yourself, since this is now a one-operator project — but still make it a deliberate
step, not an automatic one) before touching the production schedule or volume.

### 6. Cutover — prevent duplicate/overlapping runs

1. Disable the production DSM Task Scheduler task (or wait if it's mid-run — check
   `docker ps` for a currently-running `free-game-tracker-production` container; a
   one-shot job finishes in well under a minute against real sources, so waiting is
   cheap).
2. Update `.deployed-tag` (read by `deploy/run.sh`) to the new SHA. This is the *only*
   file the scheduler's invocation depends on — no unit/task edit needed.
3. Run once manually against the production volume:
   `IMAGE_TAG=<sha> docker compose run --rm free-game-tracker run`
4. Check `newsroom status` / `newsroom health` against production state before
   re-enabling.
5. Re-enable the DSM Task Scheduler task.
6. Record the deployment: commit SHA, image digest, config revision, timestamp,
   checks performed, result — in `DEPLOYMENT_LEDGER.md` (this directory).

### 7. Rollback (if step 6 or later monitoring reveals a problem)

The previous image is still loaded on the NAS (never pruned automatically — that's
what makes rollback a normal operation, not an emergency rebuild). Reverse step 6:
disable schedule → set `.deployed-tag` back to the prior SHA → run once manually →
verify → re-enable. State is untouched by an image rollback unless the bad release
also changed the schema (see below).

## Schema-change releases are a different, heavier process

Nothing in this repo's history to date has changed the schema. If a future release
ever does:
1. Back up production state first (`scripts/backup.py`), independent of the release.
2. Treat the migration itself as product development requiring its own review, not
   routine deployment plumbing (per the brief).
3. Test the migration against a **restored copy** of production data
   (`scripts/restore.py` into an isolated path), never against production directly.
4. Only then apply it to production, immediately followed by another backup.
5. Confirm the rollback image can still start against the **pre-migration** backup if
   the schema change needs to be reverted — don't assume backward compatibility
   without checking Alembic's downgrade path.

## What "seamless" means here in practice

- The scheduler's job (`deploy/run.sh`) never changes between releases — only
  `.deployed-tag`'s contents change. No DSM Task Scheduler edits for a routine release.
- The production Shared Folder is never touched by a build or a staging run — only by
  step 6.4's explicit production invocation.
- Every release leaves the previous image loaded and `.deployed-tag`'s prior value
  recoverable from `DEPLOYMENT_LEDGER.md`, so rollback is "change one file back," not
  "figure out what the last working state was."
