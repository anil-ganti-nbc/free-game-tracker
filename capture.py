import os
os.environ['HOME'] = os.environ.get('USERPROFILE', 'C:\\Users\\anil')

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    
    # Track JS errors
    errors = []
    page.on("pageerror", lambda err: errors.append(err))
    
    page.goto('http://127.0.0.1:8765')
    time.sleep(2)  # Wait for JS to render
    
    print("JS Errors:", errors)
    
    # Take full dashboard screenshot
    page.screenshot(path='dashboard_full.png', full_page=True)
    
    # Move slider to MIN
    range_input = page.locator('#days')
    # Focus and set value
    range_input.evaluate('el => { el.value = 1; el.dispatchEvent(new Event("input")); }')
    time.sleep(1)
    page.screenshot(path='slider_min.png', full_page=True)
    
    # Move slider to MID
    range_input.evaluate('el => { el.value = 7; el.dispatchEvent(new Event("input")); }')
    time.sleep(1)
    page.screenshot(path='slider_mid.png', full_page=True)
    
    # Move slider to MAX
    range_input.evaluate('el => { el.value = 14; el.dispatchEvent(new Event("input")); }')
    time.sleep(1)
    page.screenshot(path='slider_max.png', full_page=True)
    
    browser.close()
