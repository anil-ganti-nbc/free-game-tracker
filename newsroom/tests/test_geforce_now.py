"""Tests for the GeForce NOW collector.

Fixtures covered
----------------
1. Standard GFN Thursday article -- two games, two storefronts.
2. Monthly preview post -- same parser, different title variant.
3. Multiple storefronts in one bullet -- emits one event per storefront.
4. Day-one launch bullet -- day_one=True, extra confidence reason.
5. Editorial-only article (no bullets) -- zero events.
6. Empty article body -- zero events.
7. Missing storefront in bullet -- bullet rejected, zero events.
8. Duplicate monthly-preview / week-of-release overlap -- same stable key.
9. Non-GFN-Thursday post -- skipped entirely.
"""

from __future__ import annotations

from newsroom.models import (
    AccessModel,
    Category,
    EventType,
    OwnershipModel,
    Source,
)
from newsroom.sources.geforce_now import _parse_feed

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONTENT_NS = 'xmlns:content="http://purl.org/rss/1.0/modules/content/"'


def _rss(title: str = "GFN Thursday: New Games", body: str = "") -> str:
    """Build a minimal NVIDIA-Blog-style RSS feed string."""
    escaped = body.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0" {_CONTENT_NS}>'
        "<channel>"
        "<item>"
        f"<title>{title}</title>"
        "<pubDate>Thu, 05 Aug 2026 14:00:00 +0000</pubDate>"
        "<link>https://blogs.nvidia.com/geforce-news/gfn-thursday/</link>"
        f"<content:encoded><![CDATA[{escaped}]]></content:encoded>"
        "</item>"
        "</channel>"
        "</rss>"
    )


# ---------------------------------------------------------------------------
# Fixture 1 -- Standard GFN Thursday article
# ---------------------------------------------------------------------------


def test_standard_thursday_two_games() -> None:
    body = """
    <ul>
      <li><em>Game One</em> (New release on Steam, Aug 12)</li>
      <li><em>Game Two</em> (Epic Games Store)</li>
    </ul>
    """
    events = _parse_feed(_rss(body=body))
    assert len(events) == 2

    by_sf = {ev.storefronts[0]: ev for ev in events}

    steam_ev = by_sf["steam"]
    assert steam_ev.title == "Game One"
    assert steam_ev.source == Source.GEFORCE_NOW
    assert steam_ev.category == Category.SUBSCRIPTION
    assert steam_ev.event_type == EventType.STREAMING_SUPPORT_ADDED
    assert steam_ev.access_model == AccessModel.STREAMING_SUPPORT
    assert steam_ev.ownership_model == OwnershipModel.REQUIRES_EXTERNAL_OWNERSHIP
    assert steam_ev.day_one is True
    assert any("Day-one" in r for r in steam_ev.confidence.reasons)

    epic_ev = by_sf["epic"]
    assert epic_ev.title == "Game Two"
    assert epic_ev.day_one is None  # no "new release" marker
    assert epic_ev.source == Source.GEFORCE_NOW


# ---------------------------------------------------------------------------
# Fixture 2 -- Monthly preview (different title variant)
# ---------------------------------------------------------------------------


def test_monthly_preview_title_variant() -> None:
    body = """
    <ul>
      <li><em>October Game</em> (Steam, Oct 5)</li>
    </ul>
    """
    feed = _rss(title="GFN Thursday: October Games Preview", body=body)
    events = _parse_feed(feed)
    assert len(events) == 1
    assert "steam" in events[0].storefronts
    assert events[0].title == "October Game"


def test_geforce_now_thursday_title_variant() -> None:
    body = "<ul><li><em>Alpha Game</em> (Steam)</li></ul>"
    feed = _rss(title="GeForce NOW Thursday Game Additions", body=body)
    events = _parse_feed(feed)
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Fixture 3 -- Multiple storefronts in one bullet
# ---------------------------------------------------------------------------


def test_multiple_storefronts_single_bullet() -> None:
    body = """
    <ul>
      <li><em>Multi Game</em> (New release on Steam and Epic Games Store)</li>
    </ul>
    """
    events = _parse_feed(_rss(body=body))
    assert len(events) == 2
    storefronts = {ev.storefronts[0] for ev in events}
    assert storefronts == {"steam", "epic"}
    # Titles should all be the same
    assert all(ev.title == "Multi Game" for ev in events)


# ---------------------------------------------------------------------------
# Fixture 4 -- Day-one launch
# ---------------------------------------------------------------------------


