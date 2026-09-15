from xml.sax.saxutils import escape
from pathlib import Path
from collections.abc import Iterator, Callable

def listing(community: str = "GamingLaptops", ids: tuple[str, ...] = ("a1",), title: str = "New game sequel reportedly leaked", target: str = "https://example.com/story?utm_source=reddit") -> str:
    entries = []
    for eid in ids:
        link = f"https://www.reddit.com/r/{community}/comments/{eid}/story/"
        body = escape(f'<a href="{target}">[link]</a>')
        entries.append(f'<entry><id>t3_{eid}</id><title>{escape(title)}</title>'
                       f'<link href="{link}"/><published>2026-09-07T12:00:00Z</published>'
                       f'<content type="html">{body}</content></entry>')
    return '<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(entries)+'</feed>'

import pytest
from sqlalchemy import select
from newsroom import database as db
from newsroom.config import settings
from newsroom.discovery import collect
from newsroom.sources.reddit import classify
from clank_reddit import parse_listing, RedditUnavailable

@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    db.reset_engine()
    db.init_db()
    yield
    db.reset_engine()

def get_page(ids: tuple[str, ...] = ("a1",), title: str = "New game sequel reportedly leaked") -> Callable[[str], tuple[int, str]]:
    return lambda _: (200, listing("GamingLeaksAndRumours", ids, title))

def test_baseline_restart_absence_and_reordering(isolated: None) -> None:
    source = "reddit_gaming_leaks"
    assert collect(source, get=get_page())["baseline"]
    assert db.load_discovery_observations() == []
    db.reset_engine()
    assert collect(source, get=get_page())["new_observations"] == 0
    assert collect(source, get=get_page(("a2", "a1")))["new_observations"] == 1
    rows = db.load_discovery_observations()
    assert len(rows) == 1 and rows[0]["classification"] == "game_rumour_unverified"
    assert rows[0]["delivery"] == "blocked"
    collect(source, get=get_page(("a2",)))
    assert collect(source, get=get_page(("a1", "a2")))["new_observations"] == 0
    assert len(db.load_discovery_observations(include_baseline=True)) == 2
    assert db.load_all_events() == []

def test_failed_fetch_retains_state_and_does_not_admit(isolated: None) -> None:
    with pytest.raises(RedditUnavailable):
        collect("reddit_gaming_leaks", get=lambda _: (429, ""))
    assert collect("reddit_gaming_leaks", get=get_page())["baseline"]
    with db.session_scope() as s:
        runs = list(s.scalars(select(db.DiscoveryRunRow).order_by(db.DiscoveryRunRow.id)))
        assert [r.status for r in runs] == ["failed", "ok"]

@pytest.mark.parametrize("title", ["Which game would you like?", "Free game giveaway", "GPU reportedly leaked", "Weekly discussion"])
def test_non_leaks_are_not_rumours(title: str) -> None:
    post = parse_listing(listing("GamingLeaksAndRumours", title=title), "GamingLeaksAndRumours")[0]
    assert classify(post) == "non_leak_or_unclassified"

def test_free_game_claim_is_not_confirmed_offer() -> None:
    post = parse_listing(listing("FreeGameFindings", title="[Steam] [Game] Example"), "FreeGameFindings")[0]
    assert classify(post) == "giveaway_claim_unverified"

def test_dry_run_does_not_persist(isolated: None) -> None:
    collect("reddit_gaming_leaks", get=get_page(), persist=False)
    with db.session_scope() as s:
        assert list(s.scalars(select(db.DiscoveryRunRow))) == []

def test_registry_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from newsroom.cli import source_registry
    monkeypatch.setattr(settings, "enable_reddit_discovery", False)
    specs = [s for s in source_registry() if s.kind == "discovery"]
    assert len(specs) == 2 and all(not s.runnable for s in specs)


def test_manual_dispatch_and_delivery_block(isolated: None, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    from newsroom import cli, notify
    from newsroom.sources import reddit
    from newsroom.webapp import _plan_run, api_discovery, discovery_page
    monkeypatch.setattr(settings, "enable_reddit_discovery", True)
    monkeypatch.setattr(settings, "reports_dir", tmp_path / "reports")
    monkeypatch.setattr(reddit, "fetch", lambda source, get=None:
        parse_listing(listing("GamingLeaksAndRumours"), "GamingLeaksAndRumours"))
    def forbidden(*args: object, **kwargs: object) -> bool:
        raise AssertionError("Discovery reached Discord")
    monkeypatch.setattr(notify, "post_discord", forbidden)
    plan = _plan_run(["reddit_gaming_leaks"])
    assert plan["include_sources"] and plan["selected"] == ["reddit_gaming_leaks"]
    summary = cli.run_pipeline(selected=plan["selected"], include_breakouts=False,
                               include_deals=False, do_notify=True)
    assert summary["discovery"]["reddit_gaming_leaks"]["baseline"]
    assert summary["new"] == 0
    assert api_discovery()["observations"] == []
    assert "Community reports are unverified" in discovery_page()
    assert len(api_discovery(True)["observations"]) == 1


def test_related_articles_do_not_collapse_distinct_posts(isolated: None) -> None:
    collect("reddit_gaming_leaks", get=get_page())
    collect("reddit_gaming_leaks", get=get_page(("a2", "a3", "a1")))
    rows = db.load_discovery_observations()
    assert len(rows) == 2
    assert {r["external_id"] for r in rows} == {"t3_a2", "t3_a3"}
    assert all(len(r["related_observation_ids"]) == 1 for r in rows)


def test_named_game_leak_does_not_need_word_game() -> None:
    post = parse_listing(listing("GamingLeaksAndRumours", title="GTA 6 gameplay leaked"), "GamingLeaksAndRumours")[0]
    assert classify(post) == "game_rumour_unverified"


def test_additive_upgrade_preserves_existing_offers(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from newsroom.config import PROJECT_ROOT
    from newsroom.models import NewsEvent, Source, PromotionType, Confidence
    monkeypatch.setattr(settings, "database_path", tmp_path / "upgrade.db")
    db.reset_engine()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "d2610dba96ff")
    db.sync_events([NewsEvent(source=Source.GOG, title="Existing offer",
        url="https://example.com/offer", promotion_type=PromotionType.GIVEAWAY,
        confidence=Confidence(score=50, reasons=["fixture"]))], {"gog"})
    # Exercise the documented SQLite-safe pre-migration snapshot on a temp DB.
    with sqlite3.connect(settings.database_path) as origin:
        with sqlite3.connect(tmp_path / "before.db") as backup:
            origin.backup(backup)
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.init_db()
    assert [r.title for r in db.load_all_events()] == ["Existing offer"]
    assert db.load_discovery_observations(include_baseline=True) == []
    db.reset_engine()
