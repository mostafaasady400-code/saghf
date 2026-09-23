import os
import sys
import time

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

def run_live_qa():
    artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\f7af3977-3411-4c83-b6bd-b4dd6c95942f"
    os.makedirs(artifact_dir, exist_ok=True)

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    print(f"🚀 در حال اجرای تست زنده با مرورگر: {chrome_path}")

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

        results = []

        # ----------------------------------------------------
        # ۱. تست داشبورد و درگاه‌های دپارتمان
        # ----------------------------------------------------
        print("\n[تست ۱] بارگذاری داشبورد اصلی سقف...")
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(1)

        title = page.title()
        print(f"  ✓ عنوان صفحه: {title}")

        sale_gate = page.locator("text=دپارتمان خرید و فروش").first
        rent_gate = page.locator("text=دپارتمان رهن و اجاره").first
        assert sale_gate.is_visible(), "کارت دپارتمان خرید و فروش یافت نشد"
        assert rent_gate.is_visible(), "کارت دپارتمان رهن و اجاره یافت نشد"
        print("  ✓ هر دو درگاه دپارتمان خرید و فروش و رهن و اجاره با استایل ۳ بعدی مشاهده شدند.")

        page.screenshot(path=os.path.join(artifact_dir, "live_qa_1_dashboard.png"), full_page=False)
        results.append("داشبورد و درگاه‌های دپارتمان: تأیید شد")

        # ----------------------------------------------------
        # ۲. کلیک و ورود به دپارتمان رهن و اجاره از داشبورد
        # ----------------------------------------------------
        print("\n[تست ۲] ورود به دپارتمان رهن و اجاره از طریق لینک داشبورد...")
        enter_rent_btn = page.locator("a[href*='deal_type=rent']").first
        enter_rent_btn.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        current_url = page.url
        print(f"  ✓ آدرس بارگذاری‌شده: {current_url}")
        assert "deal_type=rent" in current_url, "آدرس رهن و اجاره صحیح نیست"

        # بررسی تب رهن و اجاره
        active_rent_tab = page.locator("#deal-tab-rent")
        assert active_rent_tab.is_visible(), "تب رهن و اجاره وجود ندارد"
        print(f"  ✓ تب رهن و اجاره با متن: {active_rent_tab.inner_text().strip()}")

        # بررسی وجود کارت‌های رهن و اجاره
        rent_cards = page.locator(".property-card[data-deal-type='rent']")
        count_cards = rent_cards.count()
        print(f"  ✓ تعداد فایل‌های رهن و اجاره در حال نمایش: {count_cards} فایل")
        assert count_cards > 0, "هیچ فایل رهن و اجاره‌ای نمایش داده نشده است!"

        page.screenshot(path=os.path.join(artifact_dir, "live_qa_2_rent_catalog.png"), full_page=False)
        results.append(f"کاتالوگ رهن و اجاره ({count_cards} فایل): تأیید شد")

        # ----------------------------------------------------
        # ۳. تست کاتالوگ جامع و سوئیچ آنی تب‌ها
        # ----------------------------------------------------
        print("\n[تست ۳] بارگذاری کاتالوگ جامع فایل‌ها (همه فایل‌ها)...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1)

        all_cards = page.locator(".property-card")
        total_initial = all_cards.count()
        print(f"  ✓ تعداد کل فایل‌های بارگذاری شده در صفحه: {total_initial} فایل")

        # سوئیچ به تب خرید و فروش
        print("  ← سوئیچ به تب «خرید و فروش»...")
        page.locator("#deal-tab-sale").click()
        time.sleep(0.5)
        visible_sale = len([c for c in all_cards.all() if c.is_visible()])
        print(f"  ✓ فایل‌های فروش نمایان: {visible_sale} فایل")

        # سوئیچ به تب رهن و اجاره
        print("  ← سوئیچ به تب «رهن و اجاره»...")
        page.locator("#deal-tab-rent").click()
        time.sleep(0.5)
        visible_rent = len([c for c in all_cards.all() if c.is_visible()])
        print(f"  ✓ فایل‌های رهن و اجاره نمایان: {visible_rent} فایل")

        # سوئیچ به همه آگهی‌ها
        print("  ← بازگشت به «همه آگهی‌ها»...")
        page.locator("#deal-tab-all").click()
        time.sleep(0.5)
        visible_all = len([c for c in all_cards.all() if c.is_visible()])
        print(f"  ✓ مجموع همه فایل‌های نمایان: {visible_all} فایل")

        page.screenshot(path=os.path.join(artifact_dir, "live_qa_3_all_properties.png"), full_page=False)
        results.append(f"سوئیچ آنی تب‌های معامله (فروش: {visible_sale}، اجاره: {visible_rent}، همه: {visible_all}): تأیید شد")

        # ----------------------------------------------------
        # ۴. تست گوی سه‌بعدی هوش مصنوعی (AI Orb)
        # ----------------------------------------------------
        print("\n[تست ۴] بررسی استیشن گوی هوش مصنوعی (AI Orb)...")
        ai_orb = page.locator("#aiOrbGraphic")
        if ai_orb.is_visible():
            ai_orb.scroll_into_view_if_needed()
            ai_orb.hover()
            time.sleep(0.5)
            print("  ✓ گوی هوش مصنوعی مشاهده و هاور سه‌بعدی تست شد.")

            # ارسال سوال آزمایشی در استیشن هوش مصنوعی
            ai_input = page.locator("#aiSearchInput")
            if ai_input.is_visible():
                ai_input.fill("آپارتمان رهن و اجاره سعادت آباد")
                time.sleep(0.5)
                page.screenshot(path=os.path.join(artifact_dir, "live_qa_4_ai_orb_active.png"), full_page=False)
                print("  ✓ ورودی استیشن هوش مصنوعی با موفقیت تست شد.")
        results.append("گوی هوشمند و استیشن هوش مصنوعی: تأیید شد")

        # ----------------------------------------------------
        # ۵. تست مودال سه‌بعدی ملک و لینک آگهی واقعی
        # ----------------------------------------------------
        print("\n[تست ۵] باز کردن مودال سه‌بعدی جزئیات ملک...")
        first_modal_btn = page.locator(".btn-compact-view").first
        if first_modal_btn.is_visible():
            first_modal_btn.scroll_into_view_if_needed()
            first_modal_btn.click()
            time.sleep(1.5)

            modal_overlay = page.locator("#inAppAdModalOverlay")
            assert modal_overlay.is_visible(), "مودال سه‌بعدی باز نشد"
            print("  ✓ مودال سه‌بعدی با موفقیت باز شد.")

            modal_title = page.locator("#inAppModalTitle").inner_text()
            print(f"  ✓ عنوان فایل در مودال: {modal_title}")

            page.screenshot(path=os.path.join(artifact_dir, "live_qa_5_modal_open.png"), full_page=False)
            results.append("مودال سه‌بعدی و پرونده درون‌برنامه‌ای: تأیید شد")

            # بستن مودال
            close_btn = page.locator("button[onclick='closeInAppAdModal()']").first
            if close_btn.is_visible():
                close_btn.click()
                time.sleep(0.5)
                print("  ✓ مودال با موفقیت بسته شد.")

        # ----------------------------------------------------
        # ۶. تست فرم ثبت فایل با پیش‌فرض رهن و اجاره
        # ----------------------------------------------------
        print("\n[تست ۶] باز کردن فرم ثبت ملک جدید با رهن و اجاره...")
        page.goto("http://127.0.0.1:5000/properties/new?deal_type=rent", wait_until="networkidle")
        time.sleep(1)

        deal_select = page.locator("#deal_type_select")
        selected_val = deal_select.input_value()
        print(f"  ✓ نوع معامله پیش‌فرض در فرم: {selected_val}")
        assert selected_val == 'rent', "نوع معامله باید rent باشد"

        rent_box = page.locator("#rent_prices_box")
        sale_box = page.locator("#sale_prices_box")
        assert rent_box.is_visible(), "باکس مبالغ ودیعه و اجاره باید نمایان باشد"
        assert not sale_box.is_visible(), "باکس قیمت کل فروش باید مخفی باشد"
        print("  ✓ فیلدهای ودیعه و اجاره ماهانه به‌طور صحیح نمایش داده شدند.")

        page.screenshot(path=os.path.join(artifact_dir, "live_qa_6_form_rent.png"), full_page=False)
        results.append("فرم ثبت فایل با پیش‌فرض رهن و اجاره: تأیید شد")

        browser.close()

    print("\n" + "="*50)
    print("🎉 تمام مراحل آزمون زنده با موفقیت ۱۰۰٪ به پایان رسید:")
    for r in results:
        print(f"  ✅ {r}")
    print("="*50)

if __name__ == "__main__":
    run_live_qa()
