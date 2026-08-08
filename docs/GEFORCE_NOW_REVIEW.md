GEFORCE NOW HOSTILE REVIEW

Verdict:
Production Ready With Conditions

Tests before review:
Collected: 16
Passed: 16
Failed: 0

Tests after fixes:
Collected: 27
Passed: 27
Failed: 0

GeForce NOW tests executed: 27

Claim verification:
- Discovery: RSS polling only from official NVIDIA Blog. Validated.
- Parsing: Extracting HTML from `content:encoded` and `description`. Validated.
- Storefront handling: Validated storefronts. Missing aliases (Microsoft Store, BattleNet variations) were identified and fixed.
- Identity: Determinism verified. Bug found where title extraction cut at first paren instead of last paren (truncating titles with parentheses). Fixed.
- Ownership: STREAMING_SUPPORT & REQUIRES_EXTERNAL_OWNERSHIP correctly enforced.
- Dates: Verified.
- Regions: Bug found where regions were omitted (defaulting inappropriately). Fixed by ensuring explicit `regions=["global"]`.
- Notifications: Validated.
- Health: Bug found where XML parse errors were returning silently `[]` instead of propagating `SourceError`. Fixed.
- API compatibility: Validated via JSON serialization payload structure.

Critical findings:
- [Fixed] Collector `geforce_now` was not successfully registered in `newsroom/cli.py` (`_SOURCES` array). This broke all capability of discovery via the CLI pipeline. Added.

High findings:
- [Fixed] Regex identity defect: Title extraction used first `(` instead of the last `(`, permanently truncating valid game names like `Halo (2003)`.
- [Fixed] Missing aliases for BattleNet and Microsoft Store.
- [Fixed] `assert isinstance(li, Tag)` would be fully stripped under `-O` execution flow, causing attribute errors instead of graceful skips. Replaced with `if not isinstance` guard.

Medium findings:
- [Fixed] `regions` set to empty list violated `COLLECTOR_GUIDE.md` §10. Default has been properly updated to `['global']` representing the global NVIDIA-operated catalog.
- [Fixed] Substring leaks in meta filtering where phrases like `dlcs` would inadvertently block games. Updated to use word boundaries `\bdlc\b`.
- [Fixed] Duplicate events for arbitrary `<li />` nesting layouts.

Low findings:
- [Fixed] Free weekend entries and game titles contaning skip-phrases (like `Leaving Las Vegas`) triggered false positive bans. Bounding conditions updated properly.
- [Documented Limtation] `PromotionType.GIVEAWAY` is semantically incorrect for NVIDIA GFN (it handles catalog support, not permanent library insertions) but satisfies the existing model validator framework.

Live validation:
Verified XML fetch successfully processes against the live NVIDIA Blog RSS `content:encoded` nodes, accurately filtering events without breaking down on foreign structures. Active event extraction yielded 0 events correctly because no GFN Thursday updates exist within the top feed window as of writing.

Duplicate suppression verified:
Yes.

Remaining limitations:
1. `PromotionType.GIVEAWAY` remains semantically awkward but required by `NewsEvent` baseline validation.
2. The NVIDIA Blog RSS is relatively low capacity natively, older posts drop quickly.

Safe to freeze:
YES, WITH CONDITIONS
