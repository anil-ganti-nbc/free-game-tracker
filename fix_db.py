with open('newsroom/database.py', 'r', encoding='utf-8') as f:
    text = f.read()

s = text.rfind('def _apply_update(row: NewsEventRow, event: NewsEvent) -> None:\n    # helper for updates')
if s != -1:
    clean = text[:s]
else:
    clean = text

sync_code = '''
def sync_events(events: list[NewsEvent], successful_sources: set[str] | None = None) -> None:
    """Reconcile the stored snapshot with this run's events."""
    current_keys = {event.event_key for event in events}
    with session_scope() as session:
        existing_by_key = {
            row.event_key: row for row in session.scalars(select(NewsEventRow)).all()
        }

        # Remove offers that are no longer live.
        for key, row in existing_by_key.items():
            if successful_sources is not None and row.source not in successful_sources:
                continue
            if key not in current_keys:
                session.delete(row)

        # Insert or refresh live offers.
        for event in events:
            existing = existing_by_key.get(event.event_key)
            if existing is None:
                session.add(to_row(event))
            else:
                _apply_update(existing, event)
'''
with open('newsroom/database.py', 'w', encoding='utf-8') as f:
    f.write(clean + sync_code)
