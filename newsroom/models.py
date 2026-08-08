"""The single normalized data model for the whole application: ``NewsEvent``.

Every source (Epic, Steam, GOG, and any future sensor) converts its raw data
into ``NewsEvent`` objects. Nothing downstream — the database, the comparison
step, the report — needs to know which source an event came from.

Design notes
------------
* This is a *Pydantic* model. It is the validation boundary: if a value is
  wrong, we want to fail here, loudly, before anything is stored.
* The database's ORM row is a separate class (see ``database.py``). We keep the
  in-memory domain model and the storage schema decoupled on purpose so that
  changing one does not silently reshape the other.
* Confidence is modelled as a small value object rather than a bare number,
  because the spec requires that every detection explain *why* it fired. A score
  without its reasons is not useful to an editor.
"""

from __future__ import annotations

import collections
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Source(StrEnum):
    """The store a promotion was observed on.

    Version 0.1 supports exactly three. New sensors will add members here.
    """

    EPIC = "epic"
    STEAM = "steam"
    GOG = "gog"
    #: A third-party aggregator, used to cover platforms without a clean
    #: first-party API (Prime Gaming, Humble, itch, etc.). Secondary source.
    GAMERPOWER = "gamerpower"
    PLAYSTATION_PLUS = "playstation_plus"
    XBOX_GAME_PASS = "xbox_game_pass"
    PRIME_GAMING = "prime_gaming"
    AMAZON_LUNA = "amazon_luna"
    GEFORCE_NOW = "geforce_now"


class Category(StrEnum):
    """The broad kind of thing an event represents.

    Version 0.1 only ever emits ``GAME_PROMOTION``. The field exists because
    future sensors (kernel commits, regulatory filings, and so on) will need to
    to coexist in the same table, and it is cheaper to reserve the column now than
    to migrate later. We deliberately do *not* add those future members yet.
    """

    GAME_PROMOTION = "game_promotion"
    SUBSCRIPTION = "subscription"


class PromotionType(StrEnum):
    """How a game came to be free.

    These map directly onto the four things Version 0.1 must detect.
    """

    #: Free to claim and keep, usually for a limited window (Epic/GOG giveaways).
    GIVEAWAY = "giveaway"
    #: Temporarily free to play, not to keep (Steam free weekends).
    FREE_WEEKEND = "free_weekend"
    #: Price permanently dropped to zero (and it is not a free-to-play title).
    PERMANENTLY_FREE = "permanently_free"
    #: A 100%-off discount on a normally paid game (Steam).
    FULL_DISCOUNT = "full_discount"


class EventType(StrEnum):
    GIVEAWAY = "giveaway"
    FREE_WEEKEND = "free_weekend"
    PERMANENTLY_FREE = "permanently_free"
    FULL_DISCOUNT = "full_discount"
    CATALOG_ADDITION = "catalog_addition"
    CATALOG_REMOVAL = "catalog_removal"
    CLAIMABLE_GAME = "claimable_game"
    TRIAL_ADDED = "trial_added"
    DLC_ADDED = "dlc_added"
    PERK_ADDED = "perk_added"
    STREAMING_SUPPORT_ADDED = "streaming_support_added"
    STREAMING_SUPPORT_REMOVED = "streaming_support_removed"
    AVAILABILITY_CHANGED = "availability_changed"
    DATE_CHANGED = "date_changed"
    TIER_CHANGED = "tier_changed"
    RELEASE_DELAYED = "release_delayed"


class AccessModel(StrEnum):
    CLAIMABLE = "claimable"
    SUBSCRIPTION_CATALOG = "subscription_catalog"
    STREAMING_SUPPORT = "streaming_support"
    LIMITED_TRIAL = "limited_trial"
    INCLUDED_DLC = "included_dlc"
    MEMBER_PERK = "member_perk"
    MEMBER_DISCOUNT = "member_discount"


