# Deployment ledger — Free Game Tracker (Synology NAS)

One entry per production deployment (promotion, rollback, or config-only change).
Append, never edit past entries. Fill in via `RELEASE_RUNBOOK.md` step 6.6.

Template:

```
## <UTC timestamp>
reason:              <why this deploy — feature, fix, rollback, config change>
old_commit:           <sha or "none, initial deploy">
new_commit:           <sha>
old_image_digest:     <digest or "n/a">
new_image_digest:     <digest>
config_revision:      <.env / compose overlay state, e.g. a short hash or description>
checks_performed:     <staging validation, dry run, status/health check, etc — be specific>
result:               <success | rolled back | partial>
rollback_point:       <the image/commit this can be rolled back to>
operator_note:        <anything a future reader needs, in plain language>
```

No entries yet — nothing has been deployed to the real NAS. This file exists now so
the very first deployment (once NAS access starts 2026-08-15) has somewhere to record
itself immediately, rather than that discipline being invented under time pressure at
cutover time.
