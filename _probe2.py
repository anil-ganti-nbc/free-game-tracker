from newsroom.sources.geforce_now import _extract_game_title, _extract_storefronts, _parse_feed

_CONTENT_NS = 'xmlns:content="http://purl.org/rss/1.0/modules/content/"'

def _rss(title="GFN Thursday: New Games", body=""):
    escaped = body.replace("]]>", "]]]]><![CDATA[>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<rss version="2.0" {_CONTENT_NS}><channel><item>'
        f'<title>{title}</title>'
        '<pubDate>Thu, 05 Aug 2026 14:00:00 +0000</pubDate>'
        '<link>https://blogs.nvidia.com/gfn/</link>'
        f'<content:encoded><![CDATA[{escaped}]]></content:encoded>'
        '</item></channel></rss>'
    )

print("P5 DLCS substring:", len(_parse_feed(_rss(body='<ul><li><em>Game Title</em> (EA App, DLCS mode)</li></ul>'))))
print("P6 leaving in title false positive:", len(_parse_feed(_rss(body='<ul><li><em>Leaving Las Vegas</em> (Steam)</li></ul>'))))
print("P7 free weekend in title false positive:", len(_parse_feed(_rss(body='<ul><li><em>Free Weekend Edition Game</em> (Steam)</li></ul>'))))
print("P8 removed from in title false positive:", len(_parse_feed(_rss(body='<ul><li><em>Removed From Existence</em> (Steam)</li></ul>'))))
print("P10 unclosed paren:", len(_parse_feed(_rss(body='<ul><li><em>Game Without Close</em> (Steam</li></ul>'))))
events = _parse_feed(_rss(body='<ul><li>Header<ul><li><em>Inner Game</em> (Steam)</li></ul></li></ul>'))
print(f"P11 nested list expected 1: {len(events)}, titles: {[e.title for e in events]}")

try:
    _parse_feed("garbage")
    print("P16 parse error: did not raise exception (returned silently)")
except Exception as e:
    print(f"P16 parse error raised: {type(e).__name__}")
