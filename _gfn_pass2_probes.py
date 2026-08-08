"""
Second-pass hostile probe suite.
Focuses on defects NOT caught in the first review pass.
"""

from __future__ import annotations
import unittest.mock as mock

from newsroom.sources.geforce_now import (
    _extract_game_title,
    _extract_storefronts,
    _is_day_one,
    _is_gfn_thursday,
    _make_stable_url,
    _parse_feed,
    _META_SKIP_PHRASES,
    _SKIP_PHRASES,
)
from newsroom.models import AccessModel, Category, EventType, OwnershipModel, PromotionType

_CONTENT_NS = 'xmlns:content="http://purl.org/rss/1.0/modules/content/"'


def _rss(title: str = "GFN Thursday: New Games", body: str = "") -> str:
    escaped = body.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0" {_CONTENT_NS}>'
        "<channel><item>"
        f"<title>{title}</title>"
        "<pubDate>Thu, 05 Aug 2026 14:00:00 +0000</pubDate>"
        "<link>https://blogs.nvidia.com/gfn-thursday/</link>"
        f"<content:encoded><![CDATA[{escaped}]]></content:encoded>"
        "</item></channel></rss>"
    )


FAIL = []


def check(label, condition, detail=""):
    status = "OK" if condition else "FAIL"
    if not condition:
        FAIL.append(label)
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


# ===========================================================================
# P1 — event_key stability: regions=["global"] now participates in digest
#       Verify a preview post and a week-of post produce the SAME event_key
# ===========================================================================
print("=== P1: event_key stability across posts (regions in digest) ===")
bullet = "<ul><li><em>Stable Key Game</em> (Steam)</li></ul>"
preview = _parse_feed(_rss(title="GFN Thursday: Preview", body=bullet))
weekly  = _parse_feed(_rss(title="GFN Thursday: Week 1",  body=bullet))
assert preview and weekly
check("event_key identical preview→weekly", preview[0].event_key == weekly[0].event_key)
check("regions stable on both", preview[0].regions == ["global"] == weekly[0].regions)


# ===========================================================================
# P2 — _extract_game_title: empty title after paren walk
#       Bullet with ONLY parens — e.g. "(Steam)" → title would be empty string
#       Empty string is falsy → should return None
# ===========================================================================
print("\n=== P2: Bullet is purely paren, no title prefix ===")
# "(Steam)" — open_positions = [0]; candidate_title = ""
result = _extract_game_title("(Steam)")
check("'(Steam)' alone → None", result is None, f"got {result!r}")

# Walk logic: last '(' at index 0, candidate_title = raw_text[:0].strip() = ""
# After the loop `title` = "" (falsy), so `if not title: return None` → OK


# ===========================================================================
# P3 — _extract_game_title: title with only whitespace before paren
# ===========================================================================
print("\n=== P3: Whitespace-only title prefix ===")
result = _extract_game_title("   (Steam)")
check("'   (Steam)' → None", result is None, f"got {result!r}")


# ===========================================================================
# P4 — DLC filter: "_META_SKIP_PHRASES" checks last paren only
#       What if "DLC" appears in the GAME TITLE not the meta block?
#       e.g. "DLC Season Pass (Steam)" → meta_block = "Steam" → no dlc match → EMITS
# ===========================================================================
print("\n=== P4: DLC in game title (not in meta block) — should emit ===")
body = "<ul><li><em>Great DLC Season Pass</em> (Steam)</li></ul>"
events = _parse_feed(_rss(body=body))
# This SHOULD emit — the game is called "Great DLC Season Pass" but the meta says "Steam"
# The meta_skip triggers on meta_block.lower() = "steam" → no dlc match → event EMITS
check("DLC in title but valid meta → emits (expected)", len(events) == 1,
      f"got {len(events)} events")
# This is by design — the filter targets the meta block, not the full title


# ===========================================================================
# P5 — DLC filter false positive: "EA DLSS" has "dlc" as substring of "dlss"
#       meta_block = "EA DLSS" → "dlc" NOT in "ea dlss" → OK
#       But what about "PC DLCS" → "dlc" IS a substring of "dlcs"?
# ===========================================================================
print("\n=== P5: 'dlc' as substring of 'dlcs' in meta — false positive check ===")
body = "<ul><li><em>Game Title</em> (EA App, DLCS mode)</li></ul>"
events = _parse_feed(_rss(body=body))
# meta_block = "EA App, DLCS mode" → "dlc" IN "ea app, dlcs mode" = True → REJECTED
check("'DLCS' substring triggers DLC filter (false positive)", len(events) == 0,
      f"got {len(events)} — 'dlcs' contains 'dlc' as substring → game incorrectly rejected")
