"""SQLite persistence for :class:`~newsroom.models.NewsEvent`.

This module owns everything about storage and nothing about anything else. No
source imports it; the pipeline (from a later milestone) is the only caller.

We deliberately keep the ORM row (``NewsEventRow``) separate from the Pydantic
domain model (``NewsEvent``) and translate between them with two small functions
(``to_row`` / ``to_event``). The translation is boring and explicit, which is
exactly what we want: when the schema and the model drift apart, the tests tell
us, rather than a silent coercion.

The engine and session factory are created lazily via ``get_engine`` /
``get_session_factory`` so that configuration (the database path) can change
before first use — for example in tests, or a future ``--db`` flag — without
reaching into module globals.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, create_engine, select
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.types import TypeDecorator

from newsroom.config import settings
from newsroom.models import (
    AccessModel,
    Category,
    Confidence,
    EventType,
    NewRelease,
    NewsEvent,
    OwnershipModel,
    PromotionType,
    Source,
    SteamDeal,
)

logger = logging.getLogger(__name__)


class UtcDateTime(TypeDecorator[datetime]):
    """A ``DateTime`` column that always round-trips as timezone-aware UTC.

    SQLite has no native timezone support and would otherwise return naive
    datetimes on read. A naive value cannot be compared against a timezone-aware
    "now", which would crash the model's ``is_expired`` / ``is_ending_soon``
    helpers once events are loaded back. This decorator refuses to store a naive
    value and re-attaches UTC on the way out, so stored and loaded events behave
    identically.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Normalize a value to UTC before it is written."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Refusing to store a naive datetime; expected UTC-aware.")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Re-attach UTC to a value read back from the database."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class NewsEventRow(Base):
    """The stored form of a :class:`NewsEvent`.

    Enums are stored as their string values, and the two structured fields
    (confidence reasons and metadata) as JSON. ``event_key`` is unique so we can
    upsert an offer across runs in a later milestone.
    """

    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String, unique=True, index=True)

    source: Mapped[str] = mapped_column(String, index=True)
    category: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)

    developer: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)

    promotion_type: Mapped[str] = mapped_column(String, index=True)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    promotion_start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    promotion_end: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    discovered_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime)

    confidence_score: Mapped[int] = mapped_column(Integer)
    confidence_reasons: Mapped[list[str]] = mapped_column(JSON)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    event_type: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    access_model: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    ownership_model: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    service: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    available_from: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    available_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    claim_deadline: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    day_one: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=list)
    regions: Mapped[list[str]] = mapped_column(JSON, default=list)
    storefronts: Mapped[list[str]] = mapped_column(JSON, default=list)


class SourceHealthRow(Base):
    """The latest fetch outcome for one source, so we can spot silent failures.

    ``last_success_at`` advances only when a fetch completes without raising —
    returning zero games still counts as healthy (a quiet week), while an error
    leaves it unchanged so staleness reflects real breakage.
    """

    __tablename__ = "source_health"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    last_attempt_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String)  # "ok" | "error"
    last_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)


class NewReleaseRow(Base):
    """A stored breakout new-release candidate, keyed by Steam appid."""

    __tablename__ = "new_releases"

    appid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    release_date: Mapped[datetime] = mapped_column(UtcDateTime)
    review_desc: Mapped[str] = mapped_column(String)
    total_reviews: Mapped[int] = mapped_column(Integer)
    positive_pct: Mapped[float] = mapped_column(Float)
    discovered_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime)


class SteamDealRow(Base):
    """A stored Steam deal, keyed by appid."""

    __tablename__ = "steam_deals"

    appid: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    discount_percent: Mapped[int] = mapped_column(Integer)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_desc: Mapped[str] = mapped_column(String)
    total_reviews: Mapped[int] = mapped_column(Integer)
    positive_pct: Mapped[float] = mapped_column(Float)
    discount_end: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen: Mapped[datetime] = mapped_column(UtcDateTime)