class OwnershipModel(StrEnum):
    PERMANENT_WHILE_ACCOUNT_EXISTS = "permanent_while_account_exists"
    ACCESSIBLE_WHILE_SUBSCRIBED = "accessible_while_subscribed"
    ACCESSIBLE_WHILE_IN_CATALOG = "accessible_while_in_catalog"
    REQUIRES_EXTERNAL_OWNERSHIP = "requires_external_ownership"
    LIMITED_DURATION_ACCESS = "limited_duration_access"
    UNKNOWN = "unknown"


class Confidence(BaseModel):
    """A detection's confidence score together with the reasons for it.

    The score is an integer from 0 to 100. The reasons are short human-readable
    strings explaining what evidence produced the score, e.g. "MSRP changed from
    paid to free" or "End date unavailable". An editor reads the reasons, not
    the number.
    """

    score: int = Field(ge=0, le=100, description="Confidence from 0 to 100.")
    reasons: list[str] = Field(
        min_length=1,
        description="Why this score was assigned. At least one reason is required.",
    )

    @field_validator("reasons")
    @classmethod
    def _reasons_must_be_non_empty(cls, value: list[str]) -> list[str]:
        """Reject blank or whitespace-only reasons; they explain nothing."""
        cleaned = [r.strip() for r in value if r and r.strip()]
        if not cleaned:
            raise ValueError("Confidence requires at least one non-empty reason.")
        return cleaned


@dataclass(frozen=True)
class UpcomingGame:
    """A game announced to become free *soon* — a heads-up, not a live giveaway.

    Kept deliberately lightweight and separate from :class:`NewsEvent`: an
    upcoming game is not free yet, so it does not belong in the detect/store/
    notify pipeline. It only appears as a "coming soon" note in the report.
    """

    title: str
    url: str
    starts: datetime | None


@dataclass(frozen=True)
class NewRelease:
    """A recently released game with strong reviews — a "breakout" candidate.

    A separate signal from free games (it isn't a promotion), so it lives in its
    own lane: its own table and its own dashboard panel. ``release_date`` is
    UTC-midnight of the store's listed date; the days-since-launch window is
    computed at display time so the dashboard slider can filter it live.
    """

    appid: int
    name: str
    url: str
    release_date: datetime
    review_desc: str
    total_reviews: int
    positive_pct: float


@dataclass(frozen=True)
class SteamDeal:
    """A substantially discounted, well-reviewed Steam game.

    A third signal lane (not free, not a new release): a real deal on a game
    people actually like. Its own table and dashboard panel.
    """

    appid: int
    name: str
    url: str
    discount_percent: int
    original_price: float | None
    final_price: float | None
    review_desc: str
    total_reviews: int
    positive_pct: float
    discount_end: datetime | None


