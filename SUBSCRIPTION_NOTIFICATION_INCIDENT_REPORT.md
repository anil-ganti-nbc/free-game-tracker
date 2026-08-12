# Incident Report: Subscription Events Never Reached Discord

**Trigger:** Sony published *"Helldivers 2 joins PlayStation Plus Game Catalog
today, Devoid of Liberty update out now"* on 2026-08-12. The tracker did not
alert on it.

**Actual scope of the bug:** not one missed article. Every PlayStation Plus,
Xbox Game Pass, and GeForce Now event this tracker has ever detected — from
day one — has been silently withheld from Discord. The Helldivers 2 article
is simply the first time someone noticed.

**Status:** Fixed, tested, deployed to production (Hetzner,
`free-game-tracker_2026-08-12_hetzner-01`). This document is the postmortem.

---

## 1. What actually happened

### 1.1 The bug

[`newsroom/notify.py`](newsroom/notify.py)'s `build_discord_payload()` — the
only function that ever built a Discord message — filtered its input to:

```python
eligible = [
    e for e in events
    if e.confidence.score >= min_confidence and e.category == Category.GAME_PROMOTION
]
```

Every subscription source tags its events `Category.SUBSCRIPTION`:

```
newsroom/sources/playstation_plus.py:262:  category=Category.SUBSCRIPTION,
newsroom/sources/xbox_game_pass.py:246:    category=Category.SUBSCRIPTION,
newsroom/sources/geforce_now.py:282:       category=Category.SUBSCRIPTION,
```

No other function ever built a subscription-shaped Discord message. There was
no bug in *detection* — there was no delivery mechanism for this category at
all. It's not a bounds error, a race condition, or a flaky parse. It's a
missing feature that looked, from every angle except "did a message arrive,"
like a working one: the collector ran on schedule, logged success, stored
data, and the dashboard displayed it correctly. Discord was the only place
the gap was visible, and nobody was watching for an absence.

### 1.2 Why it was there on purpose

This wasn't an oversight in isolation — it was a deliberate, if incomplete,
fix for a real problem. `build_discord_payload()`'s embed hard-codes
ownership language:

```python
price = f"${event.original_price:.2f} → Free" if event.original_price else "Free"
...
content = f"{total} new free game{'s' if total != 1 else ''} detected."
```

A subscription-catalog addition is not "$X → Free" — the game didn't become
free, a subscription tier grants temporary access to it. Posting Helldivers 2
through this exact function, unmodified, would have told the journalist a
$40 game literally became a permanent giveaway, which is false and exactly
the kind of inaccuracy a newsroom tool cannot afford. A prior contributor
recognized this and added the category filter specifically to stop that
false claim from reaching Discord — documented explicitly in
[`docs/PLAYSTATION_PLUS_COLLECTOR.md`](docs/PLAYSTATION_PLUS_COLLECTOR.md):

> **Notifications**: Category identically bypassed suppressing misleading
> "Free Giveaway" messages to Discord globally via `Category.GAME_PROMOTION`
> boundary checks.

The fix for "this embed lies about subscription events" was "don't send
subscription events," not "build a subscription-accurate embed." The former
is a one-line, obviously-correct-looking change. The latter is the one that
was actually owed and never landed.

### 1.3 Why nobody caught it sooner

- **It doesn't fail.** No exception, no log line at ERROR/WARNING level, no
  non-zero exit code. `build_discord_payload()` returns `None` for an
  all-subscription-event batch and the caller just... doesn't post. That's
  indistinguishable from "nothing new happened this run."
- **Every other signal says healthy.** `newsroom status` showed
  `playstation_plus: ok, 35 games`. The dashboard showed all 35. Reports
  written to disk included them. Every layer *except Discord delivery*
  worked, and Discord delivery is the one layer with no built-in
  confirmation ("did this post?") surfaced back to an operator.
- **It's a silent, permanent zero, not an intermittent failure.** A flaky
  bug gets noticed because behavior changes. A consistent zero from day one
  just becomes "how the tool has always behaved" — there's no before/after
  contrast to notice.
- **The taxonomy work was actually good, which made this easier to miss.**
  `NewsEvent` already correctly models `Category.SUBSCRIPTION`,
  `EventType.CATALOG_ADDITION` / `CLAIMABLE_GAME`, `AccessModel`,
  `OwnershipModel` — the access-vs-ownership distinction this incident
  report's brief specifically worried about was *already solved correctly*
  at the data model layer, and `quality.py`'s gate already exempts
  subscription events from the price filter on purpose. Everything
  downstream of detection looked deliberately, carefully built for exactly
  this case — because it was. The one missing piece was Discord delivery
  itself, which is easy to overlook precisely because everything around it
  is solid.

### 1.4 What did *not* cause it (ruled out with evidence, not assumed)

