import pytest
from datetime import datetime, UTC
from unittest.mock import patch
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

def test_mixed_malformed_pubdates():
    with patch('newsroom.sources.playstation_plus.fetch_text', return_value=xml_malformed_mixed):
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

def test_all_malformed_pubdates():
    with patch('newsroom.sources.playstation_plus.fetch_text', return_value=xml_all_malformed):
        events = fetch_events()
        assert len(events) == 0

