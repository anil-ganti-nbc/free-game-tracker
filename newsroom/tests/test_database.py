"""Storage tests: round-trip fidelity, uniqueness, and timezone safety.

Tests point the database at a temporary file via the public ``reset_engine``
seam, so no module internals are monkeypatched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from newsroom import database
from newsroom.config import settings
from newsroom.database import to_row
from newsroom.models import (
    Confidence,
    NewRelease,
    NewsEvent,
    PromotionType,
    Source,
    SteamDeal,
)


@pytest.fixture
def db(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the database at an isolated temp file for the duration of a test."""
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")  # type: ignore[operator]
    database.reset_engine()
    database.init_db()
    yield
    database.reset_engine()


def _sample_event(**overrides: object) -> NewsEvent:
    defaults: dict[str, object] = {
        "source": Source.GOG,
        "title": "Classic RPG",
        "url": "https://www.gog.com/game/classic_rpg",
        "developer": "Old Studio",
        "publisher": "Old Publisher",
        "promotion_type": PromotionType.GIVEAWAY,
        "original_price": 9.99,
        "current_price": 0.0,
        "promotion_start": datetime(2026, 7, 18, tzinfo=UTC),
        "promotion_end": datetime(2026, 7, 25, tzinfo=UTC),
        "confidence": Confidence(
            score=100,
            reasons=["MSRP changed from paid to free", "End date detected"],
        ),
        "metadata": {"store_id": "abc123"},
    }
    defaults.update(overrides)
    return NewsEvent(**defaults)  # type: ignore[arg-type]


def test_round_trip_preserves_fields(db: None) -> None:
    original = _sample_event()
    with database.session_scope() as session:
        session.add(to_row(original))

    restored = database.load_all_events()[0]
    assert restored.source is original.source
    assert restored.title == original.title
    assert restored.url == original.url
    assert restored.promotion_type is original.promotion_type
    assert restored.original_price == original.original_price
    assert restored.confidence.score == 100
    assert restored.confidence.reasons == original.confidence.reasons
    assert restored.metadata == {"store_id": "abc123"}


def test_event_key_is_unique(db: None) -> None:
    with database.session_scope() as session:
        session.add(to_row(_sample_event()))
    with pytest.raises(IntegrityError), database.session_scope() as session:
        session.add(to_row(_sample_event()))


def test_load_all_events_returns_domain_models(db: None) -> None:
    with database.session_scope() as session:
        session.add(to_row(_sample_event()))
    events = database.load_all_events()
    assert len(events) == 1
    assert events[0].event_key == "gog:https://www.gog.com/game/classic_rpg"


def test_loaded_event_is_timezone_aware(db: None) -> None:
    """Regression: datetimes must survive a DB round-trip as UTC-aware.

    Without this, SQLite hands back naive datetimes and the model's time
    helpers raise TypeError when compared against an aware "now".
    """
    end = datetime.now(UTC) + timedelta(hours=5)
    with database.session_scope() as session:
        session.add(to_row(_sample_event(promotion_end=end)))

    restored = database.load_all_events()[0]
    assert restored.promotion_end is not None
    assert restored.promotion_end.tzinfo is not None
    assert restored.is_ending_soon(within_hours=48) is True
    assert restored.is_expired() is False


def test_naive_datetime_is_rejected(db: None) -> None:
    """Storing a naive datetime is a bug and must fail loudly, not silently."""
    naive = datetime(2026, 7, 25)  # noqa: DTZ001 - intentionally naive for the test
    event = _sample_event()
    # Bypass the model (which is always aware) to feed the column a naive value.
    row = to_row(event)
    row.promotion_end = naive
    # SQLAlchemy wraps the column's ValueError in a StatementError.
    with (
        pytest.raises(StatementError, match="naive datetime"),
        database.session_scope() as session,
    ):
        session.add(row)


def test_sync_inserts_updates_and_preserves_discovered_at(db: None) -> None:
    first = datetime(2026, 7, 1, tzinfo=UTC)
    later = datetime(2026, 7, 10, tzinfo=UTC)
    database.sync_events([_sample_event(discovered_at=first, last_seen=first)])

    # Same key, changed MSRP, a later observation.
    database.sync_events(
        [_sample_event(discovered_at=later, last_seen=later, original_price=14.99)]
    )

    events = database.load_all_events()
    assert len(events) == 1
    assert events[0].discovered_at == first  # preserved from first sighting
    assert events[0].last_seen == later  # refreshed
    assert events[0].original_price == 14.99  # updated


def test_sync_prunes_vanished_events(db: None) -> None:
    keep = _sample_event(url="https://www.gog.com/game/keep")
    gone = _sample_event(url="https://www.gog.com/game/gone")
    database.sync_events([keep, gone])
    assert len(database.load_all_events()) == 2

    database.sync_events([keep])
    remaining = database.load_all_events()
    assert {e.url for e in remaining} == {"https://www.gog.com/game/keep"}


def _release(appid: int) -> NewRelease:
    return NewRelease(
        appid=appid,
        name=f"Game {appid}",
        url=f"https://store.steampowered.com/app/{appid}",
        release_date=datetime(2026, 7, 15, tzinfo=UTC),
        review_desc="Overwhelmingly Positive",
        total_reviews=2000,
        positive_pct=95.0,
    )


def test_new_releases_round_trip_and_prune(db: None) -> None:
    database.sync_new_releases([_release(10), _release(20)])
    loaded = database.load_new_releases()
    assert {r.appid for r in loaded} == {10, 20}
    assert loaded[0].review_desc == "Overwhelmingly Positive"

    # A game that ages out / drops tier is no longer returned -> pruned.
    database.sync_new_releases([_release(10)])
    assert {r.appid for r in database.load_new_releases()} == {10}


def _deal(appid: int) -> SteamDeal:
    return SteamDeal(
        appid=appid,
        name=f"Deal {appid}",
        url=f"https://store.steampowered.com/app/{appid}",
        discount_percent=40,
        original_price=39.99,
        final_price=23.99,
        review_desc="Very Positive",
        total_reviews=5000,
        positive_pct=96.0,
        discount_end=datetime(2026, 7, 25, tzinfo=UTC),
    )


def test_deals_round_trip_and_prune(db: None) -> None:
    database.sync_deals([_deal(1), _deal(2)])
    loaded = database.load_deals()
    assert {d.appid for d in loaded} == {1, 2}
    assert loaded[0].discount_percent == 40
    assert loaded[0].final_price == 23.99

    database.sync_deals([_deal(1)])
    assert {d.appid for d in database.load_deals()} == {1}
