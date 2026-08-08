import typing
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from newsroom.config import PROJECT_ROOT, settings
from newsroom.database import get_engine, init_db, reset_engine


@pytest.fixture
def clean_db(tmp_path: Path) -> typing.Iterator[None]:
    """Provide an empty DB for the test."""
    db_path = tmp_path / "test_migration.db"
    settings.database_path = db_path
    settings.database_echo = False
    reset_engine()
    yield
    reset_engine()


def test_migration_from_blank(clean_db: None) -> None:
    """A completely fresh DB should hit the standard loop transparently."""
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA table_info(news_events)")).fetchall()
        cols = [r[1] for r in res]
        assert "event_type" in cols
        assert "tiers" in cols


def test_migration_from_legacy(clean_db: None) -> None:
    """A DB matching the previous schema but lacking alembic tables should upgrade cleanly."""
    engine = get_engine()

    # 1. Manually setup alembic backwards explicitly tracking exclusively "87c050402d09"
    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

    # Run creation up to legacy
    command.upgrade(alembic_cfg, "87c050402d09")

    # Verify legacy structure lacks the tracking column
    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA table_info(news_events)")).fetchall()
        cols = [r[1] for r in res]
        assert "event_type" not in cols

    # Delete alembic_version to mimic perfectly a deployed pre-alembic DB
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))

    # 2. Run init_db which should catch the discrepancy natively, stamp identically and upgrade.
    init_db()

    with engine.connect() as conn:
        res = conn.execute(text("PRAGMA table_info(news_events)")).fetchall()
        cols = [r[1] for r in res]
        assert "event_type" in cols
        assert "available_until" in cols


def test_idempotent_multiple_runs(clean_db: None) -> None:
    init_db()
    init_db()  # Second loop must silently do nothing
    engine = get_engine()
    with engine.connect() as conn:
        res = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert res is not None
