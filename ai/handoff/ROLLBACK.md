# Rollback — Free Game Tracker cloud migration

## Code rollback

Everything in this phase lives on `cloud/free-game-production`, two commits ahead of the
`master` baseline:

```
db8e43a  Baseline commit: current state of Free Game Tracker before cloud migration
421c28f  Cloud portability: Docker, runtime bridge, scheduling, backup/restore
```

To fully roll back the code: `git checkout master` (or reset the branch to `db8e43a`).
The Windows launchers (`Run Newsroom.bat`, `Install-HourlyTask.ps1`, etc.) were never
modified, so native Windows operation is unaffected regardless of which branch is checked
out — nothing about this phase touches the existing Task Scheduler path.

## Image rollback (once a real deploy exists)

Every image must be tagged with an immutable commit SHA (`docker-compose.yml` refuses to
run without `IMAGE_TAG` set — no bare `:latest`). Rolling back means re-pointing
`.deployed-tag` (read by `deploy/run.sh`) at the previous known-good SHA and re-running;
no rebuild needed if that image is still present locally or in a registry.

## State rollback

The database is untouched by an image rollback — `fgt_production_data` is a named volume
independent of the image. If a schema-incompatible change were ever deployed (not part of
this phase — no schema changes were made), the documented path is:
1. Stop the schedule (disable cron/timer).
2. Run `scripts/backup.py` if not already current.
3. Roll back to the previous image tag.
4. Verify `newsroom status`/`newsroom health` against the existing volume before
   re-enabling the schedule.

## Restore drill (proven this phase)

`scripts/restore.py --backup <path> --target-dir <isolated dir>` restores into a directory
that is never the live data path, then runs `PRAGMA integrity_check`. Verified end-to-end
locally: backup → restore into a separate volume → integrity check passed → a container
pointed at the restored copy read back the same 49 stored records and reported `healthy`.