The incident brief's working theory was that discovery or classification
failed on this specific article. I traced the actual event through the live
system before touching code and that theory didn't hold:

- Fetching `newsroom.sources.playstation_plus.fetch_events()` **unmodified**
  against the real PlayStation Blog produced a correct
  `catalog_addition` / `subscription_catalog` event for Helldivers 2 — title,
  tiers `[extra, premium]`, `available_from=2026-08-12`, confidence 95 — via
  the ordinary monthly-roundup parser, because the August roundup article
  legitimately lists Helldivers 2 as one of its `Title | Platform` entries.
- The database had zero rows mentioning Helldivers 2 anywhere, in any table,
  before this investigation — confirming the event had never been *stored*,
  which was consistent with a separate, real, but non-causal fact: the local
  Windows pipeline hadn't run since 2026-08-09 (three days before the
  article existed). Hetzner's hourly cron, however, had been running the
  whole time on the *old* code — and its production database already had
  Helldivers 2 stored by the time I checked, proving discovery/classification
  worked fine in production too. It just never got announced.

I did find a second, real gap while investigating — the PS Blog collector
only ever polled `category/ps-plus/feed/`, which contains monthly roundups
only; a standalone same-day article about one game (the actual Helldivers 2
"Devoid of Liberty" post, distinct from the roundup) is never an item in that
feed, only a link inside the roundup's body. That's a legitimate discovery
gap for *future* incidents where no roundup happens to also cover the game —
and it's fixed in this same release — but it is not what caused this
specific miss, since the roundup alone was sufficient. Both are documented
below; they should not be conflated.

---

## 2. Blast radius

Every subscription-category detection this tracker has ever made was
affected, for as long as the source has existed:

| Source | Category tag | Discord path before this fix |
|---|---|---|
| PlayStation Plus | `SUBSCRIPTION` | None — always dropped |
| Xbox Game Pass | `SUBSCRIPTION` | None — always dropped |
| GeForce Now | `SUBSCRIPTION` | None — always dropped |

At the time of this fix, the local database held 35 previously-detected
PlayStation Plus events (monthly claims and catalog additions going back to
April 2026) that were stored, healthy-looking, and never once posted to
Discord. Xbox Game Pass and GeForce Now had zero currently-live events at
verification time, so the fix's effect on those two sources is confirmed by
code inspection and unit tests (they populate the exact same model fields
PlayStation Plus does, so the same generic notify path handles them) rather
than a live example — **the next real Xbox Game Pass or GeForce Now
detection should be checked manually to confirm it actually posts.** That's
the one piece of this fix that live traffic, not a test suite, has to prove.

Ordinary storefront giveaways (Epic, Steam, GOG, GamerPower —
`Category.GAME_PROMOTION`) were never affected; `build_discord_payload()`
worked correctly for them the entire time. This was a subscription-category
blind spot, not a general notification failure.

---

## 3. The fix

1. **[`newsroom/notify.py`](newsroom/notify.py)** — added
   `build_subscription_payload()` / `notify_new_subscription_events()`,
   mirroring the existing breakout/deal notifier pattern already in this
   file. The embed states Service / Event / Tier / Availability / Access
   type, explicitly labeled `"Subscription access (not ownership)"`, and
   never uses price or "free" language. `build_discord_payload()` is
   unchanged and now documented as intentionally giveaway-only.
2. **[`newsroom/cli.py`](newsroom/cli.py)** — wired the new notifier into
   `run_pipeline()` alongside the existing giveaway one.