@dataclass(frozen=True)
class SourceHealth:
    """Domain view of a source's latest fetch outcome."""

    source: str
    last_attempt_at: datetime
    last_success_at: datetime | None
    last_status: str
    last_count: int
    last_error: str | None


def to_row(event: NewsEvent) -> NewsEventRow:
    """Convert a domain :class:`NewsEvent` into a storable ``NewsEventRow``."""
    return NewsEventRow(
        event_key=event.event_key,
        source=event.source.value,
        category=event.category.value,
        title=event.title,
        url=event.url,
        developer=event.developer,
        publisher=event.publisher,
        promotion_type=event.promotion_type.value,
        original_price=event.original_price,
        current_price=event.current_price,
        promotion_start=event.promotion_start,
        promotion_end=event.promotion_end,
        discovered_at=event.discovered_at,
        last_seen=event.last_seen,
        confidence_score=event.confidence.score,
        confidence_reasons=event.confidence.reasons,
        event_metadata=event.metadata,
        event_type=event.event_type.value if event.event_type else None,
        access_model=event.access_model.value if event.access_model else None,
        ownership_model=event.ownership_model.value if event.ownership_model else None,
        service=event.service,
        tiers=event.tiers,
        platforms=event.platforms,
        regions=event.regions,
        storefronts=event.storefronts,
        available_from=event.available_from,
        available_until=event.available_until,
        claim_deadline=event.claim_deadline,
        day_one=event.day_one,
    )


def to_event(row: NewsEventRow) -> NewsEvent:
    """Convert a stored ``NewsEventRow`` back into a domain :class:`NewsEvent`."""
    return NewsEvent(
        source=Source(row.source),
        category=Category(row.category),
        title=row.title,
        url=row.url,
        developer=row.developer,
        publisher=row.publisher,
        promotion_type=PromotionType(row.promotion_type),
        original_price=row.original_price,
        current_price=row.current_price,
        promotion_start=row.promotion_start,
        promotion_end=row.promotion_end,
        discovered_at=row.discovered_at,
        last_seen=row.last_seen,
        confidence=Confidence(
            score=row.confidence_score,
            reasons=list(row.confidence_reasons),
        ),
        metadata=dict(row.event_metadata),
        event_type=EventType(row.event_type) if row.event_type else None,
        access_model=AccessModel(row.access_model) if row.access_model else None,
        ownership_model=OwnershipModel(row.ownership_model) if row.ownership_model else None,
        service=row.service,
        tiers=list(row.tiers) if row.tiers else [],
        platforms=list(row.platforms) if row.platforms else [],
        regions=list(row.regions) if row.regions else [],
        storefronts=list(row.storefronts) if row.storefronts else [],
        available_from=row.available_from,
        available_until=row.available_until,
        claim_deadline=row.claim_deadline,
        day_one=row.day_one,
    )


