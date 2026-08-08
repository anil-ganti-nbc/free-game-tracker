import logging, sys; logging.basicConfig(level=logging.DEBUG, stream=sys.stderr); from newsroom.sources.geforce_now import fetch_events; events = fetch_events(); print(f'Got {len(events)} events')
