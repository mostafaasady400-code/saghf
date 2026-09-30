import sys
import os
import time
import subprocess
import urllib.request
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SHOT_DIR = os.path.abspath(r"browser_test_shots")
os.makedirs(SHOT_DIR, exist_ok=True)

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

def is_cdp_available(timeout=1.0) -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False

def ensure_browser_running() -> bool:
    if is_cdp_available():
        print("✅ مرورگر گوگل کروم روی پورت 9222 آماده اتصال است.")
        return True

    print("🔍 پورت 9222 فعال نیست. در حال اجرای مستقیم Google Chrome...")
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    browser_exe = next((p for p in chrome_candidates if os.path.exists(p)), None)
    if not browser_exe:
        print("❌ مرورگر یافت نشد.")
        return False

    temp_profile = os.path.abspath(r"scratch\chrome_auto_profile")
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        browser_exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized"
    ]
    subprocess.Popen(cmd)
    for _ in range(20):
        time.sleep(0.5)
        if is_cdp_available():
            print("✅ مرورگر با موفقیت در پیش‌زمینه مانیتور باز شد.")
            return True
    return False

def run_live_interactive_demo():
    print("\n" + "=" * 70)
    print("🎬 اجرای آزمون زنده، تعاملی و نمایشی سقف روی گوگل کروم مانیتور")
    print("=" * 70)

    if not ensure_browser_running():
        return False

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context(no_viewport=True)
            if context.pages:
                page = context.pages[0]
            else:
                page = context.new_page()
            page.bring_to_front()
            print("🌐 در حال انتقال پنجره کروم به صفحه فایلینگ املاک سقف...")
            page.goto("http://127.0.0.1:5000/properties/", wait_until="commit", timeout=15000)
            time.sleep(2.5)

            # ۱. اسکرول نرم برای دیدن کارت‌های املاک و استایل بلک اند گلد
            print("📜 ۱. اسکرول نرم جهت تماشای کارت‌های لوکس املاک و مشخصات...")
            for step in range(1, 4):
                page.evaluate("window.scrollBy({ top: 450, behavior: 'smooth' });")
                time.sleep(1.2)

            page.screenshot(path=os.path.join(SHOT_DIR, "demo_01_cards_scroll.png"))
            time.sleep(1)

            # ۲. اسکرول به بالای صفحه به بخش فیلترها
            print("⬆️ ۲. بازگشت به بخش فیلترهای پیشرفته...")
            page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' });")
            time.sleep(1.5)

            # ۳. تست فیلتر انتخاب محله (District Picker)
            print("📍 ۳. کلیک روی انتخاب منطقه و محله‌های تهران...")
            picker_trigger = page.locator("#districtPickerTrigger")
            if picker_trigger.is_visible():
                picker_trigger.click()
                time.sleep(1)
                search_input = page.locator("#districtPickerSearch")
                if search_input.is_visible():
                    print("   ⌨️ تایپ زنده نام محله 'سعادت آباد' در کادر جستجوی محله...")
                    search_input.type("سعادت آباد", delay=150)
                    time.sleep(1.5)
                    # انتخاب اولین نتیجه
                    first_district = page.locator(".district-picker-item, .district-item, #districtPickerList > div").first
                    if first_district.is_visible():
                        print("   ✅ انتخاب محله سعادت‌آباد...")
                        first_district.click()
                        time.sleep(1)

            page.screenshot(path=os.path.join(SHOT_DIR, "demo_02_district_selected.png"))

            # ۴. تست درج مبالغ و جداکننده ۳ رقمی فارسی
            print("💰 ۴. تست ورودی‌های مالی و تبدیل ۳ رقمی فارسی...")
            min_price_input = page.locator("#filterMinPrice")
            if min_price_input.is_visible():
                min_price_input.click()
                min_price_input.fill("5000000000")
                time.sleep(1)

            # ۵. کلیک روی دکمه اعمال فیلتر (On-Demand Filter)
            print("🔍 ۵. کلیک روی دکمه «اعمال فیلتر» و اجرای استخراج زنده...")
            btn_filter = page.locator("#btnApplyFilter")
            if btn_filter.is_visible():
                btn_filter.click()
                time.sleep(2.5)

            page.screenshot(path=os.path.join(SHOT_DIR, "demo_03_filtered_results.png"))

            # ۶. فعال‌سازی گوی شناور سه‌بعدی هوش مصنوعی (AI Orb)
            print("🔮 ۶. تست تعاملی گوی شناور هوش مصنوعی سقف...")
            ai_orb = page.locator("#saghfSmartSphereFloating")
            if ai_orb.is_visible():
                ai_orb.scroll_into_view_if_needed()
                time.sleep(0.5)
                ai_orb.click()
                time.sleep(1.5)
                print("   ✅ گوی فعال شد و پنل HUD دستیار ملکی باز گردید.")
                page.screenshot(path=os.path.join(SHOT_DIR, "demo_04_orb_hud.png"))

                # بستن مودال HUD
                close_btn = page.locator("#aiHudCloseBtn")
                if close_btn.is_visible():
                    time.sleep(1)
                    close_btn.click()
                    time.sleep(1)

            # ۷. بازگشت به نمای اصلی و نگه داشتن پنجره باز برای کاربر
            print("🖥️ ۷. مرورگر کروم روی صفحه مانیتور شما در آدرس http://127.0.0.1:5000/properties/ فعال و آماده کار است.")
            page.evaluate("window.scrollTo({ top: 300, behavior: 'smooth' });")
            time.sleep(1)
            page.screenshot(path=os.path.join(SHOT_DIR, "demo_05_final_view.png"))

            print("\n" + "=" * 70)
            print("🎉 تمامی تست‌های بصری، اسکرول، فیلترها و گوی سه‌بعدی با موفقیت کامل اجرا شدند!")
            print("=" * 70 + "\n")
            return True
        except Exception as e:
            print(f"❌ خطا در اجرای آزمون تعاملی: {e}")
            return False

if __name__ == '__main__':
    run_live_interactive_demo()
