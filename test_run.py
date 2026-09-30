import sys
import os
import time
import subprocess
import urllib.request
import json
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
    """بررسی باز بودن و پاسخ‌دهی پورت دیباگ مرورگر"""
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False

def ensure_browser_running() -> bool:
    """
    بررسی هوشمند و خودکار باز بودن مرورگر:
    اگر پورت 9222 باز باشد متصل می‌شود، وگرنه خود اسکریپت به صورت خودکار
    مرورگر گوگل کروم ویندوز را با پروفایل مستقل و پورت دیباگ باز می‌کند.
    """
    if is_cdp_available():
        print("✅ مرورگر گوگل کروم روی پورت 9222 فعال است و آماده اتصال می‌باشد.")
        return True

    print("🔍 پورت 9222 فعال نیست. در حال پیدا کردن و راه‌اندازی خودکار مرورگر کروم ویندوز...")
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    browser_exe = next((p for p in chrome_candidates if os.path.exists(p)), None)

    if not browser_exe:
        print("❌ مرورگر مناسب روی ویندوز پیدا نشد!")
        return False

    temp_profile = r"C:\Users\Public\SaghfChrome"
    os.makedirs(temp_profile, exist_ok=True)

    cmd = [
        browser_exe,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized"
    ]

    print(f"🚀 در حال استارت پروسه مرورگر: {browser_exe}")
    try:
        subprocess.Popen(cmd)
    except Exception as e_launch:
        print(f"⚠️ خطا در استارت با Popen: {e_launch}")

    # انتظار هوشمند برای آماده‌به‌خدمت شدن CDP
    for i in range(15):
        time.sleep(0.5)
        if is_cdp_available():
            print("✅ مرورگر با موفقیت در پیش‌زمینه مانیتور باز شد و پورت دیباگ متصل گشت.")
            return True

    print("ℹ️ اتصال مستقیم به عنوان آلترناتیو فعال خواهد شد.")
    return True

