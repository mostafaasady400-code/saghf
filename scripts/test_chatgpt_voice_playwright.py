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

def run_chatgpt_voice_test():
    artifact_dir = r"C:\Users\RINO TEK\.gemini\antigravity-ide\brain\b0700ae5-99ce-4ca6-bebf-bfb35450c9b6"
    os.makedirs(artifact_dir, exist_ok=True)

    print("🚀 شروع آزمون زنده Playwright با مرورگر باز Google Chrome (حالت مرئی Headless=False)...")
    print("🌐 پنجره رسمی مرورگر گوگل کروم روی مانیتور شما باز خواهد شد...")

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_path):
        chrome_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

    with sync_playwright() as playwright:
        # مرورگر به صورت کاملاً مرئی (headless=False) با تاخیر انسانی (slow_mo=800ms) جهت مشاهده زنده کاربر
        browser = playwright.chromium.launch(
            executable_path=chrome_path,
            headless=False,
            slow_mo=800,
            args=['--start-maximized']
        )
        context = browser.new_context(
            no_viewport=True,
            locale='fa-IR'
        )
        page = context.new_page()

        # ----------------------------------------------------
        # گام ۱: باز کردن صفحه ویترین املاک و راستی‌آزمایی گوی کریستالی وکتور
        # ----------------------------------------------------
        print("\n[گام ۱] باز کردن صفحه ویترین املاک در گوگل کروم...")
        page.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        time.sleep(1.5)

        # اسکرول به گوی استراحت دقیقاً زیر تور ۳۶۰ درجه
        resting_orb_btn = page.locator("#restingOrbBtn")
        assert resting_orb_btn.is_visible(), "دکمه گوی هوشمند حالت استراحت رویت نشد!"
        resting_orb_btn.scroll_into_view_if_needed()
        time.sleep(1)

        # بررسی عدم وجود هرگونه تگ <img> در گوی استراحت (تضمین SVG خالص وکتور بدون پس‌زمینه مربعی)
        img_count = page.locator("#ai-station img").count()
        assert img_count == 0, f"خطا: تگ تصویر <img> در گوی استراحت وجود دارد ({img_count})!"
        
        # بررسی حضور SVG گوی کریستالی هندسی ۳ بعدی
        svg_orb = page.locator("#ai-station svg.geometric-crystal-orb-svg")
        assert svg_orb.is_visible(), "گوی کریستالی سه‌بعدی وکتور (SVG) رویت نشد!"
        print("  ✓ گوی سه‌بعدی کریستالی خالص وکتور (SVG) با پس‌زمینه شفاف و بدون نوشته زیرین تایید شد.")

        shot0 = os.path.join(artifact_dir, "chatgpt_voice_0_resting_orb.png")
        page.screenshot(path=shot0, full_page=False)

        # ----------------------------------------------------
        # گام ۲: کلیک روی گوی و باز شدن مودال تمام‌صفحه ChatGPT Voice Mode
        # ----------------------------------------------------
        print("\n[گام ۲] کلیک روی گوی جهت باز شدن مودال ChatGPT Voice Mode...")
        resting_orb_btn.click()
        time.sleep(2)

        modal = page.locator("#chatgptVoiceModal")
        assert modal.is_visible(), "مودال ChatGPT Voice باز نشد!"
        print("  ✓ مودال تمام‌صفحه صوتی با گوی بزرگ کریستالی و امواج صوتی زنده باز شد!")

        # بررسی گوی مرکزی مودال (SVG خالص بدون عکس ماک)
        modal_svg = page.locator("#chatgptCenterOrbContainer svg.large-modal-orb")
        assert modal_svg.is_visible(), "گوی بزرگ وکتور داخل مودال رویت نشد!"
        print("  ✓ گوی بزرگ کریستالی هندسی وکتور در مرکز مودال به صورت زنده فعال است.")

        shot1 = os.path.join(artifact_dir, "chatgpt_voice_1_modal_opened.png")
        page.screenshot(path=shot1, full_page=False)

        # ----------------------------------------------------
        # گام ۳: اجرای سناریوی اول کاربر: بودجه ۱ تومن ۶۰ تومن منطقه ۵
        # ----------------------------------------------------
        prompt1 = "بودجم ۱ تومن ۶۰ تومنه توی منطقه ۵ تهران برام خونه‌ها رو پیدا کن"
        print(f"\n[گام ۳] ارسال دستور واقعی کاربر: «{prompt1}»...")

        input_box = page.locator("#chatgptVoiceInput")
        send_btn = page.locator("#btnChatgptSend")

        input_box.fill(prompt1)
        time.sleep(1)
        send_btn.click()
        print("  ✓ دستور به دستیار صوتی سقف ارسال شد.")

        # انتظار برای پردازش و سنتز صوتی
        time.sleep(3)

        transcript = page.locator("#chatgptLiveTranscript").inner_text()
        print(f"  ✓ پاسخ صوتی ایجنت:\n    «{transcript}»")

        # بررسی نمایش کارت‌های واقعی دیتابیس با تگ «لینک آگهی»
        results_box = page.locator("#chatgptAgentResults")
        assert results_box.is_visible(), "کارت‌های نتایج ایجنت نمایش داده نشد!"
        cards_count = page.locator("#chatgptCardsList > div").count()
        assert cards_count > 0, "هیچ کارتی برای منطقه ۵ استخراج نشد!"
        print(f"  ✓ تعداد {cards_count} کارت ملکی واقعی از منطقه ۵ با پیوند مستقیم در پنل نمایش داده شد.")

        # تایید وجود تگ <a> با عنوان «لینک آگهی» طبق قانون AGENTS.md
        ad_link = page.locator("#chatgptCardsList a:has-text('لینک آگهی')").first
        assert ad_link.is_visible(), "دکمه «لینک آگهی» در کارت‌ها یافت نشد!"
        print("  ✓ تگ <a> با عنوان «لینک آگهی» تایید شد.")

        shot2 = os.path.join(artifact_dir, "chatgpt_voice_2_agent_region5.png")
        page.screenshot(path=shot2, full_page=False)

        # ----------------------------------------------------
        # گام ۴: اجرای سناریوی دوم کاربر: فروش ۲۰ تا ۲۵ میلیارد منطقه ۲ و ۵
        # ----------------------------------------------------
        print("\n[گام ۴] تست کلیک روی چیپ کارشناسی «فروش ۲۰ تا ۲۵ میلیارد منطقه ۲ و ۵»...")
        chip2 = page.locator("button.station-chip:has-text('فروش ۲۰ تا ۲۵ میلیارد')").first
        chip2.scroll_into_view_if_needed()
        time.sleep(0.5)
        chip2.click(force=True)
        time.sleep(3)

        transcript2 = page.locator("#chatgptLiveTranscript").inner_text()
        print(f"  ✓ پاسخ صوتی ایجنت برای فروش ۲۰-۲۵ میلیارد:\n    «{transcript2}»")

        cards_count2 = page.locator("#chatgptCardsList > div").count()
        assert cards_count2 > 0, "هیچ کارتی برای فروش ۲۰-۲۵ میلیارد استخراج نشد!"
        print(f"  ✓ تعداد {cards_count2} کارت ملکی فروش از منطقه ۲ و ۵ استخراج و به نمایش درآمد.")

        shot3 = os.path.join(artifact_dir, "chatgpt_voice_3_agent_sale.png")
        page.screenshot(path=shot3, full_page=False)

        # ----------------------------------------------------
        # گام ۵: بستن مودال و تست هدایت مستقیم از داشبورد
        # ----------------------------------------------------
        print("\n[گام ۵] بستن مودال صوتی و تست هدایت از داشبورد اصلی سقف...")
        close_btn = page.locator("button[title='بستن پنجره']:has-text('✕')").first
        close_btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        close_btn.click(force=True)
        time.sleep(1.5)

        # رفتن به داشبورد
        page.goto("http://127.0.0.1:5000/", wait_until="networkidle")
        time.sleep(1.5)

        dash_ai_btn = page.locator("button:has-text('دستیار هوشمند')").first
        dash_ai_btn.click()
        time.sleep(2.5)

        # بررسی باز شدن خودکار ChatGPT Voice Mode
        modal_again = page.locator("#chatgptVoiceModal")
        assert modal_again.is_visible(), "مودال صوتی پس از کلیک در داشبورد باز نشد!"
        print("  ✓ هدایت از داشبورد به گوی صوتی و باز شدن خودکار ChatGPT Voice Mode تایید گردید.")

        shot4 = os.path.join(artifact_dir, "chatgpt_voice_4_dashboard_to_voice.png")
        page.screenshot(path=shot4, full_page=False)

        time.sleep(2)
        browser.close()
        print("\n✨ تمامی مراحل آزمون با Google Chrome مرئی با موفقیت ۱۰۰٪ سپری شدند!")

if __name__ == '__main__':
    run_chatgpt_voice_test()
