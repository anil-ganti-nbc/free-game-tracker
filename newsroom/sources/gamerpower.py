"""GamerPower sensor — a secondary aggregator for the platforms we can't reach.

Epic, Steam, and GOG have clean first-party APIs, so we read those directly.
Prime Gaming, Humble, itch, Fanatical and others do not — their data is behind
auth-gated JavaScript or blocked endpoints. GamerPower is a free, no-auth public
API that aggregates giveaways across all of them, which lets us cover those
platforms without scraping fragile pages or exposing anyone's account.

Two design choices keep this honest:

* **Complementary, not duplicative.** Any giveaway whose platform is Epic, Steam,
  or GOG is skipped here — those are already covered first-party, and the
  first-party listing is the authority.
* **Marked as secondary.** GamerPower is an aggregator, not the store, so its
  detections are capped below first-party confidence and every one carries a
  "verify at store" reason. The editor is always told to confirm at the source.

As with every source, a pure :func:`parse_giveaways` (fixture-tested) is split
from the I/O :func:`fetch_free_games`.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from newsroom.config import settings
from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.sources._http import fetch_json

logger = logging.getLogger(__name__)

#: PC full-game giveaways. We filter further in the parser.
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways?platform=pc&type=game"

#: Platforms we already cover first-party; skip these to avoid duplicates.
_FIRST_PARTY_PLATFORMS = ("epic", "steam", "gog")

#: We only want full games, never DLC/loot/currency.
_GAME_TYPE = "game"


def parse_giveaways(payload: Any) -> list[NewsEvent]:
    """Convert a GamerPower giveaways payload into ``NewsEvent`` objects.

    Keeps only active, full-game giveaways on platforms we do not already cover
    first-party. Malformed entries are skipped with a warning.
    """
    if not isinstance(payload, list):
        logger.warning("Unexpected GamerPower payload type: %s", type(payload).__name__)
        return []

    events: list[NewsEvent] = []
    for entry in payload:
        try:
            event = _normalize_entry(entry)
        except Exception:  # noqa: BLE001 - one bad entry must not fail the run
            logger.warning(
                "Skipping unparseable GamerPower entry %r",
                entry.get("title") if isinstance(entry, dict) else entry,
                exc_info=True,
            )
            continue
        if event is not None:
            events.append(event)
    return events


def _normalize_entry(entry: dict[str, Any]) -> NewsEvent | None:
    """Turn one giveaway into a ``NewsEvent``, or ``None`` if it is filtered out."""
    if str(entry.get("type", "")).strip().lower() != _GAME_TYPE:
        return None
    if str(entry.get("status", "Active")).strip().lower() != "active":
        return None

    platforms = str(entry.get("platforms", ""))
    if _is_first_party(platforms):
        return None

    title = entry.get("title")
    url = entry.get("open_giveaway_url") or entry.get("gamerpower_url")
    if not title or not url:
        return None

    worth = _parse_worth(entry.get("worth"))
    end = _parse_datetime(entry.get("end_date"))

    return NewsEvent(
        source=Source.GAMERPOWER,
        title=str(title),
        url=str(url),
        promotion_type=PromotionType.GIVEAWAY,
        original_price=worth,
        current_price=0.0,
        promotion_end=end,
        confidence=_score(worth=worth, end=end),
        metadata={
            "gamerpower_id": entry.get("id"),
            "platforms": platforms,
            "gamerpower_url": entry.get("gamerpower_url"),
        },
    )


def _is_first_party(platforms: str) -> bool:
    """True if the giveaway is on a platform we already cover directly."""
    lowered = platforms.lower()
    return any(store in lowered for store in _FIRST_PARTY_PLATFORMS)


def _parse_worth(worth: Any) -> float | None:
    """Parse GamerPower's worth string (e.g. "$29.99") into a float, or ``None``."""
    if not worth:
        return None
    match = re.search(r"[\d.]+", str(worth).replace(",", ""))
    if match is None:
        return None
    try:
        value = float(match.group())
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    """Parse GamerPower's "YYYY-MM-DD HH:MM:SS" end date as UTC, or ``None``.

    GamerPower does not state a timezone; we treat the value as UTC and note that
    assumption here so downstream "ending soon" logic is at least consistent.
    """
    if not value or str(value).strip().upper() == "N/A":
        return None
    try:
        naive = datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        logger.warning("Unparseable GamerPower end_date: %r", value)
        return None
    # GamerPower states no timezone; add the configured offset, then treat as
    # UTC. E.g. if its times are US Eastern (UTC-5), set the offset to 5.
    adjusted = naive + timedelta(hours=settings.gamerpower_utc_offset_hours)
    return adjusted.replace(tzinfo=UTC)


def _score(*, worth: float | None, end: datetime | None) -> Confidence:
    """Confidence for a GamerPower detection.

    Capped below first-party sources because this is an aggregator: the ceiling
    is 90, and every detection tells the editor to confirm at the store.
    """
    score = 90
    reasons = [
        "Reported as a free game giveaway by GamerPower "
        "(secondary source; verify at store)"
    ]
    if end is not None:
        reasons.append("End date provided by aggregator")
    else:
        score -= 20
        reasons.append("End date unavailable")
    if worth is not None and worth > 0:
        reasons.append(f"Listed worth ({worth:.2f})")
    else:
        score -= 20
        reasons.append("Worth unavailable")
    return Confidence(score=max(score, 0), reasons=reasons)


def fetch_free_games(client: httpx.Client | None = None) -> list[NewsEvent]:
    """Fetch GamerPower giveaways and return the complementary ones as events.

    Raises:
        SourceError: If the endpoint cannot be fetched after all retries.
    """
    payload = fetch_json(GAMERPOWER_URL, client=client)
    events = parse_giveaways(payload)
    logger.info("GamerPower: %d complementary giveaway(s) detected", len(events))
    return events
