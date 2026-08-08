import json
data = json.load(open('debug.json'))
for item in data:
    title = item['title'][:40]
    print(f"[{item['pos']}] {title} ... {item['pub']}")
