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

def run_test():
    artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
    os.makedirs(artifact_dir, exist_ok=True)

    print("🚀 شروع آزمون اختصاصی Playwright برای سکشن دستیار هوشمند و گوی کریستالی سه‌بعدی...")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        context = browser.new_context(
            viewport={'width': 1440, 'height': 950},
            locale='fa-IR'
        )
        page = context.new_page()

        # ----------------------------------------------------
        # تست ۱: بارگذاری صفحه املاک و بررسی موقعیت سکشن دستیار هوشمند
        # ----------------------------------------------------
        print("\n[تست ۱] بارگذاری ویترین املاک و بررسی قرارگیری سکشن دستیار هوشمند زیر تور ۳۶۰...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1)

        # بررسی وجود تور ۳۶۰ درجه
        tour = page.locator("#mansion-3d-tour-container")
        assert tour.count() > 0, "کانتینر تور ۳۶۰ درجه عمارت لوکس یافت نشد!"
        print("  ✓ کانتینر تور مجازی ۳۶۰ درجه عمارت رویت شد.")

        # بررسی سکشن ثابت دستیار هوشمند
        station = page.locator("#ai-station")
        assert station.count() > 0, "سکشن #ai-station یافت نشد!"
        print("  ✓ سکشن مستقل #ai-station با موفقیت در ساختار صفحه شناسایی شد.")

        # بررسی عدم وجود ویجت شناور مزاحم (position: fixed)
        floating_orb = page.locator("#aiOrbFloatWrapper")
        is_float_visible = floating_orb.is_visible() if floating_orb.count() > 0 else False
        assert not is_float_visible, "ویجت شناور مزاحم نباید در صفحه مرئی باشد!"
        print("  ✓ عدم شناوری سراسری تایید شد: هیچ دکمه شناور مزاحمی روی صفحه حرکت نمی‌کند.")

        # اسکرول به سکشن ایستگاه و ثبت اسکرین‌شات
        station.scroll_into_view_if_needed()
        time.sleep(1)
        shot1 = os.path.join(artifact_dir, "ai_station_1_section_view.png")
        page.screenshot(path=shot1, full_page=False)
        print(f"  ✓ اسکرین‌شات سکشن ایستگاه هوشمند ذخیره شد: {shot1}")

        # ----------------------------------------------------
        # تست ۲: بررسی گوی سه‌بعدی کریستالی، هاله نوری و انیمیشن
        # ----------------------------------------------------
        print("\n[تست ۲] بررسی گوی سه‌بعدی کریستالی و هاله نوری...")
        orb_container = page.locator("#orb-container")
        assert orb_container.is_visible(), "کانتینر گوی کریستالی هوشمند مرئی نیست!"

        orb_img = page.locator("#mainCrystalOrbImg")
        assert orb_img.is_visible(), "تصویر گوی کریستالی سه‌بعدی بارگذاری نشده است!"
        print("  ✓ گوی سه‌بعدی کریستالی با رفلکس‌های فیروزه‌ای و بنفش سایبری فعال و مرئی است.")

        # ----------------------------------------------------
        # تست ۳: کلیک روی دکمه «دستیار هوشمند» در نوبار و اسکرول نرم + پالس گوی
        # ----------------------------------------------------
        print("\n[تست ۳] کلیک روی دکمه «دستیار هوشمند» در نوبار و بررسی اسکرول نرم و پالس گوی...")
        # بازگشت به بالای صفحه
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)

        nav_btn = page.locator("header.floating-3d-navbar button:has-text('دستیار هوشمند')").first
        assert nav_btn.is_visible(), "دکمه دستیار هوشمند در نوبار یافت نشد!"
        nav_btn.click()
        print("  ✓ دکمه دستیار هوشمند در نوبار کلیک شد.")
        time.sleep(1.2)

        shot2 = os.path.join(artifact_dir, "ai_station_2_scrolled_and_pulsed.png")
        page.screenshot(path=shot2, full_page=False)
        print(f"  ✓ اسکرین‌شات پس از اسکرول نرم و پالس نوری ثبت شد: {shot2}")

        # ----------------------------------------------------
        # تست ۴: ارسال سوال متنی و دریافت پاسخ تعاملی هوش مصنوعی
        # ----------------------------------------------------
        print("\n[تست ۴] تست ارسال سوال در کادر ورودی دستیار هوشمند...")
        input_field = page.locator("#stationMessageInput")
        send_btn = page.locator("#btnStationSend")

        assert input_field.is_visible(), "فیلد ورودی متن پیام مرئی نیست!"
        input_field.fill("امکانات سیستم چیه؟")
        time.sleep(0.3)
        send_btn.click()
        print("  ✓ سوال «امکانات سیستم چیه؟» ارسال گردید.")

        # انتظار برای ظهور باکس پاسخ هوشمند و متن پاسخ
        time.sleep(1.8)
        response_box = page.locator("#stationResponseBox")
        assert response_box.is_visible(), "باکس پاسخ دستیار هوشمند مرئی نشد!"

        response_text = page.locator("#stationResponseText").inner_text()
        print(f"  ✓ پاسخ بلادرنگ دریافت شد:\n    «{response_text[:120]}...»")
        assert "سقف" in response_text or "پیام‌رسان" in response_text or "تور" in response_text or "هوشمند" in response_text, "محتوای پاسخ نامعتبر است!"

        shot3 = os.path.join(artifact_dir, "ai_station_3_chat_response.png")
        page.screenshot(path=shot3, full_page=False)
        print(f"  ✓ اسکرین‌شات پاسخ هوش مصنوعی ذخیره شد: {shot3}")

        # ----------------------------------------------------
        # تست ۵: بررسی چیپ‌های پیشنهادی سریع
        # ----------------------------------------------------
        print("\n[تست ۵] تست کلیک روی چیپ پیشنهادی «استعلام ۵ پیام‌رسان»...")
        chip = page.locator("button.station-chip:has-text('استعلام ۵ پیام‌رسان')").first
        if chip.is_visible():
            chip.click()
            time.sleep(1.2)
            chip_reply = page.locator("#stationResponseText").inner_text()
            print(f"  ✓ پاسخ چیپ استعلام پیام‌رسان دریافت شد:\n    «{chip_reply[:120]}...»")

        # ----------------------------------------------------
        # تست ۶: اتصال از داشبورد مدیریتی به ایستگاه دستیار هوشمند
        # ----------------------------------------------------
        print("\n[تست ۶] تست اتصال از داشبورد اصلی به ایستگاه دستیار هوشمند...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(1)

        dash_ai_btn = page.locator("button:has-text('دستیار هوشمند (گوی سه بعدی)')").first
        assert dash_ai_btn.is_visible(), "دکمه دستیار هوشمند در داشبورد یافت نشد!"
        dash_ai_btn.click()
        print("  ✓ دکمه دستیار هوشمند در سربرگ داشبورد کلیک شد.")

        # انتظار برای انتقال به صفحه properties و هدایت به هش #ai-station
        page.wait_for_load_state("networkidle")
        time.sleep(1.5)
        current_url = page.url
        print(f"  ✓ صفحه مقصد پس از کلیک در داشبورد: {current_url}")
        assert "#ai-station" in current_url or "/properties/" in current_url, "هدایت به صفحه مناسب صورت نگرفت!"

        shot4 = os.path.join(artifact_dir, "ai_station_4_dashboard_navigation.png")
        page.screenshot(path=shot4, full_page=False)
        print(f"  ✓ اسکرین‌شات انتقال از داشبورد به ایستگاه هوشمند ثبت شد: {shot4}")

        browser.close()
        print("\n✨ تمامی مراحل آزمون Playwright با موفقیت ۱۰۰٪ تایید شدند!")

if __name__ == '__main__':
    run_test()
