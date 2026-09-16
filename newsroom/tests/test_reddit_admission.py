from collections.abc import Callable, Iterator
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from sqlalchemy import select

from clank_reddit import RedditUnavailable, parse_listing
from newsroom import database as db
from newsroom.config import settings
from newsroom.discovery import collect
from newsroom.sources.reddit import classify


def listing(
    community: str = "FreeGameFindings",
    ids: tuple[str, ...] = ("a1",),
    title: str = "[Steam] [Game] Example",
    target: str = "https://example.com/story?utm_source=reddit",
) -> str:
    entries = []
    for external_id in ids:
        link = f"https://www.reddit.com/r/{community}/comments/{external_id}/story/"
        body = escape(f'<a href="{target}">[link]</a>')
        entries.append(
            f"<entry><id>t3_{external_id}</id><title>{escape(title)}</title>"
            f'<link href="{link}"/><published>2026-09-07T12:00:00Z</published>'
            f'<content type="html">{body}</content></entry>'
        )
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>"


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()


def get_page(
    ids: tuple[str, ...] = ("a1",), title: str = "[Steam] [Game] Example"
) -> Callable[[str], tuple[int, str]]:
    return lambda _: (200, listing(ids=ids, title=title))


def combined_listing(*feeds: str) -> str:
    entries = [feed.split(">", 1)[1].rsplit("</feed>", 1)[0] for feed in feeds]
    return '<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>"


def test_baseline_restart_absence_and_reordering(isolated: None) -> None:
    source = "reddit_free_game_findings"
    assert collect(source, get=get_page())["baseline"]
    assert db.load_discovery_observations() == []
    db.reset_engine()
    assert collect(source, get=get_page())["new_observations"] == 0
    assert collect(source, get=get_page(("a2", "a1")))["new_observations"] == 1
    rows = db.load_discovery_observations()
    assert len(rows) == 1 and rows[0]["classification"] == "giveaway_claim_unverified"
    assert rows[0]["delivery"] == "blocked"
    collect(source, get=get_page(("a2",)))
    assert collect(source, get=get_page(("a1", "a2")))["new_observations"] == 0
    assert len(db.load_discovery_observations(include_baseline=True)) == 2
    assert db.load_all_events() == []


def test_failed_fetch_retains_state_and_does_not_admit(isolated: None) -> None:
    source = "reddit_free_game_findings"
    with pytest.raises(RedditUnavailable):
        collect(source, get=lambda _: (429, ""))
    assert collect(source, get=get_page())["baseline"]
    with db.session_scope() as session:
        runs = list(session.scalars(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id)))
        assert [run.status for run in runs] == ["failed", "ok"]


def test_mixed_feed_persists_valid_submission_and_skips_unusable_entries(
    isolated: None,
) -> None:
    source = "reddit_free_game_findings"
    mixed = combined_listing(
        listing(ids=("valid",)),
        listing(ids=("deleted",), title="[deleted]"),
        listing(ids=("removed",), title="[removed]"),
    )

    result = collect(source, get=lambda _: (200, mixed))

    assert result["baseline"]
    rows = db.load_discovery_observations(include_baseline=True)
    assert [row["external_id"] for row in rows] == ["t3_valid"]
    with db.session_scope() as session:
        runs = list(session.scalars(select(db.DiscoveryRunRow)))
        assert [run.status for run in runs] == ["ok"]


def test_all_unusable_feed_fails_without_replacing_previous_state(
    isolated: None,
) -> None:
    source = "reddit_free_game_findings"
    assert collect(source, get=get_page(ids=("baseline",)))["baseline"]
    before = db.load_discovery_observations(include_baseline=True)
    unusable = combined_listing(
        listing(ids=("deleted",), title="[deleted]"),
        listing(ids=("removed",), title="[removed]"),
    )

    with pytest.raises(RedditUnavailable, match="no usable submissions"):
        collect(source, get=lambda _: (200, unusable))

    assert db.load_discovery_observations(include_baseline=True) == before
    with db.session_scope() as session:
        runs = list(session.scalars(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id)))
        assert [run.status for run in runs] == ["ok", "failed"]


@pytest.mark.parametrize("title", ["Weekly discussion", "[PSA] Read this", "Request thread"])
def test_non_game_posts_are_not_giveaway_claims(title: str) -> None:
    post = parse_listing(listing(title=title), "FreeGameFindings")[0]
    assert classify(post) == "non_game_or_unclassified"


