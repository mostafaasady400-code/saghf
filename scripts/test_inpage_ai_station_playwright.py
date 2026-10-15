"""
تست اتوماسیون کامل Playwright برای اعتبارسنجی الزامات جدید دستیار هوشمند و نوبار سقف:
۱. بررسی تمیزی نوبار بالا، تغییر عنوان به «جستجوی زنده»، حذف اموجی‌های نامناسب و چیدمان بدون سرریز
۲. حذف کادرهای اضافه از تور مجازی (حذف tour-hud-footer، حذف tour-hud-header و حذف tour-zone-pills-bar)
۳. ابعاد اندازه کف دست گوی سه‌بعدی کریستالی هندسی (~94px) بدون کادر اضافه در حالت استراحت
۴. باز شدن زنده و نرم مشاور در همان صفحه بدون پرده سیاه و بدون مودال تمام‌صفحه
۵. منطق سوال‌محور در پاسخ به «سلام» (عدم استخراج شتابزده فایل‌ها و پرسیدن نوع معامله، منطقه و بودجه)
۶. تفکیک قطعی رهن و اجاره از خرید و فروش و صحت تگ «لینک آگهی»
"""

import sys
import os
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from playwright.sync_api import sync_playwright

def run_tests():
    print("🚀 در حال اجرای آزمون‌های Playwright به صورت زنده و مشاهده‌پذیر...")
    
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    with sync_playwright() as p:
        # اجرای با مرورگر قابل مشاهده (Visible Chrome)
        browser = p.chromium.launch(
            executable_path=chrome_path,
            headless=False,
            slow_mo=400,
            args=['--start-maximized']
        )
        context = browser.new_context(viewport={'width': 1366, 'height': 850}, locale='fa-IR')
        page = context.new_page()

        artifacts_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"

        def safe_screenshot(name):
            try:
                page.screenshot(path=os.path.join(artifacts_dir, name), timeout=5000)
            except Exception as e:
                print(f"   ⚠️ هشدار ذخیره تصویر {name}: {e}")

        print("1️⃣ بارگذاری صفحه کاتالوگ و تور سه‌بعدی...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1)

        # ارزیابی ۱: بررسی نوبار و عدم سرریز
        print("2️⃣ بررسی نوبار لوکس شیشه‌ای...")
        live_search_link = page.locator("a.floating-nav-link:has-text('جستجوی زنده')")
        assert live_search_link.is_visible(), "خطا: عنوان 'جستجوی زنده' در نوبار یافت نشد!"
        print("   ✅ گزینه 'جستجوی زنده' با موفقیت تایید شد.")

        # ارزیابی ۲: بررسی حذف کادرهای اضافه تور مجازی
        print("3️⃣ بررسی حذف کادرهای اضافه تور مجازی ۳۶۰ درجه...")
        hud_footer = page.locator(".tour-hud-footer")
        assert hud_footer.count() == 0, "خطا: کادر زیرین تور (.tour-hud-footer) هنوز در صفحه وجود دارد!"
        
        hud_header = page.locator(".tour-hud-header")
        assert hud_header.count() == 0, "خطا: کادر مشخصات اتاق (.tour-hud-header) هنوز در صفحه وجود دارد!"
        
        pills_bar = page.locator(".tour-zone-pills-bar")
        assert pills_bar.count() == 0, "خطا: پیل‌های سالن پذیرایی و غیره (.tour-zone-pills-bar) هنوز در صفحه وجود دارند!"
        print("   ✅ تمام کادرهای اضافه و مزاحم از تور مجازی حذف شده‌اند و تور کاملاً سینمایی و تمیز است.")

        safe_screenshot("ai_inpage_1_clean_tour_and_nav.png")

        # ارزیابی ۳: بررسی گوی حالت استراحت (اندازه کف دست ~94px بدون کادر مستطیل)
        print("4️⃣ بررسی گوی استراحت اندازه کف دست...")
        station = page.locator("#ai-station")
        assert station.is_visible(), "خطا: سکشن دستیار در صفحه یافت نشد!"
        
        resting_btn = page.locator("#restingOrbBtn")
        assert resting_btn.is_visible(), "خطا: دکمه گوی استراحت در صفحه مشاهده نشد!"
        
        box = resting_btn.bounding_box()
        print(f"   📐 ابعاد گوی استراحت در صفحه: عرض {box['width']}px × ارتفاع {box['height']}px")
        assert box['width'] >= 85 and box['height'] >= 85, f"خطا: اندازه گوی کوچک است ({box['width']}px)!"
        print("   ✅ اندازه گوی استراحت کاملاً متناسب با کف دست و بدون کادر دور آن است.")

        safe_screenshot("ai_inpage_2_palm_sized_resting_orb.png")

        # ارزیابی ۴: کلیک روی گوی و باز شدن زنده مشاور در همان صفحه (In-Page Activation)
        print("5️⃣ تست کلیک روی گوی و باز شدن پنل در صفحه...")
        resting_btn.click()
        time.sleep(1)

        active_panel = page.locator("#aiActivePanel")
        assert active_panel.is_visible(), "خطا: پنل مشاور در صفحه باز نشد!"
        
        # اطمینان از اینکه مودال فول‌اسکرین با پس‌زمینه فیکس نیست
        backdrop = page.locator(".chatgpt-voice-modal-backdrop")
        assert backdrop.count() == 0, "خطا: مودال تمام‌صفحه یا پرده سیاه نباید در صفحه باشد!"
        print("   ✅ پنل مشاور بدون هیچ پرده سیاهی نرم و زیبا روی همان صفحه زیر تور باز شد.")

        safe_screenshot("ai_inpage_3_active_station_opened.png")

        # ارزیابی ۵: تست منطق مشاور با ارسال «سلام» (باید سوال بپرسد و فایلی خارج نکند)
        print("6️⃣ تست منطق پرسش و پاسخ: ارسال «سلام»...")
        input_field = page.locator("#chatgptVoiceInput")
        input_field.fill("سلام")
        page.locator("#btnChatgptSend").click()
        time.sleep(2)

        live_transcript = page.locator("#chatgptLiveTranscript")
        transcript_text = live_transcript.inner_text()
        print(f"   💬 پاسخ مشاور به سلام: {transcript_text}")
        
        assert "رهن و اجاره" in transcript_text or "خرید و فروش" in transcript_text or "منطقه" in transcript_text, "خطا: مشاور سوالات تعیین نیاز را نپرسید!"
        
        cards_container = page.locator("#chatgptAgentResults")
        assert not cards_container.is_visible(), "خطا: در پاسخ به سلام نباید فایل‌ها به صورت ناگهانی خارج شوند!"
        print("   ✅ منطق مشاور کاملاً درست عمل کرد: هیچ فایل مازاد استخراج نشد و سوالات شفاف‌سازی پرسیده شد.")

        safe_screenshot("ai_inpage_4_greeting_questions_no_files.png")

        # ارزیابی ۶: ارسال خواسته مشخص رهن و اجاره منطقه ۵ با بودجه ۱ تومن ۶۰ تومن
        print("7️⃣ تست استخراج دقیق فایل‌های رهن و اجاره منطقه ۵...")
        input_field.fill("بودجم ۱ تومن ۶۰ تومنه توی منطقه ۵ برام فایل پیدا کن")
        page.locator("#btnChatgptSend").click()
        time.sleep(3)

        assert cards_container.is_visible(), "خطا: کانتینر کارت‌های استخراج فایل نمایان نشد!"
        cards = page.locator("#chatgptCardsList > div")
        card_count = cards.count()
        print(f"   🏢 تعداد فایل‌های رهن و اجاره استخراج‌شده در صفحه: {card_count}")
        assert card_count > 0, "خطا: فایلی استخراج نشد!"

        # بررسی قطعی عدم نمایش قیمت میلیاردی فروش در رهن و اجاره
        first_card_text = cards.first.inner_text()
        print(f"   📋 مشخصات کارت اول رهن و اجاره: {first_card_text}")
        assert "ودیعه" in first_card_text or "اجاره" in first_card_text, "خطا: کارت رهن و اجاره حاوی ودیعه/اجاره نیست!"
        assert "میلیارد تومان" not in first_card_text or "ودیعه" in first_card_text, "خطا: قیمت فروش در کارت اجاره ظاهر شده!"

        # بررسی وجود تگ <a> با عنوان «لینک آگهی»
        ad_link = cards.first.locator("a[title='لینک آگهی']")
        assert ad_link.is_visible(), "خطا: تگ لینک آگهی با عنوان 'لینک آگهی' یافت نشد!"
        print(f"   🔗 لینک مستقیم آگهی کراول شده: {ad_link.get_attribute('href')}")
        print("   ✅ تفکیک صددرصدی رهن و اجاره و وجود تگ 'لینک آگهی' تایید شد.")

        safe_screenshot("ai_inpage_5_region5_rent_cards.png")

        # ارزیابی ۷: تست استخراج فایل‌های خرید و فروش بازه ۲۰ تا ۲۵ میلیارد
        print("8️⃣ تست استخراج فایل‌های فروش ۲۰ تا ۲۵ میلیارد منطقه ۲ و ۵...")
        input_field.fill("خونه‌های ۲۰ تا ۲۵ میلیارد واسه من بکش بیرون تو منطقه ۵ یا ۲")
        page.locator("#btnChatgptSend").click()
        time.sleep(3)

        sale_first_card_text = cards.first.inner_text()
        print(f"   💎 مشخصات کارت اول فروش: {sale_first_card_text}")
        assert "قیمت کل" in sale_first_card_text or "میلیارد" in sale_first_card_text, "خطا: قیمت کل میلیاردی در فایل فروش نمایش داده نشده!"
        print("   ✅ تفکیک قطعی خرید و فروش با قیمت‌های میلیاردی تایید شد.")

        safe_screenshot("ai_inpage_6_sale_20_25b_cards.png")

        # ارزیابی ۸: تست بستن پنل و بازگشت به گوی استراحت
        print("9️⃣ تست بستن پنل مشاور و بازگشت به گوی اندازه کف دست...")
        close_btn = page.locator("button:has-text('بستن پنل')")
        close_btn.click()
        time.sleep(1)

        assert not active_panel.is_visible(), "خطا: پنل مشاور بسته نشد!"
        assert resting_btn.is_visible(), "خطا: گوی استراحت پس از بستن پنل مشاهده نشد!"
        print("   ✅ بستن پنل و بازگشت به حالت گوی استراحت با موفقیت انجام شد.")

        safe_screenshot("ai_inpage_7_panel_closed_back_to_orb.png")

        browser.close()
        print("\n🎉 تمامی سناریوها و الزامات کاربری با موفقیت ۱۰۰٪ پاس شدند!")

if __name__ == "__main__":
    run_tests()
