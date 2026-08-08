import sys
sys.path.append('newsroom')
from newsroom.sources.playstation_plus import fetch_events
from newsroom.quality import passes_quality_gate

events = fetch_events()
print('Total extracted:', len(events))
for e in events:
    passed = passes_quality_gate(e, min_confidence=75, require_known_price=False)
    print(f"{e.title[:30]} | {e.available_from} | pass={passed}")