3. **[`newsroom/sources/playstation_plus.py`](newsroom/sources/playstation_plus.py)**
   — hardening for the secondary gap: now polls the general PlayStation Blog
   feed in addition to the `ps-plus` category feed (fault-isolated per feed —
   one failing doesn't lose the other); added content-based detection
   (`_detect_standalone_access_event`) for standalone articles whose
   headline doesn't contain roundup keywords, so a future "X joins PS Plus"
   article that isn't also covered by a same-day roundup is still caught;
   added cross-article dedup so a standalone article and a roundup covering
   the same game/date collapse to one event instead of double-posting.

Full detail, root-cause tracing, and the original scope discussion are in
this session's investigation notes; the summary above is what shipped.

---

## 4. Verification performed

- Regression tests added in `test_notify.py` and `test_playstation_plus.py`
  — synthetic fixtures (different game, date, URL than the real incident, so
  the coverage protects the *class* of bug, not one hardcoded title) —
  confirmed to fail-to-collect against the pre-fix code (`ImportError`, since
  the functions they exercise didn't exist yet), then pass after the fix.
- Full test suite: 211/211 passing. Ruff/mypy: no new issues versus
  baseline (mypy errors actually dropped, 14 → 9, as a side effect of a
  cleaner refactor).
- Live end-to-end dry run against the real PlayStation Blog: Helldivers 2
  fetched, classified, passed the quality gate, and
  `build_subscription_payload()` produced the exact embed shape expected —
  without posting to the real webhook.
- Full deployment runbook followed for Hetzner: local Docker build, local
  validation (non-root, health, dry-run, persistence-across-recreation),
  staging validation (dry-run then non-dry-run against an isolated volume),
  production cutover with `.deployed-id` updated, verified `health`/`status`
  healthy afterward, cron re-enabled. Recorded in
  [`ai/handoff/DEPLOYMENT_LEDGER.md`](ai/handoff/DEPLOYMENT_LEDGER.md).
- Confirmed the cutover run itself did not flood Discord: `compare()` diffs
  against already-stored state, so previously-detected events (including
  Helldivers 2, already in production's DB from the old code's working
  discovery) do not retroactively re-announce. The fix takes effect for
  genuinely new events going forward, not as a backlog dump.

---

## 5. What must change to prevent this class of miss

The specific bug is fixed. The conditions that let it survive silently for
the source's entire lifetime are still present and will produce the same
shape of failure again for a different category, function, or filter unless
something structural changes. In priority order:

### 5.1 A coverage test that fails when a category has no notify path

Nothing in the test suite asserted "every `Category` value used by a source
has a corresponding Discord notifier." Add one. Something like:

```python
def test_every_source_category_has_a_notify_path():
    used_categories = {Category.GAME_PROMOTION, Category.SUBSCRIPTION}  # from source inspection
    handled_categories = {Category.GAME_PROMOTION, Category.SUBSCRIPTION}  # from notify.py's filters
    assert used_categories <= handled_categories
```

This is the single highest-leverage change: it converts "a new category
silently has nowhere to go" from an invisible gap into a failing test the
moment someone adds a fourth category (e.g. a future Prime Gaming or Apple
Arcade source) without also adding its delivery path.

### 5.2 Delivery confirmation, not just detection confirmation

`newsroom status` currently reports whether each *source* fetched
successfully. It says nothing about whether what was detected was ever
*delivered*. Add a lightweight, per-run summary — even just a log line —
of the form: `N events detected, M eligible for Discord, K actually posted`.
If M and K ever diverge from what an operator expects (e.g. M > 0 but the
webhook is unset, or a category silently contributes 0 to M despite
contributing to N), that's visible without reverse-engineering the code.
This does not need to be a telemetry framework — a `logger.info` line in
`run_pipeline()` after the notify calls is enough to make a future version
of this exact incident greppable in `logs/` instead of invisible.

### 5.3 Treat "silently returns None/False" as a smell in notify.py specifically

Every notify function in this file returns `False`/`None` on both "nothing
to do" (correct, expected) and "something's misconfigured" (webhook unset,
category mismatch) — the same return value means two very different things.
Not proposing an exception-based rewrite (that would make routine
zero-result runs noisy), but any *new* filter added to a notify function
going forward should come with an explicit code-review question: "if this
condition is false, is that because there's nothing to report, or because
this function structurally can't handle something it's being given?" This
incident was the second case wearing the first case's return value.

### 5.4 Xbox Game Pass / GeForce Now need a live-fire confirmation

As noted in §2, these two sources' fix is proven by code/test inspection,
not by an observed real post. The next genuine detection from either source
should be checked against Discord directly, once, to close that loop. This
isn't a code change — it's a follow-up action item.

### 5.5 Local Windows scheduling gap (operational, not code)

The local Windows instance's task-scheduler automation (built earlier in
this project's life) was never actually registered — `Get-ScheduledTask`
found nothing, and the local pipeline hadn't run in three days at the time
of this investigation. Hetzner's cron covered production the entire time, so
this wasn't causal here, but it means the local Windows install is not a
reliable redundant check on production behavior right now. If it's meant to
be more than a dev checkout, either install the scheduled task
(`Install-HourlyTask.ps1` already exists in the repo root) or explicitly
decide it's Hetzner-only from here and stop treating local staleness as
meaningful signal.

### 5.6 Documentation debt this incident exposed

`docs/PLAYSTATION_PLUS_COLLECTOR.md`'s "Limitations" section documents the
old suppression as a permanent design decision ("Category identically
bypassed... globally"), not as a known gap with an owed follow-up. Docs that
describe a missing feature as a completed decision make the gap harder to
notice on a documentation read-through, not easier. This file should be
updated to reflect the new subscription notify path — flagged here as owed,
not yet done in this pass since it's documentation-only and not part of the
approved code-fix scope.

---

## 6. One-line summary for anyone who only reads one line

The tool never lied about what it found — it just never told anyone about
an entire category of what it found, and nothing was watching for that
particular kind of silence. The fix adds the missing delivery path; the
prevention work in §5 is about making sure a *future* missing delivery path
can't hide for months the same way this one did.