# --- Engine / session lifecycle --------------------------------------------
# SQLite with a single-file database is all this app needs; there is no
# connection pool worth tuning. The engine is cached but built lazily so config
# can be set before first use.

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it from config on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, echo=settings.database_echo)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Discard the cached engine and session factory.

    The next call to ``get_engine`` rebuilds from current settings. Useful after
    changing configuration at runtime, and for isolating tests.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db() -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    from sqlalchemy import inspect

    inspector = inspect(engine)
    legacy_exists = inspector.has_table("news_events")
    alembic_exists = inspector.has_table("alembic_version")

    import alembic.command
    import alembic.config

    alembic_home = settings.alembic_home

    # We maintain a small migration runner that executes natively preventing user interventions
    alembic_cfg = alembic.config.Config(str(alembic_home / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(alembic_home / "alembic"))

    # If the user has a legacy DB that never saw Alembic, stamp it to the baseline schema revision.
    if legacy_exists and not alembic_exists:
        alembic.command.stamp(alembic_cfg, "87c050402d09")
    elif not legacy_exists:
        # Create initial structure before stamping
        Base.metadata.create_all(engine)
        alembic.command.stamp(alembic_cfg, "head")

    alembic.command.upgrade(alembic_cfg, "head")
    logger.info("Database ready at %s", settings.database_path)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session that commits on success, rolls back on error.

    Usage::

        with session_scope() as session:
            session.add(to_row(event))
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Database transaction failed; rolled back.")
        raise
    finally:
        session.close()


def load_all_events() -> list[NewsEvent]:
    """Return every stored event as domain models. Used by the comparison step.

    This is a read; it uses a plain session and never commits.
    """
    with get_session_factory()() as session:
        rows = session.scalars(select(NewsEventRow)).all()
        return [to_event(row) for row in rows]


def record_source_result(
    source: str, *, ok: bool, count: int = 0, error: str | None = None
) -> None:
    """Record the outcome of one source fetch for health monitoring."""
    now = datetime.now(UTC)
    with session_scope() as session:
        row = session.get(SourceHealthRow, source)
        if row is None:
            row = SourceHealthRow(
                source=source, last_attempt_at=now, last_status="ok", last_count=0
            )
            session.add(row)
        row.last_attempt_at = now
        if ok:
            row.last_success_at = now
            row.last_status = "ok"
            row.last_count = count
            row.last_error = None
        else:
            row.last_status = "error"
            row.last_error = error


def sync_new_releases(releases: list[NewRelease]) -> None:
    """Reconcile stored breakout releases with this run's finds (by appid).

    Same insert/update/delete pattern as ``sync_events``: the table always
    reflects the latest qualifying set, so games that age out of the window or
    slip below the review tier are removed and won't be re-announced.
    """
    now = datetime.now(UTC)
    current_ids = {r.appid for r in releases}
    with session_scope() as session:
        existing = {row.appid: row for row in session.scalars(select(NewReleaseRow)).all()}
        for appid, row in existing.items():
            if appid not in current_ids:
                session.delete(row)
        for release in releases:
            existing_row = existing.get(release.appid)
            if existing_row is None:
                session.add(
                    NewReleaseRow(
                        appid=release.appid,
                        name=release.name,
                        url=release.url,
                        release_date=release.release_date,
                        review_desc=release.review_desc,
                        total_reviews=release.total_reviews,
                        positive_pct=release.positive_pct,
                        discovered_at=now,
                        last_seen=now,
                    )
                )
            else:
                existing_row.name = release.name
                existing_row.url = release.url
                existing_row.release_date = release.release_date
                existing_row.review_desc = release.review_desc
                existing_row.total_reviews = release.total_reviews
                existing_row.positive_pct = release.positive_pct
                existing_row.last_seen = now


def load_new_releases() -> list[NewRelease]:
    """Return stored breakout releases as domain models."""
    with get_session_factory()() as session:
        rows = session.scalars(select(NewReleaseRow)).all()
        return [
            NewRelease(
                appid=row.appid,
                name=row.name,
                url=row.url,
                release_date=row.release_date,
                review_desc=row.review_desc,
                total_reviews=row.total_reviews,
                positive_pct=row.positive_pct,
            )
            for row in rows
        ]


def sync_deals(deals: list[SteamDeal]) -> None:
    """Reconcile stored Steam deals with this run's finds (by appid).

    The Steam specials feed can list the same appid more than once (e.g. a
    bundle and the base game); dedupe by appid before syncing so a repeated
    id in one run doesn't collide with itself on insert.
    """
    now = datetime.now(UTC)
    deals = list({d.appid: d for d in deals}.values())
    current_ids = {d.appid for d in deals}
    with session_scope() as session:
        existing = {row.appid: row for row in session.scalars(select(SteamDealRow)).all()}
        for appid, row in existing.items():
            if appid not in current_ids:
                session.delete(row)
        for deal in deals:
            existing_row = existing.get(deal.appid)
            if existing_row is None:
                session.add(
                    SteamDealRow(
                        appid=deal.appid,
                        name=deal.name,
                        url=deal.url,
                        discount_percent=deal.discount_percent,
                        original_price=deal.original_price,
                        final_price=deal.final_price,
                        review_desc=deal.review_desc,
                        total_reviews=deal.total_reviews,
                        positive_pct=deal.positive_pct,
                        discount_end=deal.discount_end,
                        discovered_at=now,
                        last_seen=now,
                    )
                )
            else:
                existing_row.name = deal.name
                existing_row.url = deal.url
                existing_row.discount_percent = deal.discount_percent
                existing_row.original_price = deal.original_price
                existing_row.final_price = deal.final_price
                existing_row.review_desc = deal.review_desc
                existing_row.total_reviews = deal.total_reviews
                existing_row.positive_pct = deal.positive_pct
                existing_row.discount_end = deal.discount_end
                existing_row.last_seen = now


def load_deals() -> list[SteamDeal]:
    """Return stored Steam deals as domain models."""
    with get_session_factory()() as session:
        rows = session.scalars(select(SteamDealRow)).all()
        return [
            SteamDeal(
                appid=row.appid,
                name=row.name,
                url=row.url,
                discount_percent=row.discount_percent,
                original_price=row.original_price,
                final_price=row.final_price,
                review_desc=row.review_desc,
                total_reviews=row.total_reviews,
                positive_pct=row.positive_pct,
                discount_end=row.discount_end,
            )
            for row in rows
        ]


def load_source_health() -> list[SourceHealth]:
    """Return the latest fetch outcome for every source we've recorded."""
    with get_session_factory()() as session:
        rows = session.scalars(select(SourceHealthRow)).all()
        return [
            SourceHealth(
                source=row.source,
                last_attempt_at=row.last_attempt_at,
                last_success_at=row.last_success_at,
                last_status=row.last_status,
                last_count=row.last_count,
                last_error=row.last_error,
            )
            for row in rows
        ]


def _apply_update(row: NewsEventRow, event: NewsEvent) -> None:
    """Refresh a stored row from a freshly observed event.

    ``discovered_at`` is intentionally preserved — it records when we *first*
    saw the offer — while ``last_seen`` and the mutable promotion details are
    updated to the latest observation.
    """
    row.title = event.title
    row.developer = event.developer
    row.publisher = event.publisher
    row.original_price = event.original_price
    row.current_price = event.current_price
    row.promotion_start = event.promotion_start
    row.promotion_end = event.promotion_end
    row.last_seen = event.last_seen
    row.confidence_score = event.confidence.score
    row.confidence_reasons = event.confidence.reasons
    row.event_metadata = event.metadata
    row.event_type = event.event_type.value if event.event_type else None
    row.access_model = event.access_model.value if event.access_model else None
    row.ownership_model = event.ownership_model.value if event.ownership_model else None
    row.service = event.service
    row.tiers = event.tiers
    row.platforms = event.platforms
    row.regions = event.regions
    row.storefronts = event.storefronts
    row.available_from = event.available_from
    row.available_until = event.available_until
    row.claim_deadline = event.claim_deadline
    row.day_one = event.day_one


def sync_events(events: list[NewsEvent], successful_sources: set[str] | None = None) -> None:
    """Reconcile the stored snapshot with this run's events."""
    current_keys = {event.event_key for event in events}
    with session_scope() as session:
        existing_by_key = {
            row.event_key: row for row in session.scalars(select(NewsEventRow)).all()
        }

        # Remove offers that are no longer live.
        for key, row in existing_by_key.items():
            if successful_sources is not None and row.source not in successful_sources:
                continue
            if key not in current_keys:
                session.delete(row)

        # Insert or refresh live offers.
        for event in events:
            existing = existing_by_key.get(event.event_key)
            if existing is None:
                session.add(to_row(event))
            else:
                _apply_update(existing, event)
