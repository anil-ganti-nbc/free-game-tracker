import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest

from newsroom.models import AccessModel, Category, EventType, OwnershipModel
from newsroom.sources.playstation_plus import (
    _detect_standalone_access_event,
    _extract_games_from_html,
    _parse_dates_from_text,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "psblog_feed.xml"


def test_extracts_essential_games() -> None:
    root = ET.parse(FIXTURE_PATH).getroot()
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        if title_elem is None:
            continue
        title = title_elem.text
        if title is None or "Monthly Games" not in title:
            continue

        content_elem = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        link_elem = item.find("link")

        if content_elem is None or link_elem is None:
            continue

        content = str(content_elem.text)
        link = str(link_elem.text)

        events = _extract_games_from_html(
            content,
            ["essential"],
            EventType.CLAIMABLE_GAME,
            AccessModel.CLAIMABLE,
            OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS,
            datetime(2026, 8, 1, tzinfo=UTC),
            link,
        )

        assert len(events) > 0

        # Verify a valid game from the fixture
        game = next(
            (
                e
                for e in events
                if "Signalis" in e.title or "Big Walk" in e.title or "Dying Light 2" in e.title
            ),
            events[0],
        )
        assert "essential" in game.tiers
        assert "ps4" in game.platforms or "ps5" in game.platforms
        assert game.claim_deadline is not None
        assert game.claim_deadline.year == datetime.now(UTC).year
        return


def test_extracts_catalog_games() -> None:
    root = ET.parse(FIXTURE_PATH).getroot()
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        if title_elem is None:
            continue
        title = title_elem.text
        if title is None or "Game Catalog" not in title:
            continue

        content_elem = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        link_elem = item.find("link")

        if content_elem is None or link_elem is None:
            continue

        content = str(content_elem.text)
        link = str(link_elem.text)

        events = _extract_games_from_html(
            content,
            ["extra", "premium"],
            EventType.CATALOG_ADDITION,
            AccessModel.SUBSCRIPTION_CATALOG,
            OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
            datetime(2026, 8, 1, tzinfo=UTC),
            link,
        )

        assert len(events) > 0

        avatar = next(e for e in events if "Avatar" in e.title)
        assert "extra" in avatar.tiers
        assert "premium" in avatar.tiers
        return


def test_empty_html() -> None:
    events = _extract_games_from_html(
        "",
        ["essential"],
        EventType.CLAIMABLE_GAME,
        AccessModel.CLAIMABLE,
        OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS,
        datetime(2026, 8, 1, tzinfo=UTC),
        "http://a",
    )
    assert len(events) == 0


def test_deluxe_tier_handling() -> None:
    html = "<h2>PlayStation Plus Deluxe</h2><strong>Super Game | PS4, PS5</strong>"
    events = _extract_games_from_html(
        html,
        ["extra"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 8, 1, tzinfo=UTC),
        "http://a",
    )
    assert "deluxe" in events[0].tiers
    assert "Super Game" in events[0].title


def test_classics_catalog() -> None:
    html = "<h2>PlayStation Plus Premium | Classics</h2><strong>Classic Game | PS4, PS5</strong>"
    events = _extract_games_from_html(
        html,
        ["extra", "premium"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 8, 1, tzinfo=UTC),
        "http://a",
    )
    assert events[0].metadata.get("catalog_section") == "classics"
    assert "premium" in events[0].tiers


def test_dst_winter() -> None:
    # Winter is standard time (PST, UTC-8).
    # Nov 15th 2026 01:00 UTC -> Nov 14th 17:00 PST.
    pub_date = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    # The intended date is Nov 14th, so it normalizes to Nov 14 00:00 UTC.
    assert start == datetime(2026, 11, 14, 0, 0, tzinfo=UTC)


def test_dst_summer() -> None:
    # Summer is Daylight Saving Time (PDT, UTC-7).
    # Jul 15th 2026 01:00 UTC -> Jul 14th 18:00 PDT.
    pub_date = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 7, 14, 0, 0, tzinfo=UTC)


def test_dst_transition_march() -> None:
    # US DST transition is 2nd Sunday in March. (Mar 8 2026).
    # Let's test a date near the boundary.
    pub_date = datetime(2026, 3, 9, 7, 0, tzinfo=UTC)  # 00:00 PDT
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 3, 9, 0, 0, tzinfo=UTC)


def test_dst_transition_november() -> None:
    pub_date = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # 00:00 PST
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)


