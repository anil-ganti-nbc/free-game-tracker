import logging

try:
    from newsroom.models import (
        AccessModel,
        Category,
        Confidence,
        EventType,
        NewsEvent,
        OwnershipModel,
        Source,
    )
except ImportError:
    pass

logger = logging.getLogger(__name__)


def parse_tiers(text: str) -> list[str]:
    tiers = []
    t = text.lower()
    if "luna standard" in t or "included with prime" in t:
        tiers.append("standard")
    if "luna premium" in t:
        tiers.append("premium")
    return tiers


def fetch_events() -> list[NewsEvent]:
    return []
