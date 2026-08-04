"""Steam deals sensor — substantial discounts on well-reviewed games.

A third Steam signal (distinct from free games and breakout new releases): games
discounted by at least a threshold (default 30%, but never 100% — that's a free
game, handled elsewhere) that people actually like. To keep discounted shovelware
out, a deal must clear a review tier (default "Mixed") *and* a minimum review
count (default 1000).

Candidates come from Steam's featured "specials" list, which already carries
discount and price. Only the review summary needs a per-game lookup.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from newsroom.models import SteamDeal
from newsroom.sources._http import DEFAULT_HEADERS, fetch_json
from newsroom.sources.steam import STEAM_FEATURED_URL
from newsroom.sources.steam_breakouts import (
    _APPREVIEWS_QUERY,
    _APPREVIEWS_URL,
    parse_review_summary,
    tier_meets,
)

logger = logging.getLogger(__name__)

_STORE_APP_BASE = "https://store.steampowered.com/app/"
_PRICE_DIVISOR = 100.0


def candidate_specials(featured_payload: dict[str, Any], min_discount: int) -> list[dict[str, Any]]:
    """Return specials items discounted at least ``min_discount`` but under 100%."""
    items = (featured_payload.get("specials") or {}).get("items") or []
    out: list[dict[str, Any]] = []
    for item in items:
        discount = item.get("discount_percent")
        if isinstance(discount, int) and min_discount <= discount < 100:
            out.append(item)
    return out


def build_deal(
    item: dict[str, Any], review_desc: str, total_reviews: int, positive_pct: float
) -> SteamDeal | None:
    """Assemble a :class:`SteamDeal` from a specials item and its review summary."""
    appid = item.get("id")
    name = item.get("name")
    discount = item.get("discount_percent")
    if appid is None or not name or not isinstance(discount, int):
        return None
    return SteamDeal(
        appid=int(appid),
        name=str(name),
        url=f"{_STORE_APP_BASE}{appid}",
        discount_percent=discount,
        original_price=_cents(item.get("original_price")),
        final_price=_cents(item.get("final_price")),
        review_desc=review_desc,
        total_reviews=total_reviews,
        positive_pct=positive_pct,
        discount_end=_epoch(item.get("discount_expiration")),
    )


def _cents(value: Any) -> float | None:
    if value is None:
        return None
    return float(round(float(value) / _PRICE_DIVISOR, 2))


def _epoch(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (ValueError, OSError, OverflowError):
        return None


def fetch_deals(
    client: httpx.Client | None = None,
    min_discount: int = 30,
    min_tier: str = "Mixed",
    min_reviews: int = 1000,
) -> list[SteamDeal]:
    """Trawl Steam specials and return well-reviewed, substantially-discounted games.

    Raises:
        SourceError: If the featured endpoint cannot be fetched.
    """
    owns_client = client is None
    client = client or httpx.Client(headers=DEFAULT_HEADERS)
    deals: list[SteamDeal] = []
    try:
        featured = fetch_json(STEAM_FEATURED_URL, client=client)
        for item in candidate_specials(featured, min_discount):
            deal = _evaluate(client, item, min_tier, min_reviews)
            if deal is not None:
                deals.append(deal)
    finally:
        if owns_client:
            client.close()
    logger.info("Steam deals: %d well-reviewed discount(s)", len(deals))
    return deals


def _evaluate(
    client: httpx.Client, item: dict[str, Any], min_tier: str, min_reviews: int
) -> SteamDeal | None:
    """Fetch and check one candidate's reviews; return a SteamDeal or None."""
    appid = item.get("id")
    if appid is None:
        return None
    try:
        reviews = fetch_json(f"{_APPREVIEWS_URL}{appid}{_APPREVIEWS_QUERY}", client=client)
        summary = parse_review_summary(reviews)
        if summary is None:
            return None
        review_desc, total_reviews, positive_pct = summary
        if total_reviews < min_reviews or not tier_meets(review_desc, min_tier):
            return None
    except Exception:  # noqa: BLE001 - one bad candidate must not fail the trawl
        logger.warning("Skipping deal candidate %s", appid, exc_info=True)
        return None
    return build_deal(item, review_desc, total_reviews, positive_pct)
