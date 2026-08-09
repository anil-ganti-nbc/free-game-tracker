# Deployment ledger — Free Game Tracker

One entry per production deployment (promotion, rollback, or config-only change).
Append, never edit past entries. Fill in via `RELEASE_RUNBOOK.md` step 7.6.

**No GitHub in use for this project yet** — `deployment_id` and `source_sha256`, not a
commit SHA, are the provenance record. See `DECISIONS.md`.

Template:

```
## <UTC timestamp>
reason:              <why this deploy - feature, fix, rollback, config change>
old_deployment_id:    <e.g. free-game-tracker_2026-08-09_hetzner-01, or "none, initial deploy">
new_deployment_id:    <e.g. free-game-tracker_2026-08-10_hetzner-01>
source_sha256:        <sha256 of the new deployment's source snapshot tarball>
old_image_digest:     <digest or "n/a">
new_image_digest:     <digest>
config_revision:      <.env / compose overlay state, e.g. a short description>
checks_performed:     <staging validation, dry run, status/health check, etc - be specific>
result:               <success | rolled back | partial>
rollback_point:       <the deployment_id + image this can be rolled back to>
operator_note:        <anything a future reader needs, in plain language>
```

## 2026-08-09T14:53Z
reason:              Initial production deployment (Windows workstation -> Hetzner bridge host)
old_deployment_id:    none, initial deploy
new_deployment_id:    free-game-tracker_2026-08-09_hetzner-01
source_sha256:        12f4f668e8866c12b9a96d91c8531e1a453dd4198066ed3a3732ad3701326abe
old_image_digest:     n/a
new_image_digest:     sha256:9a01a07be8ab6a489efffa73ab4758201b6fc0b84c1ecef39650368258b1a694
config_revision:      docker-compose.yml fixed same-day (moved NEWSROOM_DISCORD_WEBHOOK_URL off `:?` hard-require, see DECISIONS.md #7); real webhook set directly on host by operator, never seen by the assistant
checks_performed:     non-root confirmed, identity/health truthful in-container, staging dry-run + real run against isolated volume with persistence-across-recreation proven on the actual Hetzner host (not just Docker Desktop), then one manual production run verified via `health` (operational_state: healthy, release_channel: production, no status_reasons)
result:               success
rollback_point:       none yet (this is the first deployment) - once a second deployment_id exists, this one becomes the rollback point
operator_note:        Hourly cron installed (`0 * * * *` -> deploy/run.sh -> logs/cron-<date>.log), matching the prior Windows Task Scheduler cadence. Docker and cron both confirmed systemd-enabled for reboot survival, but an actual reboot test has not been performed yet - that's still owed as part of the broader migration's reboot-recovery proof (planned against a different, lower-stakes clank first, per the addendum). The webhook set in this deployment's .env was accidentally echoed into the assistant's session transcript via `docker compose config` immediately after setup; operator was notified and has a rotation queued but not yet done as of this entry.
