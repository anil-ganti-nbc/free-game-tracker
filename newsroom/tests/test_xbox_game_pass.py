from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest

from newsroom.models import EventType
from newsroom.sources.xbox_game_pass import (
    SourceError,
    _extract_from_post,
    _parse_date_from_text,
    _parse_plans,
    _parse_platforms,
    fetch_events,
)


def test_parse_platforms() -> None:
    p = _parse_platforms("Cloud, Console, Handheld, PC")
    assert p == ["cloud", "console", "handheld", "pc"]


def test_parse_plans() -> None:
    pl, raw = _parse_plans(
        "Now with Game Pass Premium; joining Game Pass Ultimate and PC Game Pass"
    )
    assert "premium" in pl
    assert "ultimate" in pl
    assert "pc_game_pass" in pl


def test_parse_historical_plans() -> None:
    pl, raw = _parse_plans("Game Pass Core and Xbox Game Pass Standard")
    assert "essential" in pl
    assert "core" in raw
    assert "premium" in pl
    assert "standard" in raw


def test_unknown_plan_gives_lower_confidence() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>Coming Soon</h2>
    <p>Unknown Plan Game (PC)</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming to Xbox Game Pass")
    assert len(events) == 1
    assert events[0].confidence.score == 60  # 90 - 30


def test_parse_date() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    d = _parse_date_from_text("– August 12", pub)
    assert d is not None
    assert d.month == 8
    assert d.day == 12


def test_extract_post_sections_and_leakage() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>Available Today</h2>
    <p>Some Game (Cloud, PC) - August 4</p>
    <p>Now with Game Pass Ultimate.</p>
    
    <h2>Leaving August 15</h2>
    <ul><li>Departing Game (Console)</li></ul>
    
    <h2>Coming Soon</h2>
    <p>Future Game (PC)</p>
    <p>Game Pass Premium</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming to Xbox Game Pass")

    assert len(events) == 3

    add = next(e for e in events if e.title == "Some Game")
    rem = next(e for e in events if e.title == "Departing Game")
    fut = next(e for e in events if e.title == "Future Game")

    assert "pc" in add.platforms
    assert "ultimate" in add.tiers
    assert add.available_from is not None
    assert "US" in add.regions

    assert rem.event_type == EventType.CATALOG_REMOVAL
    assert "console" in rem.platforms
    assert rem.available_until is not None
    assert rem.available_until.month == 8

    assert fut.event_type == EventType.CATALOG_ADDITION
    assert "premium" in fut.tiers
    assert fut.available_from is None


def test_extract_sibling_metadata_safety() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>Coming Soon</h2>
    <li>Game One (PC)</li>
    <li>Game Two (Cloud)</li>
    <p>Descriptive text not mentioning plans.</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming to Xbox")
    assert len(events) == 2
    game_one = next(e for e in events if e.title == "Game One")
    assert "cloud" not in game_one.platforms


def test_extract_ea_play_and_day_one() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>Coming Soon</h2>
    <p>Sports Game (Console, PC)</p>
    <p>Available on day one with Xbox Game Pass! EA Play!</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming to Xbox")
    assert len(events) == 1
    ev = events[0]
    assert ev.day_one is True
    assert ev.metadata.get("ea_play") is True


def test_multiple_games_sharing_article() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>Coming Soon</h2>
    <p>Game A (Console)</p>
    <p>Game Pass Ultimate</p>
    <p>Game B (PC)</p>
    <p>Game Pass Essential</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming")
    assert len(events) == 2
    keys = {e.event_key for e in events}
    assert len(keys) == 2, "Identity safety fail! Multiple distinct events in one URL collided."


def test_dlc_exclusion() -> None:
    pub = datetime(2026, 8, 4, tzinfo=UTC)
    html = """
    <h2>DLC and Game Updates</h2>
    <p>Some Expansion (Console, PC)</p>
    <p>Game Pass Premium</p>
    """
    events = _extract_from_post(html, pub, "http://a", "Coming")
    assert len(events) == 0


def test_raise_source_error_on_fetch_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str) -> NoReturn:
        raise SourceError("Network offline")

    import newsroom.sources.xbox_game_pass as xbox

    monkeypatch.setattr(xbox, "fetch_text", fake_fetch)

    with pytest.raises(SourceError):
        fetch_events()


def test_raise_source_error_on_invalid_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str) -> str:
        return "<invalid>xml"

    import newsroom.sources.xbox_game_pass as xbox

    monkeypatch.setattr(xbox, "fetch_text", fake_fetch)

    with pytest.raises(SourceError):
        fetch_events()


def test_empty_feed_silently_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><rss><channel></channel></rss>'

    import newsroom.sources.xbox_game_pass as xbox

    monkeypatch.setattr(xbox, "fetch_text", fake_fetch)

    events = fetch_events()
    assert events == []


def test_historical_time_window_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    old_date = (datetime.now(UTC) - timedelta(days=40)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    recent_date = (datetime.now(UTC) - timedelta(days=10)).strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
        <item>
            <title>Coming to Xbox Game Pass</title>
            <pubDate>{old_date}</pubDate>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[
                <h2>Coming Soon</h2><p>Old Game (PC)</p><p>Game Pass Ultimate</p>
            ]]></content:encoded>
        </item>
        <item>
            <title>Coming to Xbox Game Pass</title>
            <pubDate>{recent_date}</pubDate>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[
                <h2>Coming Soon</h2><p>New Game (PC)</p><p>Game Pass Ultimate</p>
            ]]></content:encoded>
        </item>
    </channel></rss>
    """

    def fake_fetch(url: str) -> str:
        return xml

    import newsroom.sources.xbox_game_pass as xbox

    monkeypatch.setattr(xbox, "fetch_text", fake_fetch)

    events = fetch_events()
    assert len(events) == 1
    assert events[0].title == "New Game"
