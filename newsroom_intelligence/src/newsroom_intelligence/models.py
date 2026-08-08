"""
Core data model for the newsroom intelligence platform.

The NewsEvent is the central object in the system.
Every source converts raw data into NewsEvents.
The pipeline transforms, compares, scores, and notifies on NewsEvents.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Category(str, Enum):
    """High-level news category. Extensible for future source types."""

    GAME_PROMOTION = "game_promotion"
    SEMICONDUCTOR_LEAK = "semiconductor_leak"
    RETAILER_LISTING = "retailer_listing"
    SOFTWARE_COMMIT = "software_commit"
    BENCHMARK = "benchmark"
    REGULATORY_FILING = "regulatory_filing"
    FIRMWARE_RELEASE = "firmware_release"
    OFFICIAL_ANNOUNCEMENT = "official_announcement"


class PromotionType(str, Enum):
    """Type of game promotion. Only used when category is GAME_PROMOTION."""

    FREE = "free"
    DISCOUNT = "discount"
    SEASONAL = "seasonal"
    BUNDLE = "bundle"
    SUBSCRIPTION = "subscription"


class Confidence(float):
    """
    Confidence score: 0.0 to 1.0.

    Represents how certain we are that this event is real and significant.

    - 0.0-0.2: Low (extracted from HTML, unverified)
    - 0.2-0.6: Medium (verified structure, single source)
    - 0.6-0.9: High (multiple sources, cross-referenced)
    - 0.9-1.0: Verified (official data, signed, database-backed)
    """

    def __new__(cls, value: float) -> "Confidence":
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {value}")
        return super().__new__(cls, value)


class NewsEvent(BaseModel):
    """
    Central data model.

    Represents a single piece of news that may be interesting.
    Designed to be extensible for all future source types.
    """

    # Unique identifier
    id: str = Field(default_factory=lambda: str(uuid4()), description="Unique event ID")

    # Classification
    category: Category = Field(description="News category")
    source: str = Field(description="Source plugin name (e.g., 'epic_games', 'steam', 'geekbench')")

    # Content
    title: str = Field(description="Event headline")
    description: str | None = Field(default=None, description="Detailed description")
    url: str = Field(description="Primary URL to the event")

    # For game promotions specifically
    developer: str | None = Field(default=None, description="Developer/publisher name (for game promotions)")
    publisher: str | None = Field(default=None, description="Publisher name (for game promotions)")
    promotion_type: PromotionType | None = Field(default=None, description="Type of promotion (for game promotions)")
    original_price: float | None = Field(default=None, description="Original price in USD (for promotions)")
    current_price: float | None = Field(default=None, description="Current price in USD (for promotions)")

    # Timing
    promotion_start: datetime | None = Field(default=None, description="When the event/promotion starts")
    promotion_end: datetime | None = Field(default=None, description="When the event/promotion ends")

    # Tracking
    discovered_at: datetime = Field(default_factory=datetime.utcnow, description="When we first discovered this event")
    last_seen: datetime = Field(default_factory=datetime.utcnow, description="Last time we verified this event exists")

    # Confidence
    confidence_score: Confidence = Field(
        default=Confidence(0.5), description="How certain we are this event is real and significant (0.0-1.0)"
    )

    # Extensibility
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Source-specific metadata (arbitrary key-value pairs)"
    )

    class Config:
        use_enum_values = False
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            Confidence: lambda v: float(v),
        }

    def is_expired(self) -> bool:
        """Check if promotion has ended."""
        if self.promotion_end is None:
            return False
        return datetime.utcnow() > self.promotion_end

    def days_until_expiration(self) -> int | None:
        """Days until promotion expires, or None if no expiration."""
        if self.promotion_end is None:
            return None
        delta = self.promotion_end - datetime.utcnow()
        return delta.days if delta.days >= 0 else None

    def price_reduction_percent(self) -> float | None:
        """Calculate percentage discount."""
        if self.original_price is None or self.current_price is None:
            return None
        if self.original_price == 0:
            return None
        return ((self.original_price - self.current_price) / self.original_price) * 100

    def __hash__(self) -> int:
        """Make NewsEvent hashable for deduplication."""
        return hash((self.id, self.source, self.url))
