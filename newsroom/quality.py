"""The quality gate: decides which detections are worth surfacing.

Detection collects everything a source reports, and the database keeps the full
record. But not every free game is worth an editor's attention — a 49-cent asset
flip going free, or an aggregator entry with no listed value and low confidence,
is a "nothingburger". This module filters what actually reaches the reports and
Discord, without discarding anything from storage.

The gate is pure and configurable, so its behaviour is entirely driven by
settings and is easy to test.
"""

from __future__ import annotations

from newsroom.models import NewsEvent


def passes_quality_gate(
    event: NewsEvent,
    *,
    min_confidence: int = 0,
    min_price: float = 0.0,
    require_known_price: bool = False,
) -> bool:
    """Return True if an event is worth surfacing under the given thresholds.

    Args:
        event: The detection to judge.
        min_confidence: Reject detections scoring below this.
        min_price: Reject games whose known MSRP is below this.
        require_known_price: Reject games with no real MSRP (missing or zero).

    A price that is missing or zero is treated as "unknown value": such an event
    passes only when ``require_known_price`` is False, and it never satisfies a
    non-zero ``min_price``.
    """
    if event.confidence.score < min_confidence:
        return False

    price = event.original_price
    if price is None or price <= 0:
        return not require_known_price
    return price >= min_price


def filter_events(
    events: list[NewsEvent],
    *,
    min_confidence: int = 0,
    min_price: float = 0.0,
    require_known_price: bool = False,
) -> list[NewsEvent]:
    """Return only the events that pass the quality gate, order preserved."""
    return [
        event
        for event in events
        if passes_quality_gate(
            event,
            min_confidence=min_confidence,
            min_price=min_price,
            require_known_price=require_known_price,
        )
    ]
