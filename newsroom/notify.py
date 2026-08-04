"""Discord notifications for newly free games.

This is a *delivery* concern, kept separate from detection: it consumes a
:class:`~newsroom.compare.RunDiff` and posts, and knows nothing about sources,
storage, or reporting. It is entirely opt-in — with no webhook configured,
:func:`notify_new_giveaways` does nothing.

Only *new* giveaways are posted. Because the comparison step already isolates
what changed this run, each free game is announced exactly once; a webhook is
never spammed with the same offer on every cycle.

Like the sources, notification is fault-isolated: a failed post is logged and
swallowed so it can never break a run.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from newsroom.compare import RunDiff
from newsroom.config import settings
from newsroom.models import NewRelease, NewsEvent, SteamDeal

logger = logging.getLogger(__name__)

#: Discord allows at most 10 embeds per webhook message.
MAX_EMBEDS = 10

#: How many times to retry a rate-limited (429) post before giving up.
_MAX_RATE_LIMIT_RETRIES = 3
#: Never wait longer than this for a retry, however large Retry-After claims.
_MAX_RETRY_WAIT_SECONDS = 30.0

_COLOR_HIGH = 0x2ECC71  # green — full-confidence detection
_COLOR_PARTIAL = 0xF1C40F  # amber — something (MSRP or end date) was missing


def _embed(event: NewsEvent) -> dict[str, Any]:
    """Build one Discord embed of facts for a single free game."""
    price = f"${event.original_price:.2f} → Free" if event.original_price else "Free"
    ends = event.promotion_end.date().isoformat() if event.promotion_end else "unknown"
    color = _COLOR_HIGH if event.confidence.score >= 100 else _COLOR_PARTIAL

    return {
        "title": event.title[:256],
        "url": event.url,
        "color": color,
        "fields": [
            {"name": "Store", "value": event.source.value, "inline": True},
            {"name": "Price", "value": price, "inline": True},
            {"name": "Ends", "value": ends, "inline": True},
            {"name": "Confidence", "value": str(event.confidence.score), "inline": True},
        ],
        "footer": {"text": ("Reason: " + "; ".join(event.confidence.reasons))[:2048]},
    }


def build_discord_payload(
    events: list[NewsEvent], min_confidence: int = 0
) -> dict[str, Any] | None:
    """Build the webhook JSON for a batch of newly free games.

    Args:
        events: The newly free games to announce.
        min_confidence: Drop events scoring below this before building.

    Returns:
        A Discord webhook payload, or ``None`` if nothing is worth sending.
    """
    eligible = [e for e in events if e.confidence.score >= min_confidence]
    if not eligible:
        return None

    total = len(eligible)
    shown = eligible[:MAX_EMBEDS]
    content = f"{total} new free game{'s' if total != 1 else ''} detected."
    if total > MAX_EMBEDS:
        content += f" Showing first {MAX_EMBEDS}."

    return {"content": content, "embeds": [_embed(e) for e in shown]}


def _retry_after_seconds(response: httpx.Response) -> float:
    """Extract Discord's requested wait from a 429, capped to something sane."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), _MAX_RETRY_WAIT_SECONDS)
        except ValueError:
            pass
    try:
        body = response.json()
        return min(float(body.get("retry_after", 1.0)), _MAX_RETRY_WAIT_SECONDS)
    except (ValueError, TypeError):
        return 1.0


def build_breakout_payload(releases: list[NewRelease]) -> dict[str, Any] | None:
    """Build the webhook JSON announcing well-reviewed new releases."""
    if not releases:
        return None
    shown = releases[:MAX_EMBEDS]
    total = len(releases)
    content = f"{total} breakout new release{'s' if total != 1 else ''} detected."
    if total > MAX_EMBEDS:
        content += f" Showing first {MAX_EMBEDS}."
    embeds = [
        {
            "title": r.name[:256],
            "url": r.url,
            "color": _COLOR_HIGH,
            "fields": [
                {"name": "Reviews", "value": r.review_desc, "inline": True},
                {"name": "Count", "value": f"{r.total_reviews:,}", "inline": True},
                {"name": "Positive", "value": f"{r.positive_pct:.0f}%", "inline": True},
                {"name": "Released", "value": r.release_date.date().isoformat(), "inline": True},
            ],
        }
        for r in shown
    ]
    return {"content": content, "embeds": embeds}