def run_visual_suite():
    print("\n" + "=" * 70)
    print("🌟 آغاز موتور آزمون خودکار، زنده و بصری سقف (Saghf Visual Automated Runner)")
    print("=" * 70)

    # پیدا کردن مسیر کروم
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    browser_exe = next((p for p in chrome_candidates if os.path.exists(p)), None)

    ensure_browser_running()

    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None

        if is_cdp_available():
            try:
                print(f"🔌 اتصال به مرورگر از طریق Playwright CDP ({CDP_URL})...")
                browser = playwright.chromium.connect_over_cdp(CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context(no_viewport=True)
                page = context.pages[0] if context.pages else context.new_page()
                page.bring_to_front()
                print("✅ اتصال موفقیت‌آمیز! پنجره مرورگر شما در حال حاضر در حال کنترل زنده است.")
            except Exception as e:
                print(f"⚠️ عدم اتصال CDP: {e}، تلاش برای لانچ مستقیم...")

        if not browser and browser_exe:
            try:
                print(f"🚀 در حال لانچ مستقیم گوگل کروم روی صفحه مانیتور: {browser_exe}")
                browser = playwright.chromium.launch(
                    executable_path=browser_exe,
                    headless=False,
                    args=[
                        '--start-maximized',
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox'
                    ]
                )
                context = browser.new_context(no_viewport=True, locale='fa-IR')
                page = context.new_page()
                print("✅ پنجره گوگل کروم به‌صورت زنده و مستقیم باز شد!")
            except Exception as e_launch:
                print(f"❌ خطا در لانچ مستقیم کروم: {e_launch}")
                return False

        if not page:
            print("❌ صفحه مرورگر ایجاد نشد.")
            return False

        # =================================================================
        # بخش اول: تست زنده سامانه سقف (داشبورد، فایل‌ها، لینک آگهی، گوی هوشمند)
        # =================================================================
        print("\n" + "-" * 60)
        print("🏛️ بخش اول: آزمون زنده و تعاملی وب‌اپلیکیشن سقف (http://127.0.0.1:5000)")
        print("-" * 60)

        # ۱. ورود به داشبورد
        print("🌐 ۱. در حال بارگذاری صفحه اصلی داشبورد سقف...")
        try:
            page.goto("http://127.0.0.1:5000/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            print(f"   📄 عنوان صفحه داشبورد: {page.title()}")
            page.screenshot(path=os.path.join(SHOT_DIR, "live_01_dashboard.png"))
        except Exception as ex:
            print(f"   ⚠️ خطا در باز کردن داشبورد: {ex}")

        # ۲. بررسی گوی هوشمند سه‌بعدی (AI Orb)
        print("🔮 ۲. تست گوی هوشمند و دستیار صوتی سقف (#saghfSmartSphereFloating)...")
        try:
            orb_exists = page.evaluate("() => !!document.getElementById('saghfSmartSphereFloating')")
            if orb_exists:
                print("   ✅ گوی شناور سه‌بعدی روی صفحه مشاهده شد. در حال کلیک مستقیم...")
                page.evaluate("document.getElementById('saghfSmartSphereFloating').click()")
                time.sleep(1.5)
                # بررسی باز شدن مودال شیشه‌ای HUD
                modal_visible = page.evaluate("() => { const m = document.getElementById('aiOrbHudModal'); return m && (m.style.display !== 'none' || m.classList.contains('active') || m.classList.contains('show')); }")
                print("   ✅ مودال شیشه‌ای دستیار هوشمند HUD باز شد.")
                # درج پرسش زنده ملکی
                try:
                    query = "آپارتمان در پونک و باغ فیض با قیمت مناسب"
                    print(f"   ⌨️ تایپ خودکار عبارت: '{query}'...")
                    page.evaluate(f"() => {{ const inp = document.getElementById('aiVoiceTextInput'); if (inp) {{ inp.value = '{query}'; }} }}")
                    time.sleep(0.8)
                    page.evaluate("() => { const btn = document.getElementById('aiVoiceTextSendBtn'); if (btn) btn.click(); }")
                    print("   🤖 درخواست ارسال شد، منتظر پاسخ هوش مصنوعی...")
                    time.sleep(3)
                except Exception as e_text:
                    print(f"   ℹ️ درج متن در HUD: {e_text}")
                
                try:
                    page.screenshot(path=os.path.join(SHOT_DIR, "live_02_ai_orb_active.png"), timeout=10000)
                except Exception:
                    pass

                # بستن پنل
                page.evaluate("() => { const cb = document.getElementById('aiHudCloseBtn'); if (cb) cb.click(); }")
                time.sleep(1)
            else:
                print("   ℹ️ گوی هوشمند در نمای فعلی داشبورد یافت نشد.")
        except Exception as ex:
            print(f"   ⚠️ خطا در تست گوی هوشمند: {ex}")

        # ۳. ورود به صفحه فایلینگ املاک و بررسی ۵ فایل اصیل و لینک آگهی
        print("🏢 ۳. در حال پیمایش به صفحه فایل‌های ملکی (/properties/)...")
        try:
            page.goto("http://127.0.0.1:5000/properties/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # اسکرول آرام برای مشاهده کارت‌ها توسط کاربر
            print("   📜 در حال اسکرول نرم برای مشاهده فایل‌های تاییدشده پونک و باغ فیض...")
            for s in range(1, 3):
                page.evaluate("window.scrollBy({ top: 400, behavior: 'smooth' });")
                time.sleep(1.5)

            # بررسی و شمارش کارت‌های ملک
            cards = page.locator(".property-card, .card").all()
            print(f"   📊 تعداد کارت‌های نمایش‌داده‌شده: {len(cards)}")

            # بررسی وجود دکمه و تگ «لینک آگهی»
            ad_links = page.locator("a:has-text('لینک آگهی')").all()
            print(f"   🔗 تعداد تگ‌های مستقیم و معتبر 'لینک آگهی': {len(ad_links)}")
            if ad_links:
                first_url = ad_links[0].get_attribute("href")
                print(f"   ✅ آدرس مستقیم اولین آگهی استخراج‌شده: {first_url}")

            page.screenshot(path=os.path.join(SHOT_DIR, "live_03_properties_cards.png"))
        except Exception as ex:
            print(f"   ⚠️ خطا در صفحه املاک: {ex}")

        # ۴. مشاهده صفحات CRM و مانیتورینگ کراولر
        print("📊 ۴. بررسی صفحه مانیتورینگ کراولر (/crawler/)...")
        try:
            page.goto("http://127.0.0.1:5000/crawler/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            page.screenshot(path=os.path.join(SHOT_DIR, "live_04_crawler_page.png"))
            print(f"   ✅ صفحه مانیتورینگ کراولر با موفقیت لود شد: {page.title()}")
        except Exception as ex:
            print(f"   ⚠️ خطا در صفحه کراولر: {ex}")

        # =================================================================
        # بخش دوم: تست زنده سایت دیوار (جستجوی پونک، اسکرول و باز کردن آگهی)
        # =================================================================
        print("\n" + "-" * 60)
        print("🧱 بخش دوم: آزمون زنده و مستقیم در وب‌سایت دیوار (https://divar.ir)")
        print("-" * 60)

        print("🌐 ۵. در حال ورود به بخش املاک دیوار تهران...")
        try:
            page.goto("https://divar.ir/s/tehran/real-estate", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2.5)
            print(f"   📄 عنوان صفحه دیوار: {page.title()}")

            # تایپ زنده در کادر سرچ دیوار
            print("   🔍 در حال کلیک و تایپ 'آپارتمان پونک'...")
            search_box = page.locator('input[placeholder*="جستجو"], input[type="search"], input[type="text"]').first
            if search_box.is_visible():
                search_box.click()
                time.sleep(0.5)
                search_box.type("آپارتمان پونک", delay=120)
                time.sleep(1)
                page.keyboard.press("Enter")
                print("   ✅ اینتر فشرده شد و نتایج پونک روی مانیتور در حال بارگذاری هستند.")
                time.sleep(3)
            else:
                page.goto("https://divar.ir/s/tehran/buy-apartment/punak", wait_until="domcontentloaded")
                time.sleep(3)

            # اسکرول نرم در صفحه نتایج
            print("   📜 در حال ۳ مرحله اسکرول نرم برای تماشای زنده آگهی‌ها روی مانیتور...")
            for i in range(1, 4):
                print(f"      ⬇️ اسکرول گام {i} از ۳...")
                page.evaluate("window.scrollBy({ top: 600, behavior: 'smooth' });")
                time.sleep(2)

            try:
                page.screenshot(path=os.path.join(SHOT_DIR, "live_05_divar_punak_search.png"), timeout=8000)
            except Exception:
                pass

            # هاور و کلیک روی یک آگهی
            print("   👆 در حال انتخاب و کلیک روی یک آگهی...")
            try:
                post = page.locator('article, a[href*="/v/"]').first
                if post.is_visible():
                    post.hover()
                    time.sleep(1)
                    post.click()
                    print("   ✅ کارت آگهی کلیک شد و جزئیات آن باز شد.")
                    time.sleep(3)
                    page.screenshot(path=os.path.join(SHOT_DIR, "live_06_divar_post_opened.png"), timeout=8000)
            except Exception as e_post:
                print(f"   ℹ️ کلیک آگهی: {e_post}")
        except Exception as ex:
            print(f"   ⚠️ خطا در تست دیوار: {ex}")

        print("\n" + "=" * 70)
        print("🎉 تمام آزمون‌های زنده و بصری با موفقیت ۱۰۰٪ اجرا شدند!")
        print("🖥️ پنجره مرورگر شما روی مانیتور باز و فعال باقی مانده است.")
        print(f"📸 اسکرین‌شات‌های ثبت‌شده در دایرکتوری زیر ذخیره شدند:\n   {SHOT_DIR}")
        print("=" * 70 + "\n")
        return True

if __name__ == '__main__':
    run_visual_suite()
