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

## 2026-08-12T16:23Z
reason:              Fix — subscription-category events (PlayStation Plus, Xbox Game Pass, GeForce Now) were never eligible for Discord notification. `notify.build_discord_payload()` has always hard-filtered to `Category.GAME_PROMOTION`; subscription events had no notification path at all. Root-caused via a live incident: a PlayStation Blog article announcing Helldivers 2 joining PS Plus Extra/Premium never reached Discord, even though discovery/classification correctly detected it. Also hardened PS Blog discovery: the collector previously polled only `category/ps-plus/feed/` (roundup posts only); now also polls the general blog feed and content-detects standalone same-day articles that carry an access-change event without a roundup-style headline.
old_deployment_id:    free-game-tracker_2026-08-09_hetzner-01
new_deployment_id:    free-game-tracker_2026-08-12_hetzner-01
source_sha256:        3546540f5573d9d512d600096b03d84a5768c68f6f97aa6e62758df15a37310d
old_image_digest:     n/a (not recorded at initial deploy)
new_image_digest:     sha256:dbae5f597fb4eea50ffd3d4d2cd4ea39958609b553aaad9c2139ac99150c407e
config_revision:      no .env/compose changes; docker-compose.yml/staging.yml/.deployed-id mechanism unchanged, only .deployed-id's value updated
checks_performed:     local test suite (211/211), ruff/mypy (no new issues vs baseline), local Docker build + non-root/health/version checks, local dry-run + persistence-across-recreation on a throwaway volume, Hetzner staging validation (dry-run then non-dry-run against fgt_staging_data, Helldivers 2 confirmed present in the staging report), production cutover run against fgt_production_data with health/status verified healthy afterward (release_channel: production, no status_reasons)
result:               success
rollback_point:       free-game-tracker_2026-08-09_hetzner-01 (image + source tarball both still present on Hetzner; .deployed-id backed up on-host as .deployed-id.bak-2026-08-09)
operator_note:        Helldivers 2 was already present in production's stored state (the old code's discovery/classification always worked — only Discord delivery was broken), so this deploy does not retroactively announce it; the fix takes effect for events that are new *from this point forward*. Cutover run itself found "0 new" giveaways/breakouts and 1 new Steam deal (pre-existing, unrelated notify path) — no notification flood. Did not touch any of the other clanks' cron entries on this shared host (oem-radar, semiconductor-intelligence, chinese-tech-wire, feature-phone-clank, smartwatch-clank, watch-clank, smartphone-clank) — verified crontab diff before/after cutover was limited to the free-game-tracker line only. GitHub push and NAS migration remain separate, not-yet-authorized follow-ups.
