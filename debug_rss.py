import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from newsroom.sources._http import fetch_text
from newsroom.sources.playstation_plus import US_BLOG_FEED

import email.utils

try:
    xml_text = fetch_text(US_BLOG_FEED)
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    print(f"Total items in feed: {len(items)}")
    
    for i, item in enumerate(items):
        title_el = item.find("title")
        title = title_el.text if title_el is not None else "NO_TITLE"
        
        link_el = item.find("link")
        link = link_el.text if link_el is not None else "NO_LINK"
        
        pubDate_el = item.find("pubDate")
        raw_pub = pubDate_el.text if pubDate_el is not None else "NO_PUBDATE"
        
        parsed = None
        if raw_pub != "NO_PUBDATE":
            try:
                parsed_dt = email.utils.parsedate_to_datetime(raw_pub)
                if parsed_dt:
                    parsed = parsed_dt.astimezone(UTC)
            except Exception:
                pass
                
        is_monthly = "Monthly Games" in title
        is_catalog = "Game Catalog" in title
        matched = is_monthly or is_catalog
        
        print(f"Position: {i}")
        print(f"Title: {title}")
        print(f"URL: {link}")
        print(f"Raw pubDate: {raw_pub}")
        print(f"Parsed pubDate: {parsed}")
        print(f"Title matched: {'yes' if matched else 'no'}")
        print("-" * 40)
        
except Exception as e:
    print(f"Failed: {e}")
