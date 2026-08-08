import os
os.environ['HOME'] = os.environ.get('USERPROFILE', 'C:\\Users\\anil')

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('http://127.0.0.1:8765')
    time.sleep(2)  # Wait for JS to render
    
    html = page.content()
    
    with open('rendered.html', 'w', encoding='utf-8') as f:
        f.write(html)
        
    browser.close()
