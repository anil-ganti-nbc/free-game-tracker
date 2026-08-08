# Stage 5 Implementation Report — GeForce NOW Collector

**Date:** 2026-08-05  
**Status:** ✅ Complete

---

## Files changed

| Path | Action |
|---|---|
| `newsroom/models.py` | Added `GEFORCE_NOW = "geforce_now"` to `Source` enum |
| `newsroom/sources/geforce_now.py` | New — full collector implementation |
| `newsroom/tests/test_geforce_now.py` | New — full test suite (16 tests) |

---

## Implementation summary

### Discovery

- Polls `https://blogs.nvidia.com/feed/` (official NVIDIA Blog RSS).
- Filters items whose `<title>` contains `"gfn thursday"` or `"geforce now thursday"` (case-insensitive).
- Gracefully handles missing or empty posts; logs and skips bad items.

### Parsing strategy

- Uses `xml.etree.ElementTree` for RSS, `BeautifulSoup` for inner HTML.
- Iterates `<li>` bullet items inside article body.
- Extracts the **last parenthetical block** `(...)` of each bullet as the metadata field containing storefront + date hints.
- **Storefront is mandatory.** Bullets without a recognised storefront are silently rejected.

### Storefront detection

Seven supported stores, matched with compiled regex patterns (longest-match priority to avoid partial shadowing):

| Raw text | Canonical label |
|---|---|
| `Epic Games Store`, `Epic Games`, `Epic` | `epic` |
| `Ubisoft Connect`, `Ubisoft` | `ubisoft connect` |
| `PC Game Pass`, `Xbox` | `xbox` |
| `Battle.net` | `battle.net` |
| `GOG.com`, `GOG` | `gog` |
| `EA App`, `EA Games` | `ea` |
| `Steam` | `steam` |

### Ownership & access model

```
access_model    = STREAMING_SUPPORT
ownership_model = REQUIRES_EXTERNAL_OWNERSHIP
promotion_type  = GIVEAWAY   (required by NewsEvent validator)
event_type      = STREAMING_SUPPORT_ADDED
category        = SUBSCRIPTION
```

### Identity & deduplication

- Each `(game_title, storefront)` pair is given a **stable synthetic URL**:
  `https://www.nvidia.com/en-us/geforce-now/games/#{sha256[:12]}`
- This URL is identical whether the game was first seen in a monthly preview or the week-of announcement post.
- Final deduplication pass: `{ url: event }` dict collapses duplicates from multiple posts in a single feed fetch.

### Day-one detection

Bullets containing `"new release"`, `"day one"`, or `"day-one"` (case-insensitive) in the metadata block:
- Set `day_one = True`
- Raise confidence score from 80 → 85
- Append `"Day-one launch detected"` to confidence reasons

### Editorial title stripping

Regex suffix strip: `– RTX Edition`, `– DLSS 4 ...` and similar patterns removed from game title before emit.

### Scope guards (not emitted)

| Category | Mechanism |
|---|---|
| Removals | Bullet text containing `"leaving"` / `"removed from"` skipped |
| Alliance-partner entries | Bullet text with `"geforce now alliance"` / `"coming to alliance"` skipped |
| Editorial posts (no bullets) | Zero `<li>` items → zero events |
| Missing storefronts | Mandatory storefront check rejects bullet |
| Private APIs / GraphQL | Not used |

### Health reporting

- `fetch_events()` raises `SourceError` on network failures — compatible with the pipeline supervisor.
- Per-item exceptions are caught and logged as warnings without crashing the fetch.
- Debug-level logs emitted per post showing event count.

### Confidence model

| Scenario | Score | Reasons |
|---|---|---|
| Standard bullet with known storefront | 80 | parsed from GFN Thursday list + storefront label |
| Day-one release marker present | 85 | + "Day-one launch detected" |

---

## Tests

16 tests in `newsroom/tests/test_geforce_now.py`:

| Test | Fixture |
|---|---|
| `test_standard_thursday_two_games` | Standard Thursday article — 2 games, 2 storefronts |
| `test_monthly_preview_title_variant` | Monthly preview title variant |
| `test_geforce_now_thursday_title_variant` | Alternative "GeForce NOW Thursday" title wording |
| `test_multiple_storefronts_single_bullet` | Single bullet with Steam + Epic → 2 events |
| `test_day_one_launch` | Day-one detection, day_one=True, score≥85 |
| `test_editorial_only_article` | No bullets → 0 events |
| `test_empty_article` | Empty body → 0 events |
| `test_missing_storefront_rejected` | Bullet without known SF → 0 events |
| `test_duplicate_monthly_week_overlap_same_key` | Preview and weekly events share `event_key` |
| `test_multiple_posts_deduplicate_same_game` | 2-post feed with same game → 1 event |
| `test_non_gfn_post_skipped` | Non-GFN post title → 0 events |
| `test_ownership_and_access_model` | access_model + ownership_model values |
| `test_all_supported_storefronts` | All 7 storefronts detected individually |
| `test_rtx_editorial_suffix_stripped_from_title` | "RTX Edition" suffix removed from title |
| `test_removal_bullet_skipped` | Bullet with "leaving" → 0 events |
| `test_badly_formed_xml_returns_empty` | Malformed feed → 0 events, no exception |

---

## Quality gates

| Tool | Result |
|---|---|
| `pytest newsroom/tests/test_geforce_now.py` | ✅ 16/16 passed |
| Full `pytest newsroom/tests/` (excl. stuck PS+ run) | ✅ 147/147 passed |
| `ruff check newsroom/sources/geforce_now.py newsroom/tests/test_geforce_now.py` | ✅ All checks passed |
| `mypy newsroom/sources/geforce_now.py` | ✅ No issues |
| `mypy newsroom/tests/test_geforce_now.py` | ✅ No issues |

---

## Known subtleties / post-mortem

### `ElementTree` falsy element bug
`xml.etree.ElementTree.Element` objects with only `.text` (no child elements) evaluate as **falsy** in Python. The line:

```python
html_el = item.find("{ns}encoded") or item.find("description")
```

would silently skip every valid `content:encoded` element. Fixed with explicit `is not None` pattern. **This is a critical class of RSS parser bug** — all existing collectors should be audited for the same pattern.

---

## Open questions (deferred)

1. Should Steam AppID be extracted from the bullet text for cross-source identity linking?
2. Is a `day_one_date` field warranted for cases where the release date is embedded in the bullet?
3. Dashboard API registration — pending confirmation of the registration pattern used by existing collectors.
