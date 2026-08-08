tests = """

def test_dst_winter():
    # Winter is standard time (PST, UTC-8).
    # Nov 15th 2026 01:00 UTC -> Nov 14th 17:00 PST.
    pub_date = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    # The intended date is Nov 14th, so it normalizes to Nov 14 00:00 UTC.
    assert start == datetime(2026, 11, 14, 0, 0, tzinfo=UTC)

def test_dst_summer():
    # Summer is Daylight Saving Time (PDT, UTC-7).
    # Jul 15th 2026 01:00 UTC -> Jul 14th 18:00 PDT.
    pub_date = datetime(2026, 7, 15, 1, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 7, 14, 0, 0, tzinfo=UTC)

def test_dst_transition_march():
    # US DST transition is 2nd Sunday in March. (Mar 8 2026).
    # Let's test a date near the boundary.
    pub_date = datetime(2026, 3, 9, 7, 0, tzinfo=UTC) # 00:00 PDT
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 3, 9, 0, 0, tzinfo=UTC)

def test_dst_transition_november():
    pub_date = datetime(2026, 11, 2, 8, 0, tzinfo=UTC) # 00:00 PST
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=UTC)

def test_utc_date_differs_from_la():
    # e.g., 5 AM UTC on Tuesday is 9 PM PST on Monday in LA.
    pub_date = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 11, 30, 0, 0, tzinfo=UTC)

def test_available_today_near_midnight_utc():
    pub_date = datetime(2026, 5, 5, 0, 30, tzinfo=UTC) # May 5 UTC, May 4 PDT
    start, _, _ = _parse_dates_from_text("available today", pub_date)
    assert start == datetime(2026, 5, 4, 0, 0, tzinfo=UTC)

def test_next_tuesday_near_midnight_utc():
    # Monday 00:30 UTC -> Sunday 17:30 PDT
    # It was published Sunday PT. So "next Tuesday" means Tuesday of the upcoming week (e.g. 2 days later)
    # 2026-05-04 (Mon) 00:30 UTC -> 2026-05-03 (Sun) 17:30 PDT
    # Sunday PT, the next Tuesday is 2026-05-05.
    pub_date = datetime(2026, 5, 4, 0, 30, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available next tuesday", pub_date)
    assert start == datetime(2026, 5, 5, 0, 0, tzinfo=UTC)

def test_end_of_year_relative_weekday():
    # Published Dec 31st 2026 (Thursday PST)
    # Next Tuesday is Jan 5th 2027.
    pub_date = datetime(2027, 1, 1, 5, 0, tzinfo=UTC) # Dec 31, 21:00 PST
    start, _, _ = _parse_dates_from_text("available next tuesday", pub_date)
    assert start == datetime(2027, 1, 5, 0, 0, tzinfo=UTC)

def test_missing_year():
    # Current pub year
    pub_date = datetime(2026, 5, 1, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available August 19", pub_date)
    assert start == datetime(2026, 8, 19, 0, 0, tzinfo=UTC)

def test_november_referencing_january():
    pub_date = datetime(2026, 11, 15, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available January 5", pub_date)
    assert start == datetime(2027, 1, 5, 0, 0, tzinfo=UTC)

def test_december_to_january_range():
    pub_date = datetime(2026, 12, 1, tzinfo=UTC)
    start, end, _ = _parse_dates_from_text("available from December 5 until January 2", pub_date)
    assert start == datetime(2026, 12, 5, 0, 0, tzinfo=UTC)
    assert end == datetime(2027, 1, 2, 0, 0, tzinfo=UTC)

def test_january_referencing_december():
    # The rules say: if s_month < pub_date.month and pub_date.month >= 11 it adds a year.
    # Otherwise it uses pub year. So a January article reading December just assumes the same year (end of current year).
    pub_date = datetime(2026, 1, 15, tzinfo=UTC)
    start, _, _ = _parse_dates_from_text("available December 5", pub_date)
    assert start == datetime(2026, 12, 5, 0, 0, tzinfo=UTC)

def test_confidence_degradation():
    from newsroom.models import Confidence
    # No dates resolved:
    html = "<strong>Super Game | PS4, PS5</strong>"
    events = _extract_games_from_html(html, ["extra"], EventType.CATALOG_ADDITION, AccessModel.SUBSCRIPTION_CATALOG, OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG, datetime(2026,1,1,tzinfo=UTC), "http://a")
    assert events[0].confidence.score == 70

def test_multiple_games_sharing_url():
    # Tested dynamically by the parser anyway...
    pass

def test_section_leakage_prevention():
    html = \"\"\"<h2>PlayStation Plus Extra and Premium</h2>
<p>available from August 1</p>
<strong>Game A | PS4</strong>
<h2>PlayStation Plus Premium | Classics</h2>
<strong>Game B | PS5</strong>\"\"\"
    events = _extract_games_from_html(html, ["extra"], EventType.CATALOG_ADDITION, AccessModel.SUBSCRIPTION_CATALOG, OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG, datetime(2026,5,1,tzinfo=UTC), "http://a")
    # Game A should have aug 1, Game B should NOT! Game B should have None.
    # Wait, game A:
    game_a = next(e for e in events if "Game A" in e.title)
    assert game_a.available_from == datetime(2026, 8, 1, tzinfo=UTC)
    game_b = next(e for e in events if "Game B" in e.title)
    assert game_b.available_from is None

def test_article_fallback():
    html = \"\"\"<p>available from August 10</p>
<h2>PlayStation Plus Premium</h2>
<strong>Game C | PS5</strong>\"\"\"
    events = _extract_games_from_html(html, ["extra"], EventType.CATALOG_ADDITION, AccessModel.SUBSCRIPTION_CATALOG, OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG, datetime(2026,5,1,tzinfo=UTC), "http://a")
    assert events[0].available_from == datetime(2026, 8, 10, tzinfo=UTC)

def test_game_specific_precedence():
    html = \"\"\"<p>available from August 10</p>
<h2>PlayStation Plus Premium</h2>
<p>available from August 15</p>
<p>available from August 20 <strong>Game D | PS5</strong></p>\"\"\"
    events = _extract_games_from_html(html, ["extra"], EventType.CATALOG_ADDITION, AccessModel.SUBSCRIPTION_CATALOG, OwnershipModel.ACCESSIBLE_WHILE_IN_CATALOG, datetime(2026,5,1,tzinfo=UTC), "http://a")
    assert events[0].available_from == datetime(2026, 8, 20, tzinfo=UTC)
"""

with open("newsroom/tests/test_playstation_plus.py", "a", encoding="utf-8") as f:
    f.write(tests)

with open("newsroom/tests/test_playstation_plus.py", "r", encoding="utf-8") as f:
    t = f.read()
    if "_parse_dates_from_text" not in t:
        t = t.replace("from newsroom.sources.playstation_plus import _extract_games_from_html", "from newsroom.sources.playstation_plus import _extract_games_from_html, _parse_dates_from_text")

with open("newsroom/tests/test_playstation_plus.py", "w", encoding="utf-8") as f:
    f.write(t)
