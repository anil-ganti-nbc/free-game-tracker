import json
from collections import Counter
from newsroom.sources import xbox_game_pass
events = xbox_game_pass.fetch_events()
post_stats = {}
for ev in events:
    title = ev.url
    if title not in post_stats:
        post_stats[title] = {"additions": 0, "departures": 0, "titles": []}
    if "REMOVAL" in str(ev.event_type):
        post_stats[title]["departures"] += 1
        post_stats[title]["titles"].append(f"(DEP) {ev.title}")
    else:
        post_stats[title]["additions"] += 1

print(json.dumps(post_stats, indent=2))
