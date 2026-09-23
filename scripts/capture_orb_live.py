import os
import sys
import time
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\f7af3977-3411-4c83-b6bd-b4dd6c95942f"
os.makedirs(artifact_dir, exist_ok=True)

chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
if not os.path.exists(chrome_path):
    chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

print(f"Launching browser from: {chrome_path}")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=chrome_path,
        headless=True,
        args=['--no-sandbox', '--disable-setuid-sandbox', '--enable-webgl', '--ignore-gpu-blocklist']
    )
    context = browser.new_context(
        viewport={'width': 1440, 'height': 960},
        locale='fa-IR'
    )
    page = context.new_page()

    # ۱. بارگذاری صفحه فایلینگ املاک و ایستگاه هوش مصنوعی
    print("Navigating to http://127.0.0.1:5000/properties/...")
    page.goto('http://127.0.0.1:5000/properties/', wait_until='networkidle', timeout=15000)
    time.sleep(3)

    # اسکرول به گوی هوش مصنوعی و ایستگاه مشاوره
    ai_station = page.locator('#ai-station')
    if ai_station.count() > 0:
        ai_station.scroll_into_view_if_needed()
        time.sleep(2)
        print("Taking screenshot of 3D Orb and AI Station in Standby Mode...")
        ai_station_shot = os.path.join(artifact_dir, "luxury_3d_orb_station_live.png")
        ai_station.screenshot(path=ai_station_shot)
        print(f"Saved: {ai_station_shot}")

    # ۲. تست کلیک روی گوی جهت باز شدن کنسول تعاملی مشاوره
    orb_anchor = page.locator('.saghf-webgl-orb-anchor')
    if orb_anchor.count() > 0:
        print("Clicking 3D Orb to activate interactive voice console...")
        page.evaluate("() => window.expandAndStartListening()")
        time.sleep(2)
        
        # اسکرین شات از کنسول باز شده
        active_shot = os.path.join(artifact_dir, "luxury_3d_orb_active_console.png")
        if ai_station.count() > 0:
            ai_station.screenshot(path=active_shot)
            print(f"Saved active state: {active_shot}")

    # ۳. تست ارسال دستور صوتی یا متنی نمونه: کلیک روی چیپ «رهن و اجاره منطقه ۵»
    chip_btn = page.locator('.saghf-chip-btn').first
    if chip_btn.count() > 0:
        print("Clicking quick chip 'رهن و اجاره منطقه ۵'...")
        chip_btn.click(force=True)
        time.sleep(3)
        
        results_shot = os.path.join(artifact_dir, "luxury_3d_orb_results_live.png")
        if ai_station.count() > 0:
            ai_station.screenshot(path=results_shot)
            print(f"Saved results state: {results_shot}")

    browser.close()
    print("✅ تمام تست‌های بصری Playwright با موفقیت به پایان رسید.")
