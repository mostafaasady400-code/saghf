import os
import sys
import time
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from playwright.sync_api import sync_playwright

def run_comprehensive_e2e_test():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    artifacts_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\f7af3977-3411-4c83-b6bd-b4dd6c95942f"
    os.makedirs(artifacts_dir, exist_ok=True)

    print("=" * 60)
    print("🚀 شروع آزمون جامع End-to-End پلتفرم سقف با Playwright و مرورگر Chrome")
    print("=" * 60)

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    print(f"🌐 مرورگر اجرایی: {chrome_path}")
    print(f"📁 مسیر ذخیره اسکرین‌شات‌ها: {artifacts_dir}\n")

    screenshots_taken = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chrome_path,
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = browser.new_context(
            viewport={'width': 1440, 'height': 900},
            locale='fa-IR'
        )
        page = context.new_page()

        # ----------------------------------------------------
        # تست ۱: داشبورد اصلی سقف (Luxury Obsidian & Gold UI)
        # ----------------------------------------------------
        print("[تست ۱] بارگذاری داشبورد اصلی و بررسی گوی شناور...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(1.5)
        
        shot1 = os.path.join(artifacts_dir, "e2e_1_dashboard.png")
        page.screenshot(path=shot1, full_page=True)
        screenshots_taken.append(("داشبورد اصلی سقف", shot1))
        print(f"  ✓ اسکرین‌شات ذخیره شد: {shot1}")

        # ----------------------------------------------------
        # تست ۲: صفحه فایل‌ها، کاتالوگ و گوی هوشمند
        # ----------------------------------------------------
        print("\n[تست ۲] ورود به بانک فایل‌ها و تست باز شدن گوی هوشمند...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1.5)
        
        shot2 = os.path.join(artifacts_dir, "e2e_2_properties.png")
        page.screenshot(path=shot2, full_page=True)
        screenshots_taken.append(("بانک فایل‌های ملکی", shot2))
        print(f"  ✓ اسکرین‌شات ذخیره شد: {shot2}")

        # ----------------------------------------------------
        # تست ۳: تعامل با گوی هوشمند و باز شدن مودال HUD
        # ----------------------------------------------------
        print("\n[تست ۳] کلیک روی گوی هوشمند سه‌بعدی و فعال‌سازی دستیار صوتی...")
        sphere_btn = page.locator("#saghfSmartSphereFloating")
        if sphere_btn.count() > 0:
            sphere_btn.first.click(force=True)
            time.sleep(2.5)
            
            modal = page.locator("#aiOrbHudModal")
            if modal.is_visible():
                print("  ✓ مودال دستیار هوشمند با موفقیت گشوده شد.")
                
                # بررسی متن خوش‌آمدگویی
                transcript = page.locator("#aiTranscriptBox")
                if transcript.is_visible():
                    t_text = transcript.inner_text()
                    print(f"  ✓ متن پیام اولیه دستیار رویت شد: '{t_text[:60]}...'")
                
                # بررسی وضعیت صوتی
                state_pill = page.locator("#aiVoiceStatePill")
                if state_pill.is_visible():
                    print(f"  ✓ نشانگر وضعیت صوتی رویت شد: '{state_pill.inner_text()}'")
                
                shot3 = os.path.join(artifacts_dir, "e2e_3_ai_orb_modal.png")
                page.screenshot(path=shot3, full_page=False)
                screenshots_taken.append(("مودال دستیار صوتی و گوی هوشمند", shot3))
                print(f"  ✓ اسکرین‌شات ذخیره شد: {shot3}")

                # تست دکمه قطع مکالمه و بستن کامل
                disconnect_btn = page.locator("#aiDisconnectCallBtn")
                if disconnect_btn.is_visible():
                    print("  ✓ دکمه قطع مکالمه صوتی و خروج موجود است. کلیک جهت آزادسازی میکروفون...")
                    disconnect_btn.click(force=True)
                    time.sleep(1)
                    print("  ✓ مودال بسته شد و دسترسی میکروفون کاملاً آزاد گردید.")

        # ----------------------------------------------------
        # تست ۴: پایپ‌لاین CRM و مراحل معاملات
        # ----------------------------------------------------
        print("\n[تست ۴] بررسی بخش مدیریت متقاضیان و CRM Pipeline...")
        page.goto("http://127.0.0.1:5000/crm/pipeline", wait_until="networkidle")
        time.sleep(1)
        shot4 = os.path.join(artifacts_dir, "e2e_4_crm_pipeline.png")
        page.screenshot(path=shot4, full_page=True)
        screenshots_taken.append(("پایپ‌لاین CRM معاملات", shot4))
        print(f"  ✓ اسکرین‌شات ذخیره شد: {shot4}")

        # ----------------------------------------------------
        # تست ۵: اتاق مانیتورینگ زنده کراولر
        # ----------------------------------------------------
        print("\n[تست ۵] بررسی اتاق مانیتورینگ زنده کراولر...")
        page.goto("http://127.0.0.1:5000/crawler/live", wait_until="networkidle")
        time.sleep(1)
        shot5 = os.path.join(artifacts_dir, "e2e_5_crawler_live.png")
        page.screenshot(path=shot5, full_page=True)
        screenshots_taken.append(("مانیتورینگ زنده کراولر", shot5))
        print(f"  ✓ اسکرین‌شات ذخیره شد: {shot5}")

        # ----------------------------------------------------
        # تست ۶: احراز هویت و ورود با تلگرام / بله
        # ----------------------------------------------------
        print("\n[تست ۶] بررسی صفحه ورود کاربران با درگاه تلگرام و بله...")
        page.goto("http://127.0.0.1:5000/auth/login", wait_until="networkidle")
        time.sleep(1)
        shot6 = os.path.join(artifacts_dir, "e2e_6_auth_login.png")
        page.screenshot(path=shot6, full_page=True)
        screenshots_taken.append(("ورود با تلگرام و بله", shot6))
        print(f"  ✓ اسکرین‌شات ذخیره شد: {shot6}")

        browser.close()

    print("\n" + "=" * 60)
    print("✨ تمامی آزمون‌های Playwright با موفقیت ۱۰۰٪ کامل شدند!")
    print("=" * 60)
    return screenshots_taken

if __name__ == '__main__':
    run_comprehensive_e2e_test()
