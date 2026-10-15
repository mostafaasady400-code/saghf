import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.goto('http://127.0.0.1:5000/properties/?lifecycle=all', wait_until='networkidle')
    artifacts = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
    
    # 1. Scroll to filters form
    filter_form = page.locator("#propertiesFilterForm")
    filter_form.scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    page.screenshot(path=os.path.join(artifacts, "mobile_8_filters_form.png"))

    # 2. Scroll to visible property cards
    cards = page.locator(".compact-property-card:visible")
    if cards.count() > 0:
        cards.first.scroll_into_view_if_needed()
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(artifacts, "mobile_9_property_card.png"))
    
    browser.close()
    print("Screenshots taken successfully!")
