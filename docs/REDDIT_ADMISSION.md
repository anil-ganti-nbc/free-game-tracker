# Reddit discovery admission — review handoff

This change admits retrieval and durable discovery evidence, with collection
opt-in and editorial delivery structurally blocked. It does not claim live soak,
production promotion, verified Reddit access, or authoritative source resolution.

## Scope and ownership

- OEM Radar: r/GamingLaptops and r/MiniPCs through native evidence_items,
  evidence_events, crawler_runs, run locking, and its existing fetcher.
  Community provenance is explicit; no product model, NEW_PRODUCT, or outbox entry.
- Free Game Tracker: r/FreeGameFindings only. Its source registry/manual GUI
  dispatch and SQLite transaction/lock machinery own collection. Discovery is
  separate from offers. The preserved r/GamingLeaksAndRumours archaeology is
  explicitly outside this tranche and this repository's domain ownership.
- Semiconductor Intelligence PR #5 is already merged; this tranche does not
  register, schedule, or expand that separate r/hardware pilot.

## Why a discovery table is necessary in Free Game Tracker

At base 011b89f, NewsEvent requires promotion terms, sync_events deletes absent
items, and notify.py sends from transient RunDiff. None can represent an
unverified leak with durable history. The additive discovery_observations and
invocation/outcome discovery_runs tables reuse the same database, session scope,
Alembic runner and newsroom.lock. They are domain discovery records, not a
second Reddit delivery/baseline service. Existing giveaway semantics stay intact.
There is no durable outbox in this repository; delivery cannot be admitted by
merely unmuting or toggling collection. Building a new notifier was out of scope.

## Shared primitive

clank_reddit is an importable, dependency-free Atom transport package. The
canonical copy is oem-radar/src/clank_reddit; FGT vendors identical bytes, pinned
by docs/REDDIT_TRANSPORT.json with a SHA-256 test in each repository. This follows
existing fleet code-reuse practice without a new repo, runtime or installation
service. Change the canonical copy first, synchronize consumers, update both
manifests, and rerun tests. Semantic policy never belongs in this package.

One bounded /new/.rss page is fetched per intake. HTTP failures, malformed feeds,
unexpected identity/scope, and empty Reddit listings fail closed. No short-circuit
cursor assumes feed ordering. Reordered/pinned posts are reconciled against
persistent observation IDs. Retrieval does not fetch arbitrary outbound links.
The HTTP transport remains consumer-owned; actual access requires a manual probe.

## State, novelty and duplicates

- First successful intake establishes the source baseline. Failure cannot admit
  a source. Baseline status stays attached to a record across edits and restarts.
- Every submission keeps its own identity. Repeated IDs do not replay; two posts
  linking the same article remain two pieces of evidence. Related URL keys remove
  only known tracking parameters and expose possible relationships, never assert
  that VideoCardz and another publisher are independent original sources.
- FGT exposes related observation IDs in its current view. These are hints, not
  cross-Clank merges or semantic duplicate decisions. No Reddit alerts are sent,
  so repeated aggregator links cannot multiply notifications during admission.
- Reddit timestamps date the submission. Linked-article publication and original
  source remain unknown unless present in evidence. Raw entry representations,
  outbound URLs, authors, run IDs and revision context are retained.
- FGT classification v1 distinguishes unverified giveaway claims from
  unclassified/non-game posts. Claims remain unverified. Keyword classification
  is deliberately conservative and needs real soak/editorial review before any
  delivery or broader claim of coverage.
- FGT's default discovery query excludes baseline and unclassified records.
  Explicit history inspection includes them without calling them novel.
- OEM evidence remains outside the product novelty stream at all times.

## Manual validation and rollback

Defaults are disabled: OEM radar.yaml reddit_discovery_enabled=false;
FGT NEWSROOM_ENABLE_REDDIT_DISCOVERY=false. To test after review, use an isolated
lane/database and the existing manual GUI collection controls, with collection
opted in. OEM uses reddit_min_interval_s (default 1800) and native source_due.
FGT shows the FreeGameFindings discovery source in its existing source registry. Opening the
GUI/evidence view does not fetch Reddit. No scheduler was created or enabled.

Before any existing database upgrade, take a SQLite Connection.backup() snapshot
and verify PRAGMA integrity_check. The FGT migration is additive. Disable intake
and revert code for rollback while retaining discovery tables/evidence; its
schema downgrade deliberately refuses to delete evidence. Never reset a baseline
or remove runtime state to make a rollback work. This task used temporary test
DBs only; existing local and remote runtime DBs were not migrated.

Live soak, operator evidence review, and a durable/authorized delivery path are
still required before notification admission. Neither config flag grants it.
Do not deploy to Hetzner from this local work.

Coverage limit: the bounded 100-entry listing is not a historical backfill.
A long source gap can exceed its horizon; missing coverage must not be inferred
as no activity. Recovery/backfill and higher recall require a separate measured
admission increment. The existing r/hardware pilot is not expanded here.

## Validation performed locally

The split branch was revalidated after removing the out-of-domain
r/GamingLeaksAndRumours source; exact results are recorded in the PR checks.
Tests used Python 3.14 and temporary databases. GitHub CI targets Python 3.12.
Both built wheels contain byte-identical clank_reddit code. No live Reddit
collection, production database migration, deployment, or notification occurred.
