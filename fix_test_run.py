with open('newsroom/tests/test_run.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('events = cli._fetch_all_sources([])', 'events, _ = cli._fetch_all_sources([])')
text = text.replace('events = cli._fetch_all_sources(["two"])', 'events, _ = cli._fetch_all_sources(["two"])')
with open('newsroom/tests/test_run.py', 'w', encoding='utf-8') as f: f.write(text)
