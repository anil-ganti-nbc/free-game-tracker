from unittest.mock import patch

def test_fetch_events_feed_ordering_and_horizon():
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
    
    with patch('newsroom.sources.playstation_plus.fetch_text', return_value=xml_feed), \\
         patch('newsroom.sources.playstation_plus.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 15, tzinfo=UTC)
        events = fetch_events()
        
    titles = [e.title for e in events]
    # Game A (Aug 10), Game C (Jul 15), Game B (Jun 1).
    # Game D (May 1) is older than 90 days from Aug 15.
    # Game E skipped because malformed date.
    
    assert "Game A " in titles
    assert "Game C " in titles
    assert "Game B " in titles
    assert "Game D " not in titles
    assert "Game E " not in titles
