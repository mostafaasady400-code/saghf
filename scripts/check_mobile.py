import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.goto('http://127.0.0.1:5000/properties/', wait_until='networkidle')
    artifacts = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
    
    # 1. AI Station resting
    page.locator("#ai-station").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(artifacts, "mobile_ai_station_resting.png"), timeout=5000)
    
    # 2. AI Station active
    page.locator("#restingOrbBtn").click()
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(artifacts, "mobile_ai_station_active.png"), timeout=5000)
    
    # 3. Catalog section
    page.locator("#properties-catalog-section").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(artifacts, "mobile_catalog_section.png"), timeout=5000)

    # 4. Property card
    cards = page.locator(".property-card")
    if cards.count() > 0:
        cards.first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(artifacts, "mobile_property_card.png"), timeout=5000)
        
    browser.close()
    print("Screenshots captured!")
