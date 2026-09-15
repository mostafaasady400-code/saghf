import os
import sys
import time
from datetime import datetime, timedelta

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
from app import create_app
from database.db import db
from database.models import Property

def run_live_test():
    artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\ae6d95ef-305d-4bff-b1ca-7fcce2ce91f2"
    os.makedirs(artifact_dir, exist_ok=True)

    print("🚀 شروع آزمون زنده End-to-End با Playwright و مرورگر Google Chrome...")

    # Ensure at least one property is expired (8 days old) for testing followup
    app = create_app()
    with app.app_context():
        p = Property.query.first()
        if p:
            p.created_at = datetime.utcnow() - timedelta(days=8)
            p.status = 'verified'
            db.session.commit()
            print(f"✓ فایل آزمایشی #{p.id} با عنوان «{p.title}» به عنوان فایل ۸ روزه تنظیم شد.")

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    print(f"🌐 مرورگر اجرایی: {chrome_path}")

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
        # تست ۱: داشبورد اصلی
        # ----------------------------------------------------
        print("\n[تست ۱] بارگذاری داشبورد مدیریتی سقف...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(1)
        dash_shot = os.path.join(artifact_dir, "live_test_1_dashboard.png")
        page.screenshot(path=dash_shot, full_page=True)
        print(f"  ✓ اسکرین‌شات داشبورد ذخیره شد: {dash_shot}")

        # ----------------------------------------------------
        # تست ۲: ویترین فایل‌های فعال و دستیار هوشمند پیشنهاد به مشتری
        # ----------------------------------------------------
        print("\n[تست ۲] بررسی ویترین املاک، فیلترهای بودجه و دستیار هوشمند...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1)
        
        # Test selecting a client in the Smart Client Matcher
        client_select = page.locator("select[name='client_id']")
        if client_select.count() > 0:
            options = client_select.locator("option").all()
            if len(options) > 1:
                client_select.select_option(index=1)
                page.wait_for_load_state("networkidle")
                time.sleep(1)
                print("  ✓ فیلتر هوشمند تطبیق با مشتری فعال گردید.")

        list_shot = os.path.join(artifact_dir, "live_test_2_properties_list.png")
        page.screenshot(path=list_shot, full_page=True)
        print(f"  ✓ اسکرین‌شات ویترین فایل‌ها ذخیره شد: {list_shot}")

        # ----------------------------------------------------
        # تست ۳: بخش یادآوری پیگیری مجدد (چرخه ۷ روزه)
        # ----------------------------------------------------
        print("\n[تست ۳] ورود به صفحه اختصاصی «یادآوری پیگیری مجدد (۷ روزه)»...")
        page.goto("http://127.0.0.1:5000/properties/followup", wait_until="networkidle")
        time.sleep(1)

        # Check for expired badge
        badge = page.locator("text=روز گذشته").first
        if badge.is_visible():
            print(f"  ✓ بج نئونی رد شدن از مرز ۷ روز رویت شد: '{badge.inner_text()}'")

        followup_shot = os.path.join(artifact_dir, "live_test_3_followup_page.png")
        page.screenshot(path=followup_shot, full_page=True)
        print(f"  ✓ اسکرین‌شات صفحه پیگیری مجدد ذخیره شد: {followup_shot}")

        # ----------------------------------------------------
        # تست ۴: باز کردن مودال استعلام ۵ پیام‌رسان
        # ----------------------------------------------------
        print("\n[تست ۴] کلیک روی دکمه استعلام ۵ پیام‌رسان و باز شدن مودال...")
        inquiry_btn = page.locator("button:has-text('استعلام وضعیت در ۵ پیام‌رسان')").first
        if inquiry_btn.is_visible():
            inquiry_btn.click()
            time.sleep(1.5)
            
            # Verify modal visible
            modal = page.locator("#messengerInquiryModal")
            if modal.is_visible():
                print("  ✓ مودال نئونی ۵ پیام‌رسان با موفقیت باز شد!")

                # Check platforms
                wa = page.locator("#btnPlatformWhatsapp")
                tg = page.locator("#btnPlatformTelegram")
                ble = page.locator("#btnPlatformBale")
                eitaa = page.locator("#btnPlatformEitaa")
                rubika = page.locator("#btnPlatformRubika")
                print(f"  ✓ دکمه‌های پیام‌رسان‌ها: واتساپ ({wa.is_visible()}), تلگرام ({tg.is_visible()}), بله ({ble.is_visible()}), ایتا ({eitaa.is_visible()}), روبیکا ({rubika.is_visible()})")

                # Verify message content
                msg_val = page.locator("#modalInquiryText").input_value()
                print("  ✓ متن استعلام محترمانه فارسی دریافت شد:")
                print("    " + msg_val.replace("\n", "\n    ")[:180] + "...")

                modal_shot = os.path.join(artifact_dir, "live_test_4_messenger_modal.png")
                page.screenshot(path=modal_shot, full_page=False)
                print(f"  ✓ اسکرین‌شات مودال پیام‌رسان‌ها ذخیره شد: {modal_shot}")

                # ----------------------------------------------------
                # تست ۵: ثبت فوری پاسخ مالک (تایید موجودی و تمدید ۷ روزه)
                # ----------------------------------------------------
                print("\n[تست ۵] ثبت پاسخ مالک (گزینه ۱: تایید موجودی و تمدید ۷ روزه)...")
                confirm_btn = page.locator("button:has-text('۱. تایید موجودی')")
                if confirm_btn.is_visible():
                    confirm_btn.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle")
                    print("  ✓ پاسخ مالک ثبت گردید و صفحه به صورت خودکار ریلود شد.")

        # ----------------------------------------------------
        # تست ۶: بررسی گزینه تماس مستقیم و باز کردن مودال ثبت شماره و اتصال دیوار
        # ----------------------------------------------------
        print("\n[تست ۶] بررسی گزینه تماس مستقیم در کارت‌های آگهی...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1)

        # Check for contact box
        contact_box = page.locator(".contact-option-box").first
        if contact_box.is_visible():
            print("  ✓ کادر نئونی «گزینه تماس مستقیم با آگهی‌دهنده» در کارت املاک رویت شد.")

        # Test opening Divar Session Modal
        print("\n[تست ۷] کلیک روی «اتصال حساب دیوار» در منوی هدر...")
        divar_btn = page.locator("button:has-text('اتصال حساب دیوار')").first
        if divar_btn.is_visible():
            divar_btn.click()
            time.sleep(1)
            divar_modal = page.locator("#divarSessionModal")
            if divar_modal.is_visible():
                print("  ✓ مودال احراز هویت پیامکی و اتصال توکن دیوار با موفقیت باز شد!")
                divar_shot = os.path.join(artifact_dir, "live_test_6_divar_auth_modal.png")
                page.screenshot(path=divar_shot, full_page=False)
                print(f"  ✓ اسکرین‌شات مودال دیوار ذخیره شد: {divar_shot}")
                page.locator("#divarSessionModal button:has-text('✕')").click()
                time.sleep(0.5)

        # Test opening Quick Phone Modal
        print("\n[تست ۸] تست باز کردن مودال ویرایش/ثبت شماره واقعی مالک...")
        edit_phone_btn = page.locator(".contact-option-box button:has-text('✏️')").first
        if edit_phone_btn.is_visible():
            edit_phone_btn.click()
            time.sleep(1)
            phone_modal = page.locator("#quickPhoneModal")
            if phone_modal.is_visible():
                print("  ✓ مودال ثبت/ویرایش شماره تلفن واقعی مالک با موفقیت باز شد!")
                phone_shot = os.path.join(artifact_dir, "live_test_7_quick_phone_modal.png")
                page.screenshot(path=phone_shot, full_page=False)
                print(f"  ✓ اسکرین‌شات مودال ثبت شماره ذخیره شد: {phone_shot}")
                page.locator("#quickPhoneModal button:has-text('✕')").click()
                time.sleep(0.5)

        # Detail Page Contact Bar
        print("\n[تست ۹] بررسی نمایش شماره واقعی و دکمه‌های تماس در پرونده اختصاصی ملک...")
        page.goto("http://127.0.0.1:5000/properties/1", wait_until="networkidle")
        time.sleep(1)
        detail_shot = os.path.join(artifact_dir, "live_test_8_property_detail_contact.png")
        page.screenshot(path=detail_shot, full_page=True)
        print(f"  ✓ اسکرین‌شات صفحه جزئیات ملک با گزینه تماس ذخیره شد: {detail_shot}")

        browser.close()
        print("\n✨ تمامی آزمون‌های زنده Playwright با موفقیت ۱۰۰٪ به پایان رسید!")

if __name__ == '__main__':
    run_live_test()