def notify_new_breakouts(
    releases: list[NewRelease],
    *,
    webhook_url: str | None = None,
    client: httpx.Client | None = None,
) -> bool:
    """Announce newly detected breakout releases to Discord, if configured."""
    url = webhook_url if webhook_url is not None else settings.discord_webhook_url
    if not url:
        return False
    payload = build_breakout_payload(releases)
    if payload is None:
        return False
    posted = post_discord(url, payload, client=client)
    if posted:
        logger.info("Discord: announced %d breakout release(s)", len(payload["embeds"]))
    return posted


def build_deal_payload(deals: list[SteamDeal]) -> dict[str, Any] | None:
    """Build the webhook JSON announcing well-reviewed Steam deals."""
    if not deals:
        return None
    shown = deals[:MAX_EMBEDS]
    total = len(deals)
    content = f"{total} Steam deal{'s' if total != 1 else ''} on well-reviewed games."
    if total > MAX_EMBEDS:
        content += f" Showing first {MAX_EMBEDS}."
    embeds = []
    for d in shown:
        price = "—"
        if d.original_price is not None and d.final_price is not None:
            price = f"${d.original_price:.2f} → ${d.final_price:.2f}"
        fields = [
            {"name": "Discount", "value": f"-{d.discount_percent}%", "inline": True},
            {"name": "Price", "value": price, "inline": True},
            {"name": "Reviews", "value": d.review_desc, "inline": True},
            {"name": "Count", "value": f"{d.total_reviews:,}", "inline": True},
        ]
        if d.discount_end is not None:
            fields.append(
                {"name": "Ends", "value": d.discount_end.date().isoformat(), "inline": True}
            )
        embeds.append({"title": d.name[:256], "url": d.url, "color": _COLOR_HIGH, "fields": fields})
    return {"content": content, "embeds": embeds}


def notify_new_deals(
    deals: list[SteamDeal],
    *,
    webhook_url: str | None = None,
    client: httpx.Client | None = None,
) -> bool:
    """Announce newly detected Steam deals to Discord, if configured."""
    url = webhook_url if webhook_url is not None else settings.discord_webhook_url
    if not url:
        return False
    payload = build_deal_payload(deals)
    if payload is None:
        return False
    posted = post_discord(url, payload, client=client)
    if posted:
        logger.info("Discord: announced %d Steam deal(s)", len(payload["embeds"]))
    return posted


def post_discord(
    webhook_url: str, payload: dict[str, Any], client: httpx.Client | None = None
) -> bool:
    """POST a payload to a Discord webhook, honouring rate limits. Never raises.

    On a 429 the requested ``Retry-After`` is waited (bounded), up to a few
    attempts — so the initial burst of a first run isn't silently dropped.

    Returns:
        True on success, False if the post ultimately failed (which is logged).
    """
    owns_client = client is None
    client = client or httpx.Client()
    try:
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = client.post(
                    webhook_url, json=payload, timeout=settings.http_timeout_seconds
                )
            except httpx.HTTPError as error:
                logger.warning("Discord notification failed: %s", error)
                return False

            if response.status_code == 429:
                if attempt >= _MAX_RATE_LIMIT_RETRIES:
                    logger.warning(
                        "Discord still rate-limited after %d tries; giving up",
                        attempt + 1,
                    )
                    return False
                wait = _retry_after_seconds(response)
                logger.warning("Discord rate-limited; retrying in %.1fs", wait)
                time.sleep(wait)
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("Discord notification failed: %s", error)
                return False
            return True
        return False
    finally:
        if owns_client:
            client.close()


def notify_new_giveaways(
    diff: RunDiff,
    *,
    webhook_url: str | None = None,
    min_confidence: int = 0,
    client: httpx.Client | None = None,
) -> bool:
    """Announce this run's newly free games to Discord, if configured.

    A no-op returning ``False`` when no webhook is set or nothing qualifies.

    Args:
        diff: The run's comparison result; only ``diff.new`` is posted.
        webhook_url: The Discord webhook. Defaults to the configured value.
        min_confidence: Confidence floor for what to announce.
        client: Optional httpx client (for testing / reuse).
    """
    url = webhook_url if webhook_url is not None else settings.discord_webhook_url
    if not url:
        logger.debug("No Discord webhook configured; skipping notification.")
        return False

    payload = build_discord_payload(diff.new, min_confidence=min_confidence)
    if payload is None:
        return False

    posted = post_discord(url, payload, client=client)
    if posted:
        logger.info("Discord: announced %d new free game(s)", len(payload["embeds"]))
    return posted
