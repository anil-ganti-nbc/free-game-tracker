"""Steam sensor — 100%-off games only.

Steam has no dedicated "free promotions" feed, but its featured-categories
endpoint exposes a ``specials`` list with each offer's discount percentage,
prices (in integer cents), and an expiry timestamp. Per the project scope we
emit **only** offers discounted by 100% — a normally-paid game that is
temporarily free — and ignore every lesser discount. Free-to-play titles never
appear as a 100% discount, so they are excluded naturally.

As with every source, this splits a pure :func:`parse_specials` (tested against
a fixture) from the I/O :func:`fetch_free_games`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from newsroom.models import Confidence, NewsEvent, PromotionType, Source
from newsroom.sources._http import DEFAULT_HEADERS, SourceError, fetch_json

logger = logging.getLogger(__name__)

STEAM_FEATURED_URL = "https://store.steampowered.com/api/featuredcategories?cc=us&l=en"
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids="
_STORE_APP_BASE = "https://store.steampowered.com/app/"

#: Steam prices are integer minor units (cents) of the requested currency.
_PRICE_DIVISOR = 100.0


def parse_specials(payload: dict[str, Any]) -> list[NewsEvent]:
    """Convert a Steam ``featuredcategories`` payload into ``NewsEvent`` objects.

    Only items discounted by exactly 100% are returned. Malformed items are
    skipped with a warning rather than failing the whole parse.
    """
    items = (payload.get("specials") or {}).get("items") or []
    events: list[NewsEvent] = []
    for item in items:
        try:
            event = _normalize_item(item)
        except Exception:  # noqa: BLE001 - one bad item must not fail the run
            logger.warning("Skipping unparseable Steam item %r", item.get("name"), exc_info=True)
            continue
        if event is not None:
            events.append(event)
    return events


def _normalize_item(item: dict[str, Any]) -> NewsEvent | None:
    """Turn one special into a ``NewsEvent``, or ``None`` if it is not 100% off."""
    if item.get("discount_percent") != 100:
        return None
    name = item.get("name")
    appid = item.get("id")
    if not name or appid is None:
        return None

    original_price = _cents_to_price(item.get("original_price"))
    end = _epoch_to_datetime(item.get("discount_expiration"))

    return NewsEvent(
        source=Source.STEAM,
        title=str(name),
        url=f"{_STORE_APP_BASE}{appid}",
        promotion_type=PromotionType.FULL_DISCOUNT,
        original_price=original_price,
        current_price=0.0,
        promotion_end=end,
        confidence=_score(original_price=original_price, end=end),
        metadata={"appid": appid, "currency": item.get("currency")},
    )


def _cents_to_price(cents: Any) -> float | None:
    """Convert integer cents to a rounded major-unit price, or ``None``."""
    if cents is None:
        return None
    return float(round(float(cents) / _PRICE_DIVISOR, 2))


def _epoch_to_datetime(timestamp: Any) -> datetime | None:
    """Convert a unix timestamp to a UTC-aware datetime, or ``None``."""
    if not timestamp:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, OSError, OverflowError):
        logger.warning("Unparseable Steam discount_expiration: %r", timestamp)
        return None


def _score(*, original_price: float | None, end: datetime | None) -> Confidence:
    """Confidence for a Steam 100%-off detection, with explaining reasons."""
    score = 100
    reasons = ["Steam 100% discount (free to keep)"]
    if end is not None:
        reasons.append("Promotion end date detected")
    else:
        score -= 30
        reasons.append("Promotion end date unavailable")
    if original_price is not None and original_price > 0:
        reasons.append(f"MSRP present ({original_price:.2f})")
    else:
        score -= 30
        reasons.append("MSRP unavailable; cannot confirm it was a paid title")
    return Confidence(score=max(score, 0), reasons=reasons)


def _first(values: Any) -> str | None:
    """Return the first entry of a list as a string, or ``None`` if empty."""
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def parse_appdetails(payload: Any, appid: int) -> tuple[str | None, str | None]:
    """Extract ``(developer, publisher)`` from a Steam appdetails response."""
    entry = payload.get(str(appid)) if isinstance(payload, dict) else None
    if not entry or not entry.get("success"):
        return None, None
    data = entry.get("data") or {}
    return _first(data.get("developers")), _first(data.get("publishers"))


def _enrich_attribution(events: list[NewsEvent], client: httpx.Client) -> list[NewsEvent]:
    """Fill in developer/publisher for each event via Steam's appdetails API.

    The featured endpoint omits these fields, so we look them up per app. There
    are rarely more than a couple of 100%-off games, so the extra requests are
    cheap. A failed lookup is skipped, leaving the fields as ``None``.
    """
    enriched: list[NewsEvent] = []
    for event in events:
        appid = event.metadata.get("appid")
        developer, publisher = event.developer, event.publisher
        if appid is not None and (developer is None or publisher is None):
            try:
                data = fetch_json(f"{STEAM_APPDETAILS_URL}{appid}", client=client)
                dev, pub = parse_appdetails(data, int(appid))
                developer = developer or dev
                publisher = publisher or pub
            except (SourceError, ValueError):
                logger.warning("Steam appdetails lookup failed for app %s", appid)
        enriched.append(event.model_copy(update={"developer": developer, "publisher": publisher}))
    return enriched


def fetch_free_games(client: httpx.Client | None = None) -> list[NewsEvent]:
    """Fetch Steam specials, enrich attribution, and return 100%-off games.

    Raises:
        SourceError: If the featured endpoint cannot be fetched after retries.
    """
    owns_client = client is None
    client = client or httpx.Client(headers=DEFAULT_HEADERS)
    try:
        payload = fetch_json(STEAM_FEATURED_URL, client=client)
        events = _enrich_attribution(parse_specials(payload), client)
    finally:
        if owns_client:
            client.close()
    logger.info("Steam: %d free (100%% off) game(s) detected", len(events))
    return events