class NewsEvent(BaseModel):
    """A single potentially newsworthy fact discovered by a source.

    An event is a snapshot of "this game is free on this store, on these terms,
    right now". Whether it is *news* is for the editor to decide; our job is to
    record it accurately and to note when it changes.
    """

    # --- Identity / classification -----------------------------------------
    source: Source = Field(description="Which store this was observed on.")
    category: Category = Field(
        default=Category.GAME_PROMOTION,
        description="The broad kind of event. Always a game promotion in v0.1.",
    )
    title: str = Field(min_length=1, description="The game's title.")
    url: str = Field(min_length=1, description="Canonical store URL for the offer.")

    # --- Attribution --------------------------------------------------------
    developer: str | None = Field(default=None, description="Developer, if known.")
    publisher: str | None = Field(default=None, description="Publisher, if known.")

    # --- Promotion terms ----------------------------------------------------
    promotion_type: PromotionType = Field(description="How the game became free.")
    original_price: float | None = Field(
        default=None,
        ge=0,
        description="MSRP before the promotion, in the source's currency.",
    )
    current_price: float | None = Field(
        default=None,
        ge=0,
        description="Price during the promotion. Usually 0 for a free offer.",
    )
    promotion_start: datetime | None = Field(
        default=None, description="When the promotion began, if known."
    )
    promotion_end: datetime | None = Field(
        default=None, description="When the promotion ends, if known."
    )

    # --- Subscription specifics ---------------------------------------------
    event_type: EventType | None = Field(default=None, description="The type of event.")
    access_model: AccessModel | None = Field(default=None, description="The access rights granted.")
    ownership_model: OwnershipModel | None = Field(default=None, description="Ownership duration.")
    service: str | None = Field(default=None, description="Subscription service identifier.")
    tiers: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    storefronts: list[str] = Field(default_factory=list)
    available_from: datetime | None = Field(default=None)
    available_until: datetime | None = Field(default=None)
    claim_deadline: datetime | None = Field(default=None)
    day_one: bool | None = Field(default=None)

    # --- Tracking -----------------------------------------------------------
    discovered_at: datetime = Field(
        default_factory=_utcnow,
        description="When this app first saw this offer.",
    )
    last_seen: datetime = Field(
        default_factory=_utcnow,
        description="Most recent run in which this offer was still present.",
    )

    # --- Evidence -----------------------------------------------------------
    confidence: Confidence = Field(description="Score and reasons for this detection.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific raw details kept for auditing. Free-form.",
    )

    @model_validator(mode="after")
    def _check_price_consistency(self) -> NewsEvent:
        """Guard against nonsensical price pairs.

        If both prices are present, the current price must not exceed the
        original — a "free game" that costs more than its MSRP is a parsing bug,
        not a promotion.
        """
        if (
            self.original_price is not None
            and self.current_price is not None
            and self.current_price > self.original_price
        ):
            raise ValueError(
                f"current_price ({self.current_price}) exceeds "
                f"original_price ({self.original_price})."
            )
        return self

    @model_validator(mode="after")
    def _check_promotion_window(self) -> NewsEvent:
        """Reject a promotion whose end precedes its start."""
        if (
            self.promotion_start is not None
            and self.promotion_end is not None
            and self.promotion_end < self.promotion_start
        ):
            raise ValueError("promotion_end is before promotion_start.")
        return self

    @field_validator("tiers", "platforms", "regions", "storefronts", mode="before")
    @classmethod
    def _normalize_collections(cls, value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, collections.abc.Iterable):
            return []
        # normalize, strip, remove empty, and sort deterministically
        cleaned = {str(item).strip() for item in value if str(item).strip()}
        return sorted(list(cleaned))

    @property
    def event_key(self) -> str:
        """A stable logical identity for this offer across runs.

        Two observations of the same offer (same store, same URL) share a key,
        which is how the comparison step in a later milestone will recognise
        that an event is unchanged, updated, or gone. The URL is the most stable
        per-offer identifier the stores give us.
        """
        if self.category != Category.SUBSCRIPTION:
            return f"{self.source.value}:{self.url}"

        ev_type = self.event_type.value if self.event_type else "unknown"
        svc = self.service or "unknown"

        variant_parts = [f"title={self.title}"]
        if self.tiers:
            variant_parts.append("tiers=" + ",".join(self.tiers))
        if self.platforms:
            variant_parts.append("platforms=" + ",".join(self.platforms))
        if self.regions:
            variant_parts.append("regions=" + ",".join(self.regions))
        if self.available_from:
            variant_parts.append("from=" + str(int(self.available_from.timestamp())))
        if self.available_until:
            variant_parts.append("until=" + str(int(self.available_until.timestamp())))

        variant = "|".join(variant_parts)
        if variant:
            digest = hashlib.sha256(variant.encode("utf-8")).hexdigest()[:16]
            return f"{self.source.value}:{self.url}:{ev_type}:{svc}:{digest}"
        return f"{self.source.value}:{self.url}:{ev_type}:{svc}:base"

    def is_ending_soon(self, within_hours: int = 48) -> bool:
        """Return True if the promotion ends within ``within_hours`` from now.

        Returns False when there is no known end date — we do not guess.
        """
        if self.promotion_end is None:
            return False
        remaining = self.promotion_end - _utcnow()
        return 0 <= remaining.total_seconds() <= within_hours * 3600

    def is_expired(self) -> bool:
        """Return True if the promotion's end date is in the past."""
        if self.promotion_end is None:
            return False
        return _utcnow() > self.promotion_end
