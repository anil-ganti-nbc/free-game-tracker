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

No entries yet — nothing has been deployed yet.
