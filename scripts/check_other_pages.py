import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

artifacts_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 844})

    # Dashboard
    page.goto('http://127.0.0.1:5000/dashboard/', wait_until='networkidle')
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(artifacts_dir, "mobile_10_dashboard.png"))

    # Live Monitor
    page.goto('http://127.0.0.1:5000/crawler/live', wait_until='networkidle')
    page.wait_for_timeout(500)
    page.screenshot(path=os.path.join(artifacts_dir, "mobile_11_crawler_live.png"))

    browser.close()
    print("Dashboard and Crawler Live screenshots taken!")
