# FreeGameFindings community-lead delivery

An FGF lead means **r/FreeGameFindings posted a structured `(Game)` or `(DLC)`
giveaway claim worth editorial attention**. It does not mean FGT verified that
the game is free. The Discord message begins “Reddit community lead — unverified
giveaway claim”, links to the Reddit submission, and asks an editor to verify
before publishing. Outbound store links remain evidence relationships; they do
not replace the Reddit permalink.

Reddit observations stay outside `NewsEvent`, the expiring offer snapshot,
`RunDiff`, and `notify_new_giveaways`. GamingLeaks INTEL has no delivery
authority from this feature.

## Authority and eligibility

`NEWSROOM_ENABLE_REDDIT_FGF_DELIVERY` defaults to `false` and is passed through
Docker Compose with a `false` default. Discovery collection has its own flag.
The delivery flag controls both creation and draining of FGF intents. Turning it
off stops delivery while preserving observations and outbox rows.

An intent is created only in the same transaction that first inserts an
observation when all of these hold:

- source is `reddit_free_game_findings`;
- this is not the source's baseline run;
- classification is `giveaway_claim_unverified` under
  `fgt-reddit-discovery-v2`;
- delivery authority is enabled and collection persists.

The observation key is the outbox primary key. Resightings, feed reorder, title
edits, and raw evidence revisions cannot create a second intent. Turning the
flag on does not scan or enqueue any existing observation, including the v1
baseline and v2 qualification rows. This is **prospective-only** activation.

## Durable states and retries

`discovery_delivery_outbox` retains one row per authorised lead. It snapshots
the compact Discord payload and stores source, external ID, observation key,
classification, policy, first-seen time, permalink, code revision, and first
raw-evidence hash. The original XML remains only on the observation.

- `pending`: authorised, never successfully delivered. A missing webhook and
  `--no-notify` leave it pending without a send attempt.
- `failed`: Discord did not confirm acceptance. Attempts and time are recorded;
  the row is retried on a later normal run.
- `delivered`: Discord accepted the POST; later drains skip the row.
- `held`: the saved payload failed validation. It is not retried automatically;
  an operator must inspect it.

At most ten pending or failed intents are attempted per normal run, once each.
The existing Discord transport supplies bounded 429 handling. Reddit intake
has no new retry. An interrupted attempt retains a durable row and records an
unknown outcome until the next attempt. **Discord webhooks do not give this
outbox an atomic transaction with SQLite**: a crash after Discord accepts a
POST but before the delivered commit can cause a duplicate on retry. The
normal success/restart path suppresses duplicates; an absolute exactly-once
network guarantee would require receiver-side idempotency.

Run summaries log `reddit_leads_detected` (new FGF observations),
`reddit_leads_eligible` (new intents), `reddit_leads_pending`,
`reddit_leads_posted`, `reddit_leads_failed`, and `reddit_leads_held` separately
from game-promotion and subscription delivery. Discord failure does not stop
ordinary FGT collection. `--no-notify` keeps authorised intents but does not
drain them.

## Operator inspection

Use read-only SQLite access to the selected environment's database. For
example, after identifying the correct path:

```sql
PRAGMA query_only=ON;
SELECT status, count(*) FROM discovery_delivery_outbox GROUP BY status;
SELECT observation_key, source, external_id, status, attempts,
       created_at, last_attempt_at, delivered_at, last_error
FROM discovery_delivery_outbox ORDER BY created_at DESC LIMIT 30;
```

Inspect run logs for `Reddit community leads:`. Do not treat a successful
Reddit fetch as proof of Discord delivery; inspect the outbox status and
delivery accounting. Do not manually edit rows to manufacture a send.

## Future production activation — procedure only

1. Review and merge the PR, then identify the accepted merge SHA.
2. Take a SQLite-safe `sqlite3.Connection.backup()` of the production DB;
   verify backup SHA-256 and `PRAGMA integrity_check` on both files.
3. Upgrade the additive `e103_fgf_delivery` migration and deploy an image
   built from the accepted SHA, keeping delivery authority **false**.
4. Verify the deployed SHA, OCI revision, effective flags, schema, integrity,
   and that historical observations created **zero** outbox intents.
5. Obtain explicit human approval, then enable only
   `NEWSROOM_ENABLE_REDDIT_FGF_DELIVERY`.
6. Let a future natural new eligible submission create the first intent.
   Inspect its wording, outbox outcome, and ordinary pipeline health; continue
   a bounded soak. Do not replay or alter historical observations.

This mission does **not** perform those production steps or send a real Discord
message.

## Rollback

Disable `NEWSROOM_ENABLE_REDDIT_FGF_DELIVERY` first. This stops new intents and
draining without deleting discovery or outbox evidence. Revert the image only
through the normal reviewed release procedure if needed. Retain observations,
outbox rows, baseline, and `first_seen`. The migration refuses a destructive
downgrade; restore a verified backup if a schema rollback is truly required.
