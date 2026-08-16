# Deployment ledger — Free Game Tracker

One entry per production deployment (promotion, rollback, or config-only change).
Append, never edit past entries. Fill in via `RELEASE_RUNBOOK.md` step 7.6.

**Provenance note:** entries through `free-game-tracker_2026-08-12_hetzner-03` use
`deployment_id`/`source_sha256` (a hashed source snapshot), not a git SHA — GitHub
wasn't in use for this project yet. See `DECISIONS.md`. As of the 2026-08-16
provenance/run-lock hardening pass, `git_sha` is the provenance record going forward,
per `RELEASE_RUNBOOK.md`.

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

## 2026-08-12T17:11Z
reason:              Post-incident hardening pass (same-day follow-up to the previous entry): (1) a category→notification coverage invariant test that fails CI if a registered source can emit a NewsEvent category with no Discord delivery path in `notify.CATEGORY_NOTIFIERS`; (2) per-run "Delivery summary" logging (detected/eligible/posted/suppressed/failed, per-category breakdown) so a future silent gap is visible without a live incident; (3) `notify_new_giveaways`/`notify_new_subscription_events` now return a small `DeliveryResult` instead of a bare bool, distinguishing "nothing eligible" / "webhook not configured" / "payload construction failed" / "delivery failed" / "posted"; (4) a real, pre-existing bug found *while validating (2)*: `alembic/env.py`'s boilerplate `fileConfig()` call (triggered by every `init_db()`, i.e. every command) was silently disabling every `newsroom.*` logger and resetting the root logger's level to `alembic.ini`'s `WARNING` — meaning essentially all of newsroom's own INFO-level logging (source failures, "Discord: announced N...", and the new delivery summary) has been invisible in every real run, container or not, this whole time. Fixed alongside the rest since the new delivery-summary feature would have been just as silently swallowed by this same bug otherwise.
old_deployment_id:    free-game-tracker_2026-08-12_hetzner-01
new_deployment_id:    free-game-tracker_2026-08-12_hetzner-03
source_sha256:        f6b4b77c54c31da305daad076aaedb4a632a560ca581556511196f9b0a1623d1
old_image_digest:     sha256:dbae5f597fb4eea50ffd3d4d2cd4ea39958609b553aaad9c2139ac99150c407e
new_image_digest:     sha256:449d5438e2d9a7fb9fb76117dd3f6e4a63b4b568d467655489328194494e1e7e
config_revision:      no .env/compose changes; only .deployed-id's value updated
checks_performed:     local test suite (221/221, up from 211 — 10 new tests), ruff/mypy (no new issues vs baseline), local Docker build + non-root/health/version checks, local dry-run + persistence-across-recreation on a throwaway volume (confirmed the Delivery summary line and per-category breakdown appear correctly in real container stdout — this is what surfaced the logging bug in the first place), Hetzner staging validation (dry-run then non-dry-run against fgt_staging_data, Delivery summary confirmed correct with outcome=webhook_not_configured as expected for staging), production cutover run against fgt_production_data with health/status verified healthy afterward (release_channel: production, no status_reasons)
result:               success
rollback_point:       free-game-tracker_2026-08-12_hetzner-01 (image + source tarball both still present on Hetzner; .deployed-id backed up on-host as .deployed-id.bak-2026-08-12-a). The Aug-9 baseline image and its .deployed-id.bak-2026-08-09 also remain, so a two-step rollback to the original pre-incident state is still possible if ever needed.
operator_note:        Deliberately built as free-game-tracker_2026-08-12_hetzner-02 first (an earlier candidate that passed staging dry-run validation) — the logging bug was found during that candidate's *further* non-dry-run validation, so -02 was never promoted to production; -03 supersedes it with the fix included. -02's image remains on Hetzner but is not a meaningful rollback point (never deployed). Production cutover run found "0 new" everywhere (outcome=no_events, correctly distinct from webhook_not_configured) — no notification flood, and for the first time this is actually *visible* in the logs rather than inferred from silence. Same shared-host cron discipline as the previous entry: only the free-game-tracker line was touched, verified before/after.

