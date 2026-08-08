
with open('newsroom/webapp.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """def _sort_key_event(event: NewsEvent, now: datetime) -> tuple[int, float, str, str]:
    \"\"\"Sort key for dashboard display.
    
    1. bucket: 0 for current/upcoming, 1 for historical/expired
    2. newest availability date (descending, so negated timestamp)
    3. source as tie-breaker
    4. title as tie-breaker
    \"\"\"
    is_expired = event.is_expired()
    bucket = 1 if is_expired else 0
    
    ts = 0.0
    if event.available_from:
        dt = event.available_from
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        ts = dt.timestamp()
        
    return (bucket, -ts, event.source.value, (event.title or \"\").lower())"""

replacement = """def _sort_key_event(event: NewsEvent, now: datetime) -> tuple[int, float, str, str]:
    \"\"\"Sort key for dashboard display.
    
    1. bucket: 0 for current/upcoming, 1 for historical/expired
    2. newest availability date (descending, so negated timestamp)
    3. source as tie-breaker
    4. title as tie-breaker
    \"\"\"
    is_expired = event.is_expired()
    bucket = 1 if is_expired else 0
    
    ts = 0.0
    start_dt = event.available_from or event.promotion_start
    if start_dt:
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=UTC)
        ts = start_dt.timestamp()
        
    return (bucket, -ts, event.source.value, (event.title or \"\").lower())"""

text = text.replace(target, replacement)
with open('newsroom/webapp.py', 'w', encoding='utf-8') as f:
    f.write(text)