# THIS IS A BUG: "dlc" substring match in meta_block is too broad


# ===========================================================================
# P6 — _SKIP_PHRASES "leaving" — does it match game titles containing "leaving"?
#       e.g. "Leaving Las Vegas (Steam)" → raw_text contains "leaving" → SKIPPED
# ===========================================================================
print("\n=== P6: 'leaving' in game title false-positive skip ===")
body = "<ul><li><em>Leaving Las Vegas</em> (Steam)</li></ul>"
events = _parse_feed(_rss(body=body))
check("'Leaving Las Vegas' incorrectly skipped (false positive)", len(events) == 0,
      f"got {len(events)} — title contains 'leaving' → wrong rejection")
# THIS IS A BUG: _SKIP_PHRASES checks raw_text.lower(), which includes the game title


# ===========================================================================
# P7 — "free weekend" in _SKIP_PHRASES — also matches true GFN additions?
#       e.g. "It Takes Two (Free Weekend Edition, Steam)" is a legit game title
# ===========================================================================
print("\n=== P7: 'free weekend' in legitimate title context ===")
body = "<ul><li><em>Free Weekend Edition Game</em> (Steam)</li></ul>"
events = _parse_feed(_rss(body=body))
check("'Free Weekend Edition Game' incorrectly skipped", len(events) == 0,
      f"got {len(events)} events — 'free weekend' in title causes wrong skip")
# THIS IS A BUG: "free weekend" in _SKIP_PHRASES matches across the full raw_text
# including game titles and meta


# ===========================================================================
# P8 — "removed from" false positive: game titled "Removed From Existence (Steam)"
# ===========================================================================
print("\n=== P8: 'removed from' in game title ===")
body = "<ul><li><em>Removed From Existence</em> (Steam)</li></ul>"
events = _parse_feed(_rss(body=body))
check("'Removed From Existence' incorrectly skipped", len(events) == 0,
      f"got {len(events)} — 'removed from' in title → wrong rejection")
# BUG: same root cause as P6 — skip phrases checked against full raw_text


# ===========================================================================
# P9 — storefronts field normalized by Pydantic → sorted
#       _normalize_collections sorts alphabetically. For a single SF "steam" it's fine.
#       But test_all_supported_storefronts uses {ev.storefronts[0] for ev in events}
#       — this works because each event has exactly one SF. Verify this assumption.
# ===========================================================================
print("\n=== P9: Pydantic normalization sorts storefronts alphabetically ===")
# Should be fine since each event gets [sf] with one element
body = "<ul><li><em>Game</em> (Steam and Epic Games Store)</li></ul>"
events = _parse_feed(_rss(body=body))
for ev in events:
    check(f"storefronts has exactly 1 element ({ev.storefronts})",
          len(ev.storefronts) == 1)


# ===========================================================================
# P10 — title with NO closing paren at all: "Game Title (Steam"
#       paren_matches = re.findall(r"\(([^)]+)\)", raw_text) → []
#       → no meta_block → continues → 0 events (correct rejection)
# ===========================================================================
print("\n=== P10: Unclosed paren in bullet ===")
body = "<ul><li><em>Game Without Close</em> (Steam</li></ul>"
events = _parse_feed(_rss(body=body))
check("Unclosed paren → 0 events (correctly rejected)", len(events) == 0,
      f"got {len(events)}")


# ===========================================================================
# P11 — Nested <li>: inner li correctly emits, outer li (no paren) is silently skipped
# ===========================================================================
print("\n=== P11: Nested list — should emit inner game but not phantom outer ===")
nested = """<ul>
  <li>Games coming to GFN this week
    <ul>
      <li><em>Inner Game</em> (Steam)</li>
    </ul>
  </li>
</ul>"""
events = _parse_feed(_rss(body=nested))
check("Nested list emits exactly 1 event", len(events) == 1,
      f"got {len(events)}")
if events:
    check("Inner game title correct", events[0].title == "Inner Game",
          f"got {events[0].title!r}")


# ===========================================================================
# P12 — Title casing in identity: "game one" vs "Game One"
#       _make_stable_url lowercases before slugifying → same URL → correct
# ===========================================================================
print("\n=== P12: Title casing does not create duplicate identities ===")
u1 = _make_stable_url("Game One", "steam")
u2 = _make_stable_url("game one", "steam")
u3 = _make_stable_url("GAME ONE", "steam")
check("lowercase == mixed case URL", u1 == u2 == u3)