## 2026-08-16T17:03Z
reason:              Reliability + provenance hardening pass: (1) cross-process single-instance run lock (`newsroom/run_lock.py`, fcntl.flock on a persistent-volume file) closing the gap where an overlapping cron invocation could write the database concurrently — no prior real overlap incident, but the architecture permitted one; (2) Git-based provenance (accepted SHA = OCI org.opencontainers.image.revision = runtime source_revision), replacing the hashed-snapshot model now that GitHub is genuinely in use. First deployment where `.deployed-id`'s value is a git short-SHA rather than a date-stamped snapshot identifier.
old_deployment_id:   free-game-tracker_2026-08-12_hetzner-03
new_deployment_id:   cec0346
git_sha:             cec034695d52affc284701fe93966dd7c59c5bcd
old_image_digest:    sha256:449d5438e2d9a7fb9fb76117dd3f6e4a63b4b568d467655489328194494e1e7e
new_image_digest:    sha256:5e8b016dc3854aa4f87f2209788a3de7ec345be882ec066a9700163a32f20df4
config_revision:     no .env/compose changes beyond adding docker-compose.yml's build.args.GIT_REVISION passthrough; only .deployed-id's value updated
checks_performed:    Reconciled free-game-tracker_2026-08-12_hetzner-03 (the outgoing production release) against git history first — confirmed byte-for-byte identical (all 72 application files + Dockerfile + compose + .dockerignore, modulo one file's line-ending representation) to commit 840641fe83b4 via full sha256 comparison, not assumed. Local test suite 233/233 (up from 221 baseline — 12 new tests), ruff/mypy clean on all changed files. Feature branch -> PR #1 -> squash-merged to main as cec0346. Built on Hetzner directly via git-clone-in-container (no Docker available on the usual dev machine this session) from the exact accepted SHA. Three-way provenance verified before touching production: OCI label, NEWSROOM_SOURCE_REVISION env, and `newsroom identity`'s source_revision all equal cec034695d52affc284701fe93966dd7c59c5bcd. Pre-deployment: SQLite-consistent backup via scripts/backup.py (newsroom-20260816T165718Z.db, integrity ok), production DB integrity ok, baseline counts recorded (news_events=54, steam_deals=100, source_health=9), webhook confirmed configured (value not inspected). Staging validation against fgt_staging_data (dry-run --no-notify, then a real --no-notify run) both clean, DB integrity ok. Production cutover run via the real deploy/run.sh wrapper: run lock correctly acquired/released, "0 new, 0 events" (no notification flood), DB integrity ok afterward, counts consistent (steam_deals' small change reflects that table tracking current active deals, not a cumulative log). Real cross-process lock overlap test against fgt_staging_data (a genuine `docker compose run` invocation, not a synthetic/local-only test): Run A backgrounded, Run B invoked ~0.3s later while A was genuinely still fetching sources — B was refused cleanly ("another newsroom run is already active... Skipping this invocation.", exit 0), A continued and completed normally ~60s later ("Run complete... 0 new"), staging DB integrity ok afterward. A natural (non-manual) hourly cron invocation was also observed post-deployment — see operator_note.
result:              success
rollback_point:      free-game-tracker_2026-08-12_hetzner-03 (image + git commit 840641fe83b4 both still present/retrievable; .deployed-id backed up at logs/.deployed-id.bak-2026-08-16-hardening on Hetzner, since the deploy-user's home directory itself isn't group-writable for creating new files — this ledger entry is the authoritative rollback record). All three prior images (-01, -03, and this one) remain on Hetzner, untouched/unpruned.
operator_note:       Natural (non-manual) hourly cron invocation observed at 2026-08-16T18:00:03Z, the first scheduled run of the new image: correct image (free-game-tracker:cec0346), run lock acquired/released cleanly, all collectors executed, DB integrity ok before and after, counts unchanged (news_events=54, source_health=9). Delivery behaved normally — genuinely announced 1 new Steam breakout release to real production Discord (correctly distinct from a duplicate/flood; nothing else was new). Soak clock for this hardened revision restarts at this timestamp — see RELEASE_RUNBOOK.md; the pre-hardening soak history (through hetzner-03) remains valid as historical evidence of collector/delivery correctness, just not of this session's run-lock/provenance code specifically. An unrelated hourly tick at 17:00:03Z (using the outgoing -03 image, since .deployed-id hadn't been switched yet at that exact moment) is also visible in today's log — noted here only to avoid confusing it with the first hardened-image run.
