import os
import sys
import time

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from playwright.sync_api import sync_playwright

def run_visible_demo():
    print("==================================================================")
    print("🚀 اجرای زنده و نمایشی سامانه املاک سقف و دستیار هوشمند با Google Chrome")
    print("🌐 پنجره رسمی گوگل کروم روی مانیتور شما باز می‌شود تا مراحل را به طور زنده ببینید...")
    print("==================================================================")

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chrome_path,
            headless=False,
            slow_mo=1000,  # مکث ۱ ثانیه‌ای برای مشاهده کامل کاربر
            args=['--start-maximized']
        )
        context = browser.new_context(
            no_viewport=True,
            locale='fa-IR'
        )
        page = context.new_page()

        # ----------------------------------------------------
        # صحنه ۱: بارگذاری داشبورد مدیریتی سقف
        # ----------------------------------------------------
        print("\n[صحنه ۱] باز کردن داشبورد جامع مدیریتی سقف...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(3)

        # ----------------------------------------------------
        # صحنه ۲: کلیک روی دکمه دستیار هوشمند در داشبورد
        # ----------------------------------------------------
        print("\n[صحنه ۲] کلیک روی «دستیار هوشمند (گوی سه بعدی)» در سربرگ داشبورد...")
        dash_btn = page.locator("button:has-text('دستیار هوشمند (گوی سه بعدی)')").first
        if dash_btn.is_visible():
            dash_btn.hover()
            time.sleep(1)
            dash_btn.click()
            time.sleep(3)

        # ----------------------------------------------------
        # صحنه ۳: مشاهده گوی جمع‌وجور و باز شدن مودال ChatGPT Voice
        # ----------------------------------------------------
        print("\n[صحنه ۳] مشاهده مودال تمام‌صفحه صوتی ChatGPT Voice با گوی کریستالی...")
        modal = page.locator("#chatgptVoiceModal")
        if not modal.is_visible():
            # اگر هنوز باز نشده، روی نوار پیل کلیک می‌کنیم
            page.locator("#ai-station").click()
            time.sleep(2)

        time.sleep(2)

        # ----------------------------------------------------
        # صحنه ۴: تست سناریوی اول کاربر (۱ تومن ۶۰ تومن منطقه ۵)
        # ----------------------------------------------------
        prompt1 = "بودجم ۱ تومن ۶۰ تومنه توی منطقه ۵ تهران برام خونه‌ها رو پیدا کن"
        print(f"\n[صحنه ۴] اجرای دستور واقعی کاربر:\n«{prompt1}»...")
        
        input_box = page.locator("#chatgptVoiceInput")
        send_btn = page.locator("#btnChatgptSend")

        input_box.fill(prompt1)
        time.sleep(1.5)
        send_btn.click()

        print("  ⚡ در حال پردازش توسط ایجنت هوشمند سقف...")
        time.sleep(3.5)

        transcript = page.locator("#chatgptLiveTranscript").inner_text()
        print(f"  🔊 پاسخ صوتی ایجنت: «{transcript[:100]}...»")
        time.sleep(4)

        # ----------------------------------------------------
        # صحنه ۵: تست سناریوی دوم کاربر (فروش ۲۰ تا ۲۵ میلیارد)
        # ----------------------------------------------------
        print("\n[صحنه ۵] اجرای سناریوی دوم: «فروش ۲۰ تا ۲۵ میلیارد منطقه ۲ و ۵»...")
        chip_btn = page.locator("button.station-chip:has-text('فروش ۲۰ تا ۲۵ میلیارد')").first
        chip_btn.hover()
        time.sleep(1)
        chip_btn.click()

        print("  ⚡ در حال استخراج فایل‌های فروش طلایی از دیتابیس...")
        time.sleep(3.5)

        transcript2 = page.locator("#chatgptLiveTranscript").inner_text()
        print(f"  🔊 پاسخ صوتی ایجنت: «{transcript2[:100]}...»")
        time.sleep(4)

        # ----------------------------------------------------
        # صحنه ۶: بستن مودال و مشاهده تور مجازی ۳۶۰ درجه و فایل‌های ویترین
        # ----------------------------------------------------
        print("\n[صحنه ۶] بستن مودال صوتی و ورق زدن تور مجازی ۳۶۰ درجه عمارت...")
        close_btn = page.locator("button[title='بستن']:has-text('✕')").first
        close_btn.click()
        time.sleep(2)

        # اسکرول نرم به بالای صفحه برای مشاهده تور ۳۶۰
        page.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' })")
        time.sleep(2.5)

        # تغییر اتاق تور به مستر روم
        bedroom_btn = page.locator("button.tour-zone-pill-btn[data-zone-index='2']").first
        if bedroom_btn.is_visible():
            bedroom_btn.click()
            time.sleep(2)

        # اسکرول به فهرست آگهی‌ها
        page.evaluate("window.scrollTo({ top: 800, behavior: 'smooth' })")
        time.sleep(3)

        # ----------------------------------------------------
        # صحنه ۷: بررسی وضعیت اتاق مانیتورینگ زنده کراولر
        # ----------------------------------------------------
        print("\n[صحنه ۷] ورود به اتاق مانیتورینگ زنده کراولر دیوار و شیپور...")
        page.goto("http://127.0.0.1:5000/crawler/live", wait_until="networkidle")
        time.sleep(3)

        print("\n✨ تمامی بخش‌های سامانه و دستیار صوتی با موفقیت کامل جلوی چشم شما اجرا شدند.")
        time.sleep(2)
        browser.close()

if __name__ == '__main__':
    run_visible_demo()