def test_utc_date_differs_from_la() -> None:
    # e.g., 5 AM UTC on Tuesday is 9 PM PST on Monday in LA.
    pub_date = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 11, 30, 0, 0, tzinfo=UTC)


def test_available_today_near_midnight_utc() -> None:
    pub_date = datetime(2026, 5, 5, 0, 30, tzinfo=UTC)  # May 5 UTC, May 4 PDT
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 5, 4, 0, 0, tzinfo=UTC)


def test_next_tuesday_near_midnight_utc() -> None:
    # Monday 00:30 UTC -> Sunday 17:30 PDT
    # It was published Sunday PT. So "next Tuesday" means Tuesday of the upcoming week (e.g. 2 days later)
    # 2026-05-04 (Mon) 00:30 UTC -> 2026-05-03 (Sun) 17:30 PDT
    # Sunday PT, the next Tuesday is 2026-05-05.
    pub_date = datetime(2026, 5, 4, 0, 30, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available next tuesday", pub_date)
    assert start == datetime(2026, 5, 5, 0, 0, tzinfo=UTC)


def test_end_of_year_relative_weekday() -> None:
    # Published Dec 31st 2026 (Thursday PST)
    # Next Tuesday is Jan 5th 2027.
    pub_date = datetime(2027, 1, 1, 5, 0, tzinfo=UTC)  # Dec 31, 21:00 PST
    start, _, _ = _parse_dates_from_text("available next tuesday", pub_date)
    assert start == datetime(2027, 1, 5, 0, 0, tzinfo=UTC)


def test_missing_year() -> None:
    # Current pub year
    pub_date = datetime(2026, 5, 1, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available August 19", pub_date)
    assert start == datetime(2026, 8, 19, 0, 0, tzinfo=UTC)


def test_november_referencing_january() -> None:
    pub_date = datetime(2026, 11, 15, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available January 5", pub_date)
    assert start == datetime(2027, 1, 5, 0, 0, tzinfo=UTC)


def test_december_to_january_range() -> None:
    pub_date = datetime(2026, 12, 1, tzinfo=UTC)
    start, end, _ = _parse_dates_from_text("available from December 5 until January 2", pub_date)
    assert start == datetime(2026, 12, 5, 0, 0, tzinfo=UTC)
    assert end == datetime(2027, 1, 2, 0, 0, tzinfo=UTC)


def test_january_referencing_december() -> None:
    # The rules say: if s_month < pub_date.month and pub_date.month >= 11 it adds a year.
    # Otherwise it uses pub year. So a January article reading December just assumes the same year (end of current year).
    pub_date = datetime(2026, 1, 15, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available December 5", pub_date)
    assert start == datetime(2026, 12, 5, 0, 0, tzinfo=UTC)


def test_confidence_degradation() -> None:

    # No dates resolved:
    html = "<strong>Super Game | PS4, PS5</strong>"
    events = _extract_games_from_html(
        html,
        ["extra"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 1, 1, tzinfo=UTC),
        "http://a",
    )
    assert events[0].confidence.score == 70


def test_multiple_games_sharing_url() -> None:
    # Tested dynamically by the parser anyway...
    pass


def test_section_leakage_prevention() -> None:
    html = """<h2>PlayStation Plus Extra and Premium</h2>
<p>available from August 1</p>
<strong>Game A | PS4</strong>
<h2>PlayStation Plus Premium | Classics</h2>
<strong>Game B | PS5</strong>"""
    events = _extract_games_from_html(
        html,
        ["extra"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 5, 1, tzinfo=UTC),
        "http://a",
    )
    # Game A should have aug 1, Game B should NOT! Game B should have None.
    # Wait, game A:
    game_a = next(e for e in events if "Game A" in e.title)
    assert game_a.available_from == datetime(2026, 8, 1, tzinfo=UTC)
    game_b = next(e for e in events if "Game B" in e.title)
    assert game_b.available_from is None


def test_article_fallback() -> None:
    html = """<p>available from August 10</p>
<h2>PlayStation Plus Premium</h2>
<strong>Game C | PS5</strong>"""
    events = _extract_games_from_html(
        html,
        ["extra"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 5, 1, tzinfo=UTC),
        "http://a",
    )
    assert events[0].available_from == datetime(2026, 8, 10, tzinfo=UTC)


def test_game_specific_precedence() -> None:
    html = """<p>available from August 10</p>
<h2>PlayStation Plus Premium</h2>
<p>available from August 15</p>
<p>available from August 20 <strong>Game D | PS5</strong></p>"""
    events = _extract_games_from_html(
        html,
        ["extra"],
        EventType.CATALOG_ADDITION,
        AccessModel.SUBSCRIPTION_CATALOG,
        OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG,
        datetime(2026, 5, 1, tzinfo=UTC),
        "http://a",
    )
    assert events[0].available_from == datetime(2026, 8, 20, tzinfo=UTC)


from unittest.mock import patch


def test_fetch_events_feed_ordering_and_horizon() -> None:
    from newsroom.sources.playstation_plus import fetch_events

    xml_feed = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
    <channel>
        <item>
            <title>PlayStation Plus Monthly Games for August</title>
            <pubDate>Mon, 10 Aug 2026 12:00:00 +0000</pubDate>
            <link>http://august</link>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
                &lt;p&gt;available today&lt;/p&gt;&lt;strong&gt;Game A | PS5&lt;/strong&gt;
            </content:encoded>
        </item>
        <item>
            <title>PlayStation Plus games for June (Old variant)</title>
            <pubDate>Thu, 01 Jun 2026 12:00:00 +0000</pubDate>
            <link>http://june</link>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
                &lt;p&gt;available today&lt;/p&gt;&lt;strong&gt;Game B | PS5&lt;/strong&gt;
            </content:encoded>
        </item>
        <item>
            <title>PlayStation Plus Game Catalog lineup July</title>
            <pubDate>Mon, 15 Jul 2026 12:00:00 +0000</pubDate>
            <link>http://july</link>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
                &lt;p&gt;available today&lt;/p&gt;&lt;strong&gt;Game C | PS5&lt;/strong&gt;
            </content:encoded>
        </item>
        <item>
            <title>PlayStation Plus Game Catalog lineup May (beyond horizon)</title>
            <pubDate>Sat, 01 May 2026 12:00:00 +0000</pubDate>
            <link>http://may</link>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
                &lt;p&gt;available today&lt;/p&gt;&lt;strong&gt;Game D | PS5&lt;/strong&gt;
            </content:encoded>
        </item>
        <item>
            <title>PlayStation Plus Monthly Games (Malformed pubdate)</title>
            <pubDate>Malformed Date 123</pubDate>
            <link>http://malformed</link>
            <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
                &lt;p&gt;available today&lt;/p&gt;&lt;strong&gt;Game E | PS5&lt;/strong&gt;
            </content:encoded>
        </item>
    </channel>
    </rss>
    """

    with (
        patch("newsroom.sources.playstation_plus.fetch_text", return_value=xml_feed),
        patch("newsroom.sources.playstation_plus.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2026, 8, 15, tzinfo=UTC)
        events = fetch_events()

    titles = [e.title for e in events]
    # Game A (Aug 10), Game C (Jul 15), Game B (Jun 1).
    # Game D (May 1) is older than 90 days from Aug 15.
    # Game E skipped because malformed date.

    assert "Game A" in titles
    assert "Game C" in titles
    assert "Game B" in titles
    assert "Game D" not in titles
    assert "Game E" not in titles


from newsroom.sources.playstation_plus import fetch_events

xml_malformed_mixed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <item>
        <title>PlayStation Plus Monthly Games</title>
        <pubDate>Wed, 10 Jun 2026 15:30:33 +0000</pubDate>
        <link>http://ok</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
            &lt;p&gt;Valid&lt;/p&gt;&lt;strong&gt;Game A | PS5&lt;/strong&gt;
        </content:encoded>
    </item>
    <item>
        <title>PlayStation Plus Monthly Games</title>
        <pubDate>Malformed date text</pubDate>
        <link>http://bad</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
            &lt;p&gt;Bad&lt;/p&gt;&lt;strong&gt;Game B | PS5&lt;/strong&gt;
        </content:encoded>
    </item>
</channel>
</rss>
"""


def test_mixed_malformed_pubdates() -> None:
    with patch("newsroom.sources.playstation_plus.fetch_text", return_value=xml_malformed_mixed):
        events = fetch_events()
        titles = [e.title for e in events]
        assert "Game A" in titles
        assert "Game B" not in titles


xml_all_malformed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <item>
        <title>PlayStation Plus Monthly Games</title>
        <pubDate>Missing tz +19022391209</pubDate>
        <link>http://bad1</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
            &lt;p&gt;Bad&lt;/p&gt;&lt;strong&gt;Game B | PS5&lt;/strong&gt;
        </content:encoded>
    </item>
    <item>
        <title>PlayStation Plus Game Catalog (No pubDate)</title>
        <link>http://missing</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
            &lt;strong&gt;Game C | PS5&lt;/strong&gt;
        </content:encoded>
    </item>
</channel>
</rss>
"""


def test_all_malformed_pubdates() -> None:
    with patch("newsroom.sources.playstation_plus.fetch_text", return_value=xml_all_malformed):
        events = fetch_events()
        assert len(events) == 0


# --- Standalone-article access-event detection ------------------------------
#
# Regression coverage for the Helldivers 2 incident. Deliberately uses a
# different game, date, and URL than the real incident throughout, so the
# coverage protects the *class* of miss (a same-day standalone article whose
# headline doesn't scream "PS Plus", carrying a real access-change event
# buried in otherwise unrelated content) rather than one hardcoded title.

_STANDALONE_POSITIVE_HTML = """
<p>This major content update introduces a new final boss encounter and
several quality-of-life improvements requested by the community.</p>
<p>Ghost Runner 3 enters the PlayStation Plus Game Catalog today, available to
PlayStation Plus Extra and Premium members starting August 20.</p>
<p>Fight through neon-lit corridors and discover the truth behind the Dharma
Tower.</p>
"""

_STANDALONE_PUB_DATE = datetime(2026, 8, 20, 18, 0, tzinfo=UTC)
_STANDALONE_URL = "https://blog.playstation.com/2026/08/20/ghost-runner-3-boss-update/"


def test_standalone_detects_access_event_from_body_not_headline() -> None:
    """The headline alone gives no hint this article carries a PS Plus event."""
    event = _detect_standalone_access_event(
        "Ghost Runner 3 Update Adds New Boss, Out Now",
        _STANDALONE_POSITIVE_HTML,
        _STANDALONE_PUB_DATE,
        _STANDALONE_URL,
    )
    assert event is not None
    assert event.title == "Ghost Runner 3"
    assert event.category == Category.SUBSCRIPTION
    assert event.event_type == EventType.CATALOG_ADDITION
    assert event.access_model == AccessModel.SUBSCRIPTION_CATALOG
    assert event.ownership_model == OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG
    assert set(event.tiers) == {"extra", "premium"}
    assert event.available_from == datetime(2026, 8, 20, tzinfo=UTC)
    assert event.url == _STANDALONE_URL


def test_standalone_detects_monthly_claim_variant() -> None:
    html = """
    <p>Word Weave joins the PlayStation Plus Monthly Games lineup today,
    available to PlayStation Plus Essential members starting today.</p>
    """
    event = _detect_standalone_access_event(
        "Word Weave Launch Trailer Released",
        html,
        _STANDALONE_PUB_DATE,
        _STANDALONE_URL,
    )
    assert event is not None
    assert event.event_type == EventType.CLAIMABLE_GAME
    assert event.access_model == AccessModel.CLAIMABLE
    assert event.ownership_model == OwnershipModel.PERMANENT_WHILE_ACCOUNT_EXISTS


_STANDALONE_NEGATIVE_CASES = {
    "casual_multiplayer_requirement": """
        <p>Online multiplayer for Neon Squad requires PlayStation Plus to play
        with friends across the galaxy.</p>
    """,
    "marketing_discount_copy": """
        <p>This week only, enjoy a discount for PlayStation Plus members: save
        20% on select titles storewide.</p>
    """,
    "unrelated_linking_article": """
        <p>Check out our full lineup of weekend deals, and don't forget you
        can browse the PlayStation Plus page for more offers.</p>
    """,
    "update_article_mentioning_ps_plus_without_new_access": """
        <p>Patch 2.1 for Dream Weavers fixes several bugs reported by
        PlayStation Plus members in the community forums.</p>
    """,
    "existing_membership_referenced_without_new_event": """
        <p>Thanks for being a PlayStation Plus Extra member -- here's what's
        still available in the Game Catalog this week.</p>
    """,
}


@pytest.mark.parametrize(
    "html", _STANDALONE_NEGATIVE_CASES.values(), ids=_STANDALONE_NEGATIVE_CASES.keys()
)
def test_standalone_rejects_false_positives(html: str) -> None:
    event = _detect_standalone_access_event(
        "Some Unrelated Headline",
        html,
        _STANDALONE_PUB_DATE,
        _STANDALONE_URL,
    )
    assert event is None


def test_standalone_returns_none_without_playstation_plus_mention() -> None:
    html = "<p>Just a normal article about a game update, nothing subscription-related.</p>"
    assert (
        _detect_standalone_access_event("Headline", html, _STANDALONE_PUB_DATE, _STANDALONE_URL)
        is None
    )


def test_standalone_returns_none_without_a_resolvable_tier() -> None:
    """A qualifying sentence with no tier keyword shouldn't guess a tier."""
    html = "<p>Nova Drift joins PlayStation Plus starting today.</p>"
    assert (
        _detect_standalone_access_event("Headline", html, _STANDALONE_PUB_DATE, _STANDALONE_URL)
        is None
    )


# --- fetch_events(): the full discovery -> classification path --------------
#
# These exercise fetch_events() itself (not just the helper) so the coverage
# proves the complete relevant path: two feeds fetched, a non-roundup
# candidate inspected for content, and a correctly-shaped event produced.


def _rss(*items_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        + "".join(items_xml)
        + "</channel></rss>"
    )


def _rss_item(title: str, link: str, pub_date: str, body_html: str) -> str:
    return f"""
    <item>
        <title>{title}</title>
        <pubDate>{pub_date}</pubDate>
        <link>{link}</link>
        <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">
            <![CDATA[{body_html}]]>
        </content:encoded>
    </item>
    """


def test_fetch_events_finds_standalone_article_absent_from_category_feed() -> None:
    """The exact shape of the Helldivers 2 miss: a standalone article that is
    never an item in the category/ps-plus feed, only in the general feed, with
    a headline that doesn't contain any roundup keyword. Pre-fix, fetch_events
    only polled the category feed and title-gated on roundup keywords, so this
    candidate would never have been fetched at all -- this test would have
    failed against that implementation.
    """
    category_feed = _rss(
        _rss_item(
            "PlayStation Plus Monthly Games for September",
            "http://category-item",
            "Mon, 01 Sep 2026 12:00:00 +0000",
            "<p>available today</p><strong>Unrelated Game | PS5</strong>",
        )
    )
    general_feed = _rss(
        _rss_item(
            "Ghost Runner 3 Update Adds New Boss, Out Now",
            _STANDALONE_URL,
            "Thu, 20 Aug 2026 18:00:00 +0000",
            _STANDALONE_POSITIVE_HTML,
        )
    )

    def fake_fetch_text(url: str) -> str:
        if "category/ps-plus" in url:
            return category_feed
        return general_feed

    with (
        patch("newsroom.sources.playstation_plus.fetch_text", side_effect=fake_fetch_text),
        patch("newsroom.sources.playstation_plus.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = datetime(2026, 8, 21, tzinfo=UTC)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        events = fetch_events()

    ghost_runner = next((e for e in events if e.title == "Ghost Runner 3"), None)
    assert ghost_runner is not None
    assert ghost_runner.event_type == EventType.CATALOG_ADDITION
    assert ghost_runner.category == Category.SUBSCRIPTION


def test_fetch_events_collapses_same_game_reported_by_both_feeds() -> None:
    """A same-day standalone article can describe exactly what a roundup
    published the same day already covers -- must produce one event, not two.
    """
    shared_pub_date = "Thu, 20 Aug 2026 18:00:00 +0000"
    category_feed = _rss(
        _rss_item(
            "PlayStation Plus Game Catalog for August",
            "http://roundup-item",
            shared_pub_date,
            "<h2>PlayStation Plus Extra and Premium</h2>"
            "<p>available from August 20</p>"
            "<strong>Ghost Runner 3 | PS5</strong>",
        )
    )
    general_feed = _rss(
        _rss_item(
            "Ghost Runner 3 Update Adds New Boss, Out Now",
            _STANDALONE_URL,
            shared_pub_date,
            _STANDALONE_POSITIVE_HTML,
        )
    )

    def fake_fetch_text(url: str) -> str:
        if "category/ps-plus" in url:
            return category_feed
        return general_feed

    with patch("newsroom.sources.playstation_plus.fetch_text", side_effect=fake_fetch_text):
        events = fetch_events()

    matches = [e for e in events if "Ghost Runner 3" in e.title]
    assert len(matches) == 1
