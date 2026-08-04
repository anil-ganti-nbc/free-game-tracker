"""Epic Games Store sensor.

Epic publishes its weekly free games through a single JSON endpoint. Each
"element" is a store offer; a game is *currently free to claim* when it has an
active promotional offer whose discount percentage is 0. (Epic's
``discountPercentage`` is the fraction of the price you still pay, so ``0`` means
100% off — free — and ``20`` means 80% off, which is an ordinary sale we ignore.)

This module has two halves, deliberately separated:

* :func:`parse_free_games` is a pure function: JSON in, ``NewsEvent`` list out.
  All the detection and filtering logic lives here and is unit-tested against a
  saved fixture with no network access.
* :func:`fetch_free_games` does the I/O — one HTTP GET with graceful retries —
  and then hands the payload to the parser.

The source knows nothing about the database, reporting, or other sources.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, NamedTuple

import httpx

from newsroom.models import Confidence, NewsEvent, PromotionType, Source, UpcomingGame
from newsroom.sources._http import SourceError, fetch_json

__all__ = [
    "EPIC_FREE_GAMES_URL",
    "SourceError",
    "fetch_free_games",
    "fetch_upcoming_free_games",
    "parse_free_games",
    "parse_upcoming_free_games",
]

logger = logging.getLogger(__name__)

#: The public, unauthenticated free-games endpoint.
EPIC_FREE_GAMES_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=en-US&country=US&allowCountries=US"
)

#: Base for building a human-facing store link from an offer slug.
_STORE_PRODUCT_BASE = "https://store.epicgames.com/en-US/p/"
#: Fallback link when no usable slug is present.
_FREE_GAMES_PAGE = "https://store.epicgames.com/en-US/free-games"

#: Offer types that are not standalone games. Per spec: ignore DLC and bundles.
_IGNORED_OFFER_TYPES = {"ADD_ON", "BUNDLE"}
#: Category path prefixes that mark DLC/bundles regardless of offer type.
_IGNORED_CATEGORY_PREFIXES = ("addons", "bundles")


class _ActiveOffer(NamedTuple):
    """The start/end of the promotional window currently making a game free."""

    start: datetime | None
    end: datetime | None


def parse_free_games(
    payload: dict[str, Any], now: datetime | None = None
) -> list[NewsEvent]:
    """Convert a raw Epic ``freeGamesPromotions`` payload into ``NewsEvent`` objects.

    Only games that are free to claim *right now* are returned. DLC, bundles,
    ordinary discounts, and merely-upcoming giveaways are filtered out.

    Args:
        payload: The decoded JSON from the Epic endpoint.
        now: The instant to evaluate promotion windows against. Defaults to the
            current UTC time; injectable so tests are deterministic.

    Returns:
        A list of validated free-game events. Malformed elements are skipped
        with a warning rather than aborting the whole parse.
    """
    moment = now or datetime.now(UTC)
    elements = (
        payload.get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )

    events: list[NewsEvent] = []
    for element in elements:
        try:
            event = _normalize_element(element, moment)
        except Exception:  # noqa: BLE001 - one bad element must not fail the run
            logger.warning(
                "Skipping unparseable Epic element %r", element.get("title"),
                exc_info=True,
            )
            continue
        if event is not None:
            events.append(event)
    return events


def _normalize_element(element: dict[str, Any], now: datetime) -> NewsEvent | None:
    """Turn one Epic element into a ``NewsEvent``, or ``None`` if it is not free."""
    if _should_ignore(element):
        return None

    offer = _active_free_offer(element, now)
    if offer is None:
        return None

    title = element.get("title")
    if not title:
        return None

    original_price = _resolve_original_price(element)
    developer, publisher = _resolve_attribution(element)
    confidence = _score(original_price=original_price, end=offer.end)

    return NewsEvent(
        source=Source.EPIC,
        title=title,
        url=_resolve_url(element),
        developer=developer,
        publisher=publisher,
        promotion_type=PromotionType.GIVEAWAY,
        original_price=original_price,
        current_price=0.0,  # By definition of an active 100%-off offer.
        promotion_start=offer.start,
        promotion_end=offer.end,
        confidence=confidence,
        metadata={
            "offer_id": element.get("id"),
            "namespace": element.get("namespace"),
            "offer_type": element.get("offerType"),
        },
    )


def _should_ignore(element: dict[str, Any]) -> bool:
    """Return True for DLC and bundles, which the spec excludes."""
    if element.get("offerType") in _IGNORED_OFFER_TYPES:
        return True
    paths = [c.get("path", "") for c in element.get("categories") or []]
    return any(p.startswith(_IGNORED_CATEGORY_PREFIXES) for p in paths)


def _active_free_offer(element: dict[str, Any], now: datetime) -> _ActiveOffer | None:
    """Return the active 100%-off promotional window, or ``None`` if not free now.

    Epic nests promotional offers two levels deep. An offer makes the game free
    when its ``discountPercentage`` is 0 and ``now`` falls inside its window.
    """
    promotions = element.get("promotions") or {}
    for group in promotions.get("promotionalOffers") or []:
        for offer in group.get("promotionalOffers") or []:
            setting = offer.get("discountSetting") or {}
            if setting.get("discountPercentage") != 0:
                continue
            start = _parse_epic_datetime(offer.get("startDate"))
            end = _parse_epic_datetime(offer.get("endDate"))
            if start is not None and now < start:
                continue
            if end is not None and now >= end:
                continue
            return _ActiveOffer(start=start, end=end)
    return None


def _resolve_original_price(element: dict[str, Any]) -> float | None:
    """Return the MSRP in major currency units, or ``None`` if unavailable."""
    total = (element.get("price") or {}).get("totalPrice") or {}
    cents = total.get("originalPrice")
    if cents is None:
        return None
    decimals = (total.get("currencyInfo") or {}).get("decimals", 2)
    price = float(cents) / (10 ** int(decimals))
    return float(round(price, 2))


def _resolve_attribution(element: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(developer, publisher)`` from custom attributes and the seller."""
    developer = _custom_attribute(element, "developerName")
    publisher = _custom_attribute(element, "publisherName")
    if publisher is None:
        publisher = (element.get("seller") or {}).get("name")
    return developer, publisher