def test_day_one_launch() -> None:
    body = """
    <ul>
      <li><em>Brand New Game</em> (New release on Steam)</li>
    </ul>
    """
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    ev = events[0]
    assert ev.day_one is True
    assert any("Day-one" in r for r in ev.confidence.reasons)
    assert ev.confidence.score >= 85


# ---------------------------------------------------------------------------
# Fixture 5 -- Editorial-only article (no bullet lists)
# ---------------------------------------------------------------------------


def test_editorial_only_article() -> None:
    body = "<p>RTX 5080 servers are now rolling out to more regions!</p>"
    events = _parse_feed(_rss(body=body))
    assert events == []


# ---------------------------------------------------------------------------
# Fixture 6 -- Empty article body
# ---------------------------------------------------------------------------


def test_empty_article() -> None:
    events = _parse_feed(_rss(body=""))
    assert events == []


# ---------------------------------------------------------------------------
# Fixture 7 -- Missing storefront
# ---------------------------------------------------------------------------


def test_missing_storefront_rejected() -> None:
    body = """
    <ul>
      <li><em>Mystery Game</em> (Coming soon, Q4 2026)</li>
    </ul>
    """
    events = _parse_feed(_rss(body=body))
    assert events == []


# ---------------------------------------------------------------------------
# Fixture 8 -- Duplicate monthly-preview / week-of overlap
# ---------------------------------------------------------------------------


def test_duplicate_monthly_week_overlap_same_key() -> None:
    bullet = "<ul><li><em>Overlap Game</em> (Steam)</li></ul>"

    preview_events = _parse_feed(_rss(title="GFN Thursday: Preview", body=bullet))
    weekly_events = _parse_feed(_rss(title="GFN Thursday: Week 1", body=bullet))

    assert len(preview_events) == 1
    assert len(weekly_events) == 1
    # Stable event key must match regardless of which post announced the game.
    assert preview_events[0].event_key == weekly_events[0].event_key


def test_multiple_posts_deduplicate_same_game() -> None:
    """Two GFN Thursday posts mentioning the same game => single event returned."""
    bullet = "<ul><li><em>Same Game</em> (Steam)</li></ul>"
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0" {_CONTENT_NS}>'
        "<channel>"
        "<item>"
        "<title>GFN Thursday: Preview</title>"
        "<pubDate>Thu, 01 Aug 2026 14:00:00 +0000</pubDate>"
        "<link>https://blogs.nvidia.com/1/</link>"
        f"<content:encoded><![CDATA[{bullet}]]></content:encoded>"
        "</item>"
        "<item>"
        "<title>GFN Thursday: Week 1</title>"
        "<pubDate>Thu, 08 Aug 2026 14:00:00 +0000</pubDate>"
        "<link>https://blogs.nvidia.com/2/</link>"
        f"<content:encoded><![CDATA[{bullet}]]></content:encoded>"
        "</item>"
        "</channel>"
        "</rss>"
    )
    events = _parse_feed(feed)
    assert len(events) == 1  # deduplicated across posts


# ---------------------------------------------------------------------------
# Fixture 9 -- Non-GFN-Thursday post skipped
# ---------------------------------------------------------------------------


def test_non_gfn_post_skipped() -> None:
    body = "<ul><li><em>Some Game</em> (Steam)</li></ul>"
    feed = _rss(title="NVIDIA Announces RTX 5090 Ti GPU", body=body)
    events = _parse_feed(feed)
    assert events == []


# ---------------------------------------------------------------------------
# Identity / model assertions
# ---------------------------------------------------------------------------


def test_ownership_and_access_model() -> None:
    body = "<ul><li><em>Any Game</em> (GOG)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    ev = events[0]
    assert ev.access_model == AccessModel.STREAMING_SUPPORT
    assert ev.ownership_model == OwnershipModel.REQUIRES_EXTERNAL_OWNERSHIP


def test_all_supported_storefronts() -> None:
    body = """<ul>
      <li><em>G1</em> (Steam)</li>
      <li><em>G2</em> (Epic Games Store)</li>
      <li><em>G3</em> (Xbox)</li>
      <li><em>G4</em> (Ubisoft Connect)</li>
      <li><em>G5</em> (Battle.net)</li>
      <li><em>G6</em> (GOG)</li>
      <li><em>G7</em> (EA App)</li>
    </ul>"""
    events = _parse_feed(_rss(body=body))
    found = {ev.storefronts[0] for ev in events}
    assert found == {"steam", "epic", "xbox", "ubisoft connect", "battle.net", "gog", "ea"}


