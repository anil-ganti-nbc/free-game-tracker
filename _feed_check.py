import traceback
import xml.etree.ElementTree as ET
from newsroom.sources._http import fetch_text, SourceError

try:
    feed = fetch_text('https://blogs.nvidia.com/category/geforce-now/feed/')
    root = ET.fromstring(feed)
    items = [i.find('title').text for i in root.findall('.//item') if i.find('title') is not None]
    print(f'Total items: {len(items)}')
    print('Titles:')
    for t in items:
        print(f'- {t}')
except SourceError as e:
    print(f"SourceError: {e}")
except Exception as e:
    traceback.print_exc()