def _custom_attribute(element: dict[str, Any], key: str) -> str | None:
    """Return a named custom attribute's value, treating "null"/"" as absent."""
    for attr in element.get("customAttributes") or []:
        if attr.get("key") == key:
            value = attr.get("value")
            if value in (None, "", "null"):
                return None
            return str(value)
    return None


def _resolve_url(element: dict[str, Any]) -> str:
    """Build the best available store URL for an offer.

    Prefers the product slug, then catalog/offer page mappings, then the raw
    url slug. Falls back to the free-games page when nothing usable exists.
    """
    product_slug = element.get("productSlug")
    if product_slug:
        return _STORE_PRODUCT_BASE + str(product_slug).split("/")[0]

    for source_key in ("catalogNs", None):
        mappings = (
            (element.get("catalogNs") or {}).get("mappings")
            if source_key
            else element.get("offerMappings")
        ) or []
        for mapping in mappings:
            slug = mapping.get("pageSlug")
            if slug:
                return _STORE_PRODUCT_BASE + str(slug)

    url_slug = element.get("urlSlug")
    if url_slug:
        return _STORE_PRODUCT_BASE + str(url_slug)
    return _FREE_GAMES_PAGE


def _score(*, original_price: float | None, end: datetime | None) -> Confidence:
    """Assign a confidence score and the reasons behind it.

    A clean detection — Epic marks the game 100%-off, we know the MSRP, and we
    know when it ends — scores 100. Missing an end date or a real MSRP each costs
    points and adds an explaining reason, exactly as the spec requires.
    """
    score = 100
    reasons = ["Active Epic promotional offer at 100% off (free to claim)"]

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


def _parse_epic_datetime(value: str | None) -> datetime | None:
    """Parse an Epic ISO-8601 timestamp (``...Z``) into UTC-aware datetime.

    ``fromisoformat`` accepts the trailing ``Z`` only from Python 3.11; we
    normalise it first so the code is robust across interpreters. Returns
    ``None`` for missing or unparseable input.
    """
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        logger.warning("Unparseable Epic datetime: %r", value)
        return None


def parse_upcoming_free_games(
    payload: dict[str, Any], now: datetime | None = None
) -> list[UpcomingGame]:
    """Extract games that Epic has announced will become free in the future.

    This is a heads-up signal, distinct from live giveaways: the games are not
    free yet. Anything currently free, or DLC/bundles, is excluded.
    """
    moment = now or datetime.now(UTC)
    elements = (
        payload.get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )

    upcoming: list[UpcomingGame] = []
    for element in elements:
        try:
            game = _normalize_upcoming(element, moment)
        except Exception:  # noqa: BLE001 - one bad element must not fail the run
            logger.warning(
                "Skipping unparseable upcoming Epic element %r",
                element.get("title"),
                exc_info=True,
            )
            continue
        if game is not None:
            upcoming.append(game)
    return upcoming


def _normalize_upcoming(element: dict[str, Any], now: datetime) -> UpcomingGame | None:
    """Turn one element into an ``UpcomingGame``, or ``None`` if not applicable."""
    if _should_ignore(element):
        return None
    if _active_free_offer(element, now) is not None:
        return None  # already free; that's a live giveaway, not upcoming

    start = _upcoming_free_start(element, now)
    if start is None:
        return None

    title = element.get("title")
    if not title:
        return None
    return UpcomingGame(title=str(title), url=_resolve_url(element), starts=start)


def _upcoming_free_start(element: dict[str, Any], now: datetime) -> datetime | None:
    """Return the future start of an announced 100%-off offer, if any."""
    promotions = element.get("promotions") or {}
    for group in promotions.get("upcomingPromotionalOffers") or []:
        for offer in group.get("promotionalOffers") or []:
            setting = offer.get("discountSetting") or {}
            if setting.get("discountPercentage") != 0:
                continue
            start = _parse_epic_datetime(offer.get("startDate"))
            if start is not None and start > now:
                return start
    return None


# --- I/O -------------------------------------------------------------------


def fetch_free_games(
    client: httpx.Client | None = None, now: datetime | None = None
) -> list[NewsEvent]:
    """Fetch the Epic free-games endpoint and return normalized events.

    Args:
        client: An optional httpx client (useful for testing or connection
            reuse). One is created and closed automatically if not supplied.
        now: Passed through to :func:`parse_free_games` for deterministic tests.

    Raises:
        SourceError: If the endpoint cannot be fetched after all retries.
    """
    payload = fetch_json(EPIC_FREE_GAMES_URL, client=client)
    events = parse_free_games(payload, now=now)
    logger.info("Epic: %d free game(s) detected", len(events))
    return events


def fetch_upcoming_free_games(
    client: httpx.Client | None = None, now: datetime | None = None
) -> list[UpcomingGame]:
    """Fetch Epic's endpoint and return games announced to become free soon.

    Raises:
        SourceError: If the endpoint cannot be fetched after all retries.
    """
    payload = fetch_json(EPIC_FREE_GAMES_URL, client=client)
    upcoming = parse_upcoming_free_games(payload, now=now)
    logger.info("Epic: %d upcoming free game(s) detected", len(upcoming))
    return upcoming
