# Xbox Game Pass Collector

This document describes the implementation of the Xbox Game Pass collector.

## Source
- **Announcement Source**: Parses the Xbox Wire RSS feed for tags `xbox-game-pass`.
- **Catalog Verification**: (Optional) Enriches using undocumented endpoints `catalog.gamepass.com/sigls/v2` and `displaycatalog.mp.microsoft.com/v7.0/products`. Do not rely on them for core event fetching!

## Capabilities
- **Plans**: 
  - Ultimate
  - Premium (mapped from Standard historically)
  - Essential (mapped from Core historically)
  - PC Game Pass (mapped from PC only)
- **Platforms**: Parsed locally (cloud, PC, xbox_one, xbox_series, handheld, console).
- **Day One**: Sets `day_one=True` if explicit, else `None`.
- **EA Play**: Preserves explicitly stated relationship in metadata setting `ea_play=True`.
- **Departures**: Triggers a `CATALOG_REMOVAL` event when games fall under a "Leaving Soon" heading with a date.

## Known Limitations
- Undocumented endpoints are used for enrichment, but they could break.
- Relies heavily on canonical string parsing of headers and titles.

## Regional Verification
- The parser extracts regional availability where available, defaulting to `global` for the canonical US feed but can fallback when extended catalog parsing checks `market=IN` or `GB`.
