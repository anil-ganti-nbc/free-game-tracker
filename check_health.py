import urllib.request, json
try:
    resp = urllib.request.urlopen('http://127.0.0.1:8765/api/state')
    data = json.loads(resp.read().decode('utf-8'))
    for h in data['health']:
        print(f"{h['source']}: {h['status']} - {h.get('error', '')}")
except Exception as e:
    print('Error:', e)
