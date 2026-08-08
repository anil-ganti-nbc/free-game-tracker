"""Steam deals sensor — substantial discounts on well-reviewed games.

A third Steam signal (distinct from free games and breakout new releases): games
discounted by at least a threshold (default 30%, but never 100% — that's a free
game, handled elsewhere) that people actually like. To keep discounted shovelware
out, a deal must clear a review tier (default "Mixed") *and* a minimum review
count (default 1000).

Candidates come from Steam's storefront *search* endpoint filtered to specials
(``specials=1``), paged and sorted by review count. This deliberately does not
use Steam's featured "specials" carousel (``/api/featuredcategories``): that
list is Valve's hand-picked front page, hard-capped at exactly 10 items — it
missed the vast majority of real discounts (e.g. Gears 5 at 85% off with
24k+ "Mostly Positive" reviews never appeared in it). The search endpoint has
no such cap, but does return thousands of results, so scanning is bounded to
``settings.deal_scan_pages`` pages to avoid hammering Steam or flooding the
tracker — see that setting's docstring for the tradeoff.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from newsroom.config import settings
from newsroom.models import SteamDeal
from newsroom.sources._http import DEFAULT_HEADERS, fetch_json
from newsroom.sources.steam_breakouts import (
    _APPREVIEWS_QUERY,
    _APPREVIEWS_URL,
    parse_review_summary,
    tier_meets,
)

logger = logging.getLogger(__name__)

_STORE_APP_BASE = "https://store.steampowered.com/app/"
_PRICE_DIVISOR = 100.0

_SEARCH_URL = "https://store.steampowered.com/search/results/"
_SEARCH_PAGE_SIZE = 100

# One result row's essentials: appid, title, discount, and the two displayed
# prices (as "$xx.xx" text — the search page never exposes raw cents).
_ROW_RE = re.compile(
    r'data-ds-appid="(?P<appid>\d+)".*?'
    r'<span class="title">(?P<name>.*?)</span>.*?'
    r'data-discount="(?P<discount>\d+)".*?'
    r'discount_original_price">\$(?P<original>[\d,]+\.\d{2})</div>\s*'
    r'<div class="discount_final_price">\$(?P<final>[\d,]+\.\d{2})</div>',
    re.S,
)


def _search_page_url(start: int, count: int) -> str:
    """Build a specials-filtered, review-sorted search page URL."""
    params = {
        "query": "",
        "start": start,
        "count": count,
        "specials": 1,
        "sort_by": "Reviews_DESC",
        "cc": "us",
        "l": "en",
        "infinite": 1,
    }
    return f"{_SEARCH_URL}?{urlencode(params)}"


def parse_search_page(results_html: str) -> list[dict[str, Any]]:
    """Parse one search-results page into specials-shaped candidate dicts."""
    out: list[dict[str, Any]] = []
    for m in _ROW_RE.finditer(results_html):
        out.append(
            {
                "id": int(m["appid"]),
                "name": m["name"],
                "discount_percent": int(m["discount"]),
                "original_price": round(float(m["original"].replace(",", "")) * _PRICE_DIVISOR),
                "final_price": round(float(m["final"].replace(",", "")) * _PRICE_DIVISOR),
                # The search page doesn't expose an expiry timestamp.
                "discount_expiration": None,
            }
        )
    return out


def candidate_specials(items: list[dict[str, Any]], min_discount: int) -> list[dict[str, Any]]:
    """Return specials items discounted at least ``min_discount`` but under 100%."""
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


#: Below this many raw candidates scanned, warn — a healthy run over several
#: pages should see hundreds of discounted items; a low count usually means the
#: search page's markup drifted and ``parse_search_page`` stopped matching rows,
#: which would otherwise look identical to "Steam just has few sales today".
_MIN_EXPECTED_CANDIDATES = 50


def fetch_deals(
    client: httpx.Client | None = None,
    min_discount: int = 30,
    min_tier: str = "Mixed",
    min_reviews: int = 1000,
    max_pages: int | None = None,
) -> list[SteamDeal]:
    """Trawl Steam's discounted-specials search results for well-reviewed deals.

    Pages through up to ``max_pages`` (default ``settings.deal_scan_pages``) of
    ``_SEARCH_PAGE_SIZE`` candidates each, sorted by review count so the
    highest-signal games are scanned first within the bounded horizon.

    Raises:
        SourceError: If a search page cannot be fetched.
    """
    if max_pages is None:
        max_pages = settings.deal_scan_pages
    owns_client = client is None
    client = client or httpx.Client(headers=DEFAULT_HEADERS)
    deals: list[SteamDeal] = []
    candidates_scanned = 0
    try:
        for page in range(max_pages):
            start = page * _SEARCH_PAGE_SIZE
            payload = fetch_json(_search_page_url(start, _SEARCH_PAGE_SIZE), client=client)
            items = parse_search_page(payload.get("results_html", ""))
            if not items:
                break
            candidates_scanned += len(items)
            for item in candidate_specials(items, min_discount):
                deal = _evaluate(client, item, min_tier, min_reviews)
                if deal is not None:
                    deals.append(deal)
            if len(items) < _SEARCH_PAGE_SIZE:
                break
    finally:
        if owns_client:
            client.close()
    if candidates_scanned < _MIN_EXPECTED_CANDIDATES:
        logger.warning(
            "Steam deals: only %d discount candidate(s) scanned across %d page(s) "
            "(min_discount=%d%%) — expected at least %d; the search page markup may "
            "have drifted, or Steam is genuinely running few sales right now",
            candidates_scanned,
            max_pages,
            min_discount,
            _MIN_EXPECTED_CANDIDATES,
        )
    logger.info(
        "Steam deals: scanned %d candidate(s), %d well-reviewed discount(s)",
        candidates_scanned,
        len(deals),
    )
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
