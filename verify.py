import sys
sys.path.append('newsroom')
from newsroom.cli import run_pipeline
from newsroom.webapp import get_state

run_pipeline(selected=['playstation_plus'], persist=True)

state = get_state()
events = [e for e in state['giveaways'] if e['source'] == 'playstation_plus']
print('Events emitted:', len(events))
if events:
    print('Newest current event:', events[0]['title'])
    print('Dashboard first PlayStation rows:')
    for i, e in enumerate(events[:5]):
        print(f"{i+1}. {e['title']} ({e['available_from']})")