def test_rtx_editorial_suffix_stripped_from_title() -> None:
    body = "<ul><li><em>Awesome Game - RTX Edition</em> (Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert "RTX Edition" not in events[0].title


def test_removal_bullet_skipped() -> None:
    body = """<ul>
      <li><em>Old Game</em> (leaving the service, Steam)</li>
    </ul>"""
    events = _parse_feed(_rss(body=body))
    assert events == []


def test_badly_formed_xml_returns_empty() -> None:
    import pytest

    from newsroom.sources._http import SourceError

    with pytest.raises(SourceError, match="RSS feed parse failed"):
        _parse_feed("this is not XML <<<garbage")


# ---------------------------------------------------------------------------
# Hostile review additions
# ---------------------------------------------------------------------------


def test_paren_in_game_title_preserved() -> None:
    """Game names containing parens (e.g., 'Halo (2003)') must not be truncated."""
    body = "<ul><li><em>Game (2024)</em> (New release on Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].title == "Game (2024)"


def test_paren_in_title_complex() -> None:
    """Multi-paren title: 'Game (Part 1)' followed by storefront paren."""
    body = "<ul><li><em>Game (Part 1)</em> (Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].title == "Game (Part 1)"


def test_battlenet_no_dot_alias() -> None:
    """'BattleNet' without a dot must match battle.net."""
    body = "<ul><li><em>Overwatch 2</em> (BattleNet)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].storefronts == ["battle.net"]


def test_battle_net_space_alias() -> None:
    """'Battle Net' with a space must match battle.net."""
    body = "<ul><li><em>Diablo IV</em> (Battle Net)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].storefronts == ["battle.net"]


def test_microsoft_store_alias() -> None:
    """'Microsoft Store' is a real GFN alias for the Xbox/PC Game Pass storefront."""
    body = "<ul><li><em>Forza Horizon 5</em> (Microsoft Store)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].storefronts == ["xbox"]


def test_regions_explicitly_set() -> None:
    """COLLECTOR_GUIDE §10: regions must not be empty (would imply unknown scope)."""
    body = "<ul><li><em>Test Game</em> (Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].regions
    assert "nvidia_operated" in events[0].regions
    assert "global" not in events[0].regions


def test_edition_parentheses_preserved() -> None:
    """Meaningful title parentheses remain intact."""
    body = "<ul><li><em>Game Name (Definitive Edition)</em> (Epic Games Store)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert events[0].title == "Game Name (Definitive Edition)"
    assert events[0].storefronts == ["epic"]


def test_dates_stripped_from_parentheses() -> None:
    body = "<ul><li><em>Game Name</em> (Steam) — available August 7</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert events[0].title == "Game Name"
    assert events[0].storefronts == ["steam"]


def test_emdash_date_before_parentheses() -> None:
    body = "<ul><li><em>Game Name</em> — August 7 (Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert "August" not in events[0].title
    assert "Game Name" in events[0].title
    assert events[0].storefronts == ["steam"]


def test_dlc_bullet_rejected() -> None:
    """DLC announcements must not be emitted as streaming-support events."""
    body = "<ul><li><em>Game DLC Pack 1</em> (New DLC on Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert events == []


def test_free_weekend_bullet_rejected() -> None:
    """Free weekends are temporary and must not pollute the support catalog."""
    body = "<ul><li><em>Game</em> (Free weekend on Steam, Nov 1-3)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert events == []


def test_rtx_suffix_unicode_em_dash() -> None:
    """RTX suffix joined with a Unicode em-dash (\u2013) must be stripped."""
    body = "<ul><li><em>Awesome Game \u2013 RTX Edition</em> (Steam)</li></ul>"
    events = _parse_feed(_rss(body=body))
    assert len(events) == 1
    assert "RTX Edition" not in events[0].title
    assert events[0].title == "Awesome Game"


def test_storefronts_field_on_every_event() -> None:
    """storefronts must be a non-empty list on every emitted event."""
    body = """<ul>
      <li><em>G1</em> (Steam)</li>
      <li><em>G2</em> (Epic Games Store)</li>
      <li><em>G3</em> (GOG)</li>
    </ul>"""
    events = _parse_feed(_rss(body=body))
    assert len(events) == 3
    for ev in events:
        assert ev.storefronts, f"{ev.title}: storefronts must be non-empty"
        assert len(ev.storefronts) == 1


def test_geforce_now_registered_in_sources() -> None:
    """geforce_now must appear in the pipeline _SOURCES registry."""
    from newsroom.cli import _SOURCES

    assert "geforce_now" in _SOURCES, "geforce_now is not registered in the pipeline"
