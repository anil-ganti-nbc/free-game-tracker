"""Steam "breakout" sensor — recently released games with strong reviews.

A different signal from free games: newly launched titles that are already very
well reviewed. Candidates come from Steam's "New Releases" list; each is checked
for (a) a release date within the configured window and (b) a review tier at or
above the configured minimum. Everything is plain JSON — no browser.

Pure parsers (fixture-tested) are separated from the I/O ``fetch_breakouts``,
which is HTTP-heavy: it looks up release date (appdetails) and review summary
(appreviews) per candidate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from newsroom.models import NewRelease
from newsroom.sources._http import DEFAULT_HEADERS, fetch_json
from newsroom.sources.steam import STEAM_APPDETAILS_URL, STEAM_FEATURED_URL

logger = logging.getLogger(__name__)

_STORE_APP_BASE = "https://store.steampowered.com/app/"
_APPREVIEWS_URL = "https://store.steampowered.com/appreviews/"
_APPREVIEWS_QUERY = "?json=1&language=all&purchase_type=all&num_per_page=0"

#: Steam review tiers, best first. Threshold comparison uses this order. Includes
#: "Mixed" and below so other sensors (deals) can set a lower floor; breakouts
#: still use a positive floor, so negative tiers simply never qualify there.
_TIER_ORDER = [
    "Overwhelmingly Positive",
    "Very Positive",
    "Positive",
    "Mostly Positive",
    "Mixed",
    "Mostly Negative",
    "Negative",
    "Very Negative",
    "Overwhelmingly Negative",
]


def candidate_appids(featured_payload: dict[str, Any]) -> list[int]:
    """Extract app ids from Steam's featured 'new_releases' list."""
    items = (featured_payload.get("new_releases") or {}).get("items") or []
    appids: list[int] = []
    for item in items:
        appid = item.get("id")
        if isinstance(appid, int):
            appids.append(appid)
    return appids


def parse_release(appdetails_payload: Any, appid: int) -> tuple[str, datetime, bool] | None:
    """Return ``(name, release_date, is_game)`` from an appdetails response.

    Returns ``None`` if the app is missing, unsuccessful, or has no parseable
    full release date (year-only or "Coming soon" values are skipped).
    """
    entry = appdetails_payload.get(str(appid)) if isinstance(appdetails_payload, dict) else None
    if not entry or not entry.get("success"):
        return None
    data = entry.get("data") or {}
    name = data.get("name")
    release = (data.get("release_date") or {}).get("date")
    if not name or not release or (data.get("release_date") or {}).get("coming_soon"):
        return None
    release_date = _parse_store_date(str(release))
    if release_date is None:
        return None
    is_game = data.get("type") == "game"
    return str(name), release_date, is_game


def parse_review_summary(appreviews_payload: Any) -> tuple[str, int, float] | None:
    """Return ``(review_desc, total_reviews, positive_pct)`` or ``None``."""
    if not isinstance(appreviews_payload, dict) or not appreviews_payload.get("success"):
        return None
    summary = appreviews_payload.get("query_summary") or {}
    desc = summary.get("review_score_desc")
    total = summary.get("total_reviews")
    positive = summary.get("total_positive")
    if not desc or not total:
        return None
    pct = round(float(positive) / float(total) * 100, 1) if positive is not None else 0.0
    return str(desc), int(total), pct


def tier_meets(review_desc: str, minimum: str) -> bool:
    """True if ``review_desc`` is at least as good as ``minimum`` (positive tiers)."""
    if review_desc not in _TIER_ORDER or minimum not in _TIER_ORDER:
        return False
    return _TIER_ORDER.index(review_desc) <= _TIER_ORDER.index(minimum)


def within_window(release_date: datetime, now: datetime, max_days: int) -> bool:
    """True if the game released between now and ``max_days`` ago (inclusive)."""
    age_days = (now - release_date).days
    return 0 <= age_days <= max_days


def _parse_store_date(value: str) -> datetime | None:
    """Parse a Steam store date ("Feb 24, 2022" or "24 Feb, 2022") as UTC midnight."""
    for fmt in ("%b %d, %Y", "%d %b, %Y"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def fetch_breakouts(
    client: httpx.Client | None = None,
    now: datetime | None = None,
    max_days: int = 14,
    min_tier: str = "Very Positive",
) -> list[NewRelease]:
    """Trawl Steam new releases and return in-window, well-reviewed games.

    Raises:
        SourceError: If the featured endpoint cannot be fetched.
    """
    moment = now or datetime.now(UTC)
    owns_client = client is None
    client = client or httpx.Client(headers=DEFAULT_HEADERS)
    try:
        featured = fetch_json(STEAM_FEATURED_URL, client=client)
        results: list[NewRelease] = []
        for appid in candidate_appids(featured):
            release = _evaluate_candidate(client, appid, moment, max_days, min_tier)
            if release is not None:
                results.append(release)
    finally:
        if owns_client:
            client.close()
    logger.info("Steam breakouts: %d well-reviewed new release(s)", len(results))
    return results


def _evaluate_candidate(
    client: httpx.Client, appid: int, now: datetime, max_days: int, min_tier: str
) -> NewRelease | None:
    """Check one candidate's release date then reviews; build a NewRelease or None."""
    try:
        details = fetch_json(
            f"{STEAM_APPDETAILS_URL}{appid}&filters=basic,release_date", client=client
        )
        parsed = parse_release(details, appid)
        if parsed is None:
            return None
        name, release_date, is_game = parsed
        if not is_game or not within_window(release_date, now, max_days):
            return None

        reviews = fetch_json(f"{_APPREVIEWS_URL}{appid}{_APPREVIEWS_QUERY}", client=client)
        summary = parse_review_summary(reviews)
        if summary is None:
            return None
        review_desc, total_reviews, positive_pct = summary
        if not tier_meets(review_desc, min_tier):
            return None
    except Exception:  # noqa: BLE001 - one bad candidate must not fail the trawl
        logger.warning("Skipping breakout candidate %s", appid, exc_info=True)
        return None

    return NewRelease(
        appid=appid,
        name=name,
        url=f"{_STORE_APP_BASE}{appid}",
        release_date=release_date,
        review_desc=review_desc,
        total_reviews=total_reviews,
        positive_pct=positive_pct,
    )