def test_free_game_claim_is_not_confirmed_offer() -> None:
    post = parse_listing(listing(), "FreeGameFindings")[0]
    assert classify(post) == "giveaway_claim_unverified"


def test_dry_run_does_not_persist(isolated: None) -> None:
    collect("reddit_free_game_findings", get=get_page(), persist=False)
    with db.session_scope() as session:
        assert list(session.scalars(select(db.DiscoveryRunRow))) == []


def test_registry_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from newsroom.cli import source_registry

    monkeypatch.setattr(settings, "enable_reddit_discovery", False)
    specs = [spec for spec in source_registry() if spec.kind == "discovery"]
    assert [spec.name for spec in specs] == ["reddit_free_game_findings"]
    assert not specs[0].runnable


def test_manual_dispatch_and_delivery_block(
    isolated: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom import cli, notify
    from newsroom.sources import reddit
    from newsroom.webapp import _plan_run, api_discovery, discovery_page

    monkeypatch.setattr(settings, "enable_reddit_discovery", True)
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    monkeypatch.setattr(
        reddit,
        "fetch",
        lambda source, get=None: parse_listing(listing(), "FreeGameFindings"),
    )

    def forbidden(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Discovery reached Discord")

    monkeypatch.setattr(notify, "post_discord", forbidden)
    plan = _plan_run(["reddit_free_game_findings"])
    assert plan["include_sources"]
    assert plan["selected"] == ["reddit_free_game_findings"]
    summary = cli.run_pipeline(
        selected=plan["selected"],
        include_breakouts=False,
        include_deals=False,
        do_notify=True,
    )
    assert summary["discovery"]["reddit_free_game_findings"]["baseline"]
    assert summary["new"] == 0
    assert api_discovery()["observations"] == []
    assert "Community reports are unverified" in discovery_page()
    assert len(api_discovery(True)["observations"]) == 1


def test_duplicate_submissions_remain_evidence_not_duplicate_events(isolated: None) -> None:
    source = "reddit_free_game_findings"
    collect(source, get=get_page())
    collect(source, get=get_page(("a2", "a3", "a1")))
    rows = db.load_discovery_observations()
    assert {row["external_id"] for row in rows} == {"t3_a2", "t3_a3"}
    assert all(len(row["related_observation_ids"]) == 1 for row in rows)
    assert db.load_all_events() == []


def test_discovery_does_not_resurrect_expired_offers(
    isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from newsroom import cli
    from newsroom.models import Confidence, NewsEvent, PromotionType, Source
    from newsroom.sources import reddit

    offer = NewsEvent(
        source=Source.GOG,
        title="Expired offer",
        url="https://example.com/expired",
        promotion_type=PromotionType.GIVEAWAY,
        confidence=Confidence(score=50, reasons=["fixture"]),
    )
    db.sync_events([offer], {Source.GOG.value})
    db.sync_events([], {Source.GOG.value})
    assert db.load_all_events() == []
    monkeypatch.setattr(settings, "enable_reddit_discovery", True)
    monkeypatch.setattr(
        reddit,
        "fetch",
        lambda source, get=None: parse_listing(listing(), "FreeGameFindings"),
    )
    cli.run_pipeline(
        selected=["reddit_free_game_findings"],
        include_breakouts=False,
        include_deals=False,
        do_notify=False,
    )
    assert db.load_all_events() == []


def test_additive_upgrade_preserves_existing_offers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from alembic import command
    from alembic.config import Config
    from newsroom.config import PROJECT_ROOT
    from newsroom.models import Confidence, NewsEvent, PromotionType, Source

    monkeypatch.setattr(settings, "database_path", tmp_path / "upgrade.db")
    db.reset_engine()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "d2610dba96ff")
    db.sync_events(
        [
            NewsEvent(
                source=Source.GOG,
                title="Existing offer",
                url="https://example.com/offer",
                promotion_type=PromotionType.GIVEAWAY,
                confidence=Confidence(score=50, reasons=["fixture"]),
            )
        ],
        {"gog"},
    )
    with (
        sqlite3.connect(settings.database_path) as origin,
        sqlite3.connect(tmp_path / "before.db") as backup,
    ):
        origin.backup(backup)
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.init_db()
    assert [row.title for row in db.load_all_events()] == ["Existing offer"]
    assert db.load_discovery_observations(include_baseline=True) == []
    db.reset_engine()
