with open('newsroom/sources/playstation_plus.py', 'r') as f:
    text = f.read()

text = text.replace('from typing import Any', 'from typing import Any\nfrom zoneinfo import ZoneInfo\n\nPLAYSTATION_BLOG_TZ = ZoneInfo("America/Los_Angeles")')

old_today = """    if "available today" in text_lower:
        start = datetime(pub_date.year, pub_date.month, pub_date.day, tzinfo=UTC)
        phrase = "available today\""""

new_today = """    if "available today" in text_lower:
        pub_pt = pub_date.astimezone(PLAYSTATION_BLOG_TZ)
        start = datetime(pub_pt.year, pub_pt.month, pub_pt.day, tzinfo=UTC)
        phrase = "available today\""""
text = text.replace(old_today, new_today)

old_tuesday = """    elif "available next tuesday" in text_lower:
        # PlayStation Blog uses US Pacific time. Approximate with UTC-8 for weekday boundaries.
        pub_pt = pub_date - timedelta(hours=8)
        days_ahead = 1 - pub_pt.weekday()
        if days_ahead <= 0:
             days_ahead += 7
        target_pt = pub_pt + timedelta(days=days_ahead)
        start = datetime(target_pt.year, target_pt.month, target_pt.day, tzinfo=UTC)
        phrase = "available next tuesday\""""

new_tuesday = """    elif "available next tuesday" in text_lower:
        pub_pt = pub_date.astimezone(PLAYSTATION_BLOG_TZ)
        days_ahead = 1 - pub_pt.weekday()
        if days_ahead <= 0:
             days_ahead += 7
        target_pt = pub_pt + timedelta(days=days_ahead)
        start = datetime(target_pt.year, target_pt.month, target_pt.day, tzinfo=UTC)
        phrase = "available next tuesday\""""

text = text.replace(old_tuesday, new_tuesday)

with open('newsroom/sources/playstation_plus.py', 'w') as f:
    f.write(text)
