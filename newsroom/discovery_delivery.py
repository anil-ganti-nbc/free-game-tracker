"""Durable FGF community-lead outbox; independent of NewsEvent delivery."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from newsroom import database as db
from newsroom import notify
from newsroom.config import settings

logger = logging.getLogger(__name__)
FGF_SOURCE = "reddit_free_game_findings"
FGF_POLICY = "fgt-reddit-discovery-v2"
LEAD_LABEL = "Reddit community lead — unverified giveaway claim"
MAX_ATTEMPTS_PER_RUN = 10


def build_lead_payload(title: str, permalink: str, first_seen: datetime) -> dict[str, Any]:
    """Snapshot copy at first admission so later title edits cannot alter an intent."""
    return {
        "content": LEAD_LABEL,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": title[:256],
                "url": permalink,
                "color": 0xF1C40F,
                "fields": [
                    {"name": "Source", "value": "r/FreeGameFindings", "inline": True},
                    {"name": "Status", "value": "Unverified community claim", "inline": True},
                    {
                        "name": "First observed (UTC)",
                        "value": first_seen.astimezone(UTC).isoformat(),
                        "inline": False,
                    },
                ],
                "footer": {"text": "Verify before publishing · community evidence only"},
            }
        ],
    }


def _valid_payload(payload: Any, permalink: str) -> bool:
    if not isinstance(payload, dict) or payload.get("content") != LEAD_LABEL:
        return False
    embeds = payload.get("embeds")
    return (
        isinstance(embeds, list)
        and len(embeds) == 1
        and isinstance(embeds[0], dict)
        and isinstance(embeds[0].get("title"), str)
        and 0 < len(embeds[0]["title"]) <= 256
        and embeds[0].get("url") == permalink
        and payload.get("allowed_mentions") == {"parse": []}
    )


def _pending_count() -> int:
    with db.session_scope() as session:
        count = session.scalar(
            select(func.count())
            .select_from(db.DiscoveryDeliveryRow)
            .where(
                db.DiscoveryDeliveryRow.source == FGF_SOURCE,
                db.DiscoveryDeliveryRow.status.in_(("pending", "failed")),
            )
        )
        return int(count or 0)


def drain_leads(
    *,
    send: Callable[[str, dict[str, Any]], bool] | None = None,
    webhook_url: str | None = None,
) -> dict[str, int]:
    """Attempt each eligible intent once per run, within the existing run lock.

    A crash after Discord accepts but before the delivered commit is inherently
    ambiguous; the durable outbox gives at-least-once retry in that narrow window.
    """
    result = {"reddit_leads_posted": 0, "reddit_leads_failed": 0, "reddit_leads_held": 0}
    if not settings.enable_reddit_fgf_delivery:
        result["reddit_leads_pending"] = _pending_count()
        return result
    url = webhook_url if webhook_url is not None else settings.discord_webhook_url
    if not url:
        result["reddit_leads_pending"] = _pending_count()
        return result
    with db.session_scope() as session:
        keys = list(
            session.scalars(
                select(db.DiscoveryDeliveryRow.observation_key)
                .where(
                    db.DiscoveryDeliveryRow.source == FGF_SOURCE,
                    db.DiscoveryDeliveryRow.status.in_(("pending", "failed")),
                )
                .order_by(
                    db.DiscoveryDeliveryRow.created_at,
                    db.DiscoveryDeliveryRow.observation_key,
                )
                .limit(MAX_ATTEMPTS_PER_RUN)
            )
        )
    for key in keys:
        with db.session_scope() as session:
            row = session.get(db.DiscoveryDeliveryRow, key)
            if row is None or row.status not in {"pending", "failed"}:
                continue
            if not _valid_payload(row.payload, row.permalink):
                row.status = "held"
                row.last_error = "Invalid community-lead payload; operator review required"
                result["reddit_leads_held"] += 1
                continue
            payload = row.payload
            row.attempts += 1
            row.last_attempt_at = datetime.now(UTC)
            row.last_error = "Delivery outcome unknown until Discord response"
        try:
            accepted = send(url, payload) if send is not None else notify.post_discord(url, payload)
        except Exception:
            logger.exception("FGF community-lead transport failed for %s", key)
            accepted = False
        with db.session_scope() as session:
            row = session.get(db.DiscoveryDeliveryRow, key)
            assert row is not None
            if accepted:
                row.status = "delivered"
                row.delivered_at = datetime.now(UTC)
                row.last_error = None
                result["reddit_leads_posted"] += 1
            else:
                row.status = "failed"
                row.last_error = "Discord transport did not confirm acceptance"
                result["reddit_leads_failed"] += 1
    result["reddit_leads_pending"] = _pending_count()
    return result


def account_leads(*, detected: int, eligible: int, drain: bool) -> dict[str, int]:
    """Keep community-lead accounting separate from NewsEvent delivery."""
    outcome = (
        drain_leads()
        if drain
        else {
            "reddit_leads_posted": 0,
            "reddit_leads_failed": 0,
            "reddit_leads_held": 0,
            "reddit_leads_pending": _pending_count(),
        }
    )
    result = {"reddit_leads_detected": detected, "reddit_leads_eligible": eligible} | outcome
    logger.info(
        "Reddit community leads: detected=%d eligible=%d pending=%d posted=%d failed=%d held=%d",
        detected,
        eligible,
        result["reddit_leads_pending"],
        result["reddit_leads_posted"],
        result["reddit_leads_failed"],
        result["reddit_leads_held"],
    )
    return result