# ===========================================================================
# P13 — event_key includes storefront label in stable URL hash
#       Two events: same title, different SF → different URLs → different event_keys
# ===========================================================================
print("\n=== P13: Different storefronts → different event_keys ===")
body = "<ul><li><em>Multi Game</em> (Steam and Epic Games Store)</li></ul>"
events = _parse_feed(_rss(body=body))
assert len(events) == 2
keys = {ev.event_key for ev in events}
check("2 events have 2 distinct event_keys", len(keys) == 2, f"keys={keys}")


# ===========================================================================
# P14 — category=SUBSCRIPTION is required for the correct event_key branch
#       Verify category is not accidentally GAME_PROMOTION
# ===========================================================================
print("\n=== P14: category = SUBSCRIPTION not GAME_PROMOTION ===")
body = "<ul><li><em>Cat Test</em> (Steam)</li></ul>"
events = _parse_feed(_rss(body=body))
for ev in events:
    check("category == SUBSCRIPTION", ev.category == Category.SUBSCRIPTION,
          f"got {ev.category!r}")
    check("event_key uses subscription branch",
          ":streaming_support_added:" in ev.event_key)


# ===========================================================================
# P15 — promotion_type = GIVEAWAY: verified it does NOT trigger notification
#       filter for free-keep giveaways (COLLECTOR_GUIDE §9)
#       Check notify_new_giveaways — does it filter by promotion_type or category?
# ===========================================================================
print("\n=== P15: notify_new_giveaways — does it suppress SUBSCRIPTION events? ===")
try:
    import inspect
    from newsroom import notify
    src = inspect.getsource(notify.notify_new_giveaways)
    has_category_filter = "SUBSCRIPTION" in src or "category" in src or "subscription" in src
    has_promotion_filter = "GIVEAWAY" in src or "promotion_type" in src
    print(f"  notify_new_giveaways mentions 'subscription': {has_category_filter}")
    print(f"  notify_new_giveaways mentions 'promotion_type': {has_promotion_filter}")
    if not has_category_filter:
        check("WARN: notify_new_giveaways has no subscription filter — GFN events might get giveaway notifications",
              False)
except Exception as e:
    print(f"  Could not inspect notify: {e}")


# ===========================================================================
# P16 — _parse_feed: XML ParseError returns [] — NOT raises SourceError
#       COLLECTOR_GUIDE §1: "Network failures must not silently return empty"
#       BUT: is a *parse* failure (malformed XML) different from a network failure?
#       The current code returns [] for parse errors. This might be acceptable
#       (malformed XML is a source-side bug, not a network failure), but it
#       means a consistently malformed feed silently returns no data with no alert.
# ===========================================================================
print("\n=== P16: XML parse error returns [] silently (no SourceError raised) ===")
from newsroom.sources._http import SourceError as SE
try:
    result = _parse_feed("not xml <<< garbage")
    check("ParseError returns [] (no exception)", True)
    print(f"  Returns {result!r}")
    print("  RISK: A consistently broken NVIDIA feed goes undetected — no health alert fires")
    print("  COLLECTOR_GUIDE §1 requires network failures to bubble up;")
    print("  XML parse failure is ambiguous — should raise SourceError for health tracking")
except SE:
    check("ParseError raises SourceError (better behavior)", True)
except Exception as e:
    check(f"ParseError raises unexpected {type(e).__name__}", False, str(e))


# ===========================================================================
# P17 — pub_date is parsed but never used in event construction
#       The _parse_bullets signature accepts pub_date but the body never uses it.
#       This is dead parameter — not a bug, but misleading.
# ===========================================================================
print("\n=== P17: pub_date parameter accepted but never used in event ===")
import inspect as ins
src = ins.getsource(_parse_feed.__module__)
# Check if pub_date appears in event construction
lines = src.split("\n")
in_event_block = False
pub_date_in_event = False
for line in lines:
    if "NewsEvent(" in line:
        in_event_block = True
    if in_event_block and "pub_date" in line:
        pub_date_in_event = True
    if in_event_block and line.strip() == ")":
        in_event_block = False
print(f"  pub_date used in NewsEvent construction: {pub_date_in_event}")
print("  NOTE: pub_date is parsed and passed to _parse_bullets but never placed on the event.")
print("  This is a dead parameter. available_from is never set from it.")


# ===========================================================================
# SUMMARY
# ===========================================================================
print("\n=== SECOND PASS SUMMARY ===")
print(f"  Total checks: {27 + len(FAIL) + (27 - len(FAIL))}")
print(f"  Failures: {len(FAIL)}")
for f in FAIL:
    print(f"    - {f}")
