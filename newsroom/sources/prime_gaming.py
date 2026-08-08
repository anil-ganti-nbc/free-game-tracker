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


class RawOffer:
    def __init__(self, title, url, section, raw_text):
        self.title = title
        self.url = url
        self.section = section
        self.raw_text = raw_text


def guess_ownership(text: str) -> OwnershipModel:
    text = text.lower()
    if (
        "epic games" in text
        or "gog" in text
        or "amazon games app" in text
        or "legacy games" in text
    ):
        return OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS
    return OwnershipModel.UNKNOWN


def fetch_events() -> list[NewsEvent]:
    # Shared discovery mock
    return []
