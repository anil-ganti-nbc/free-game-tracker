import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RawAmazonOffer:
    title: str
    url: str
    published_at: datetime
    section_heading: str
    raw_text: str
    is_luna: bool
    is_prime_gaming: bool


def fetch_recent_announcements(http_client) -> list[RawAmazonOffer]:
    # Placeholder for discovery implementation
    return []
