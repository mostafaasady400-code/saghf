import time
import os
from playwright.sync_api import sync_playwright

artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\ae6d95ef-305d-4bff-b1ca-7fcce2ce91f2"
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome_path, headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})

    # 1. Properties List
    page.goto('http://127.0.0.1:5000/properties/', wait_until='networkidle')
    time.sleep(1)

    # 2. Click Divar Connect
    page.locator("button:has-text('اتصال حساب دیوار')").first.click()
    time.sleep(1)
    page.screenshot(path=os.path.join(artifact_dir, 'live_test_6_divar_auth_modal.png'))
    print('Saved live_test_6_divar_auth_modal.png')
    page.locator("button[onclick=\"closeModal('divarSessionModal')\"]").click()
    time.sleep(0.5)

    # 3. Click Register Phone
    page.locator("button:has-text('ثبت شماره')").first.click()
    time.sleep(1)
    page.screenshot(path=os.path.join(artifact_dir, 'live_test_7_quick_phone_modal.png'))
    print('Saved live_test_7_quick_phone_modal.png')
    page.locator("button[onclick=\"closeModal('quickPhoneModal')\"]").click()
    time.sleep(0.5)

    # 4. Screenshot full properties page showing real phone
    page.screenshot(path=os.path.join(artifact_dir, 'live_test_9_properties_with_real_phone.png'), full_page=True)
    print('Saved live_test_9_properties_with_real_phone.png')

    browser.close()
print('Done capturing modals and pages!')

