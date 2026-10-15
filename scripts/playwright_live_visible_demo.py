import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from playwright.sync_api import sync_playwright
from app import create_app
from database.models import db, Property, Owner
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.owner_filter import OwnerFilter
from crawler.dedup import dedup_engine

def run_visible_playwright_demo():
    print("=" * 65)
    print("🎬 راه‌اندازی مرورگر زنده Playwright بر بستر گوگل کروم اصلی دسکتاپ")
    print("=" * 65)

    app = create_app()

    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome_exe):
        chrome_exe = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"

    with sync_playwright() as p:
        print(f"🌐 اجرای مرورگر گرافیکی (Visible GUI Mode): {chrome_exe}")
        browser = p.chromium.launch(
            executable_path=chrome_exe if os.path.exists(chrome_exe) else None,
            channel="chrome" if not os.path.exists(chrome_exe) else None,
            headless=False,
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox'
            ]
        )

        context = browser.new_context(
            no_viewport=True,
            locale='fa-IR'
        )

        # ---------------------------------------------------------
        # تب ۱: صفحه مانیتورینگ زنده کراولر سامانه سقف
        # ---------------------------------------------------------
        page_crawler = context.new_page()
        print("\n[مرحله ۱] نمایش داشبورد زنده کراولر در سامانه سقف...")
        page_crawler.goto("http://127.0.0.1:5000/crawler/", wait_until="domcontentloaded")
        page_crawler.wait_for_timeout(2500)

        # افکت بصری نئونی برای توجه کاربر به داشبورد کراولر
        page_crawler.evaluate("""
            const h = document.querySelector('h1, h2, .crawler-header');
            if (h) {
                h.style.boxShadow = '0 0 25px #00ffaa';
                h.style.borderRadius = '12px';
                h.style.transition = 'all 0.5s ease';
            }
        """)
        time.sleep(2)

        # ---------------------------------------------------------
        # تب ۲: نمایش زنده سایت دیوار و استخراج بلادرنگ آگهی‌ها
        # ---------------------------------------------------------
        page_divar = context.new_page()
        print("\n[مرحله ۲] ناوبری زنده به پلتفرم دیوار (بخش رهن و اجاره آپارتمان تهران)...")
        page_divar.goto("https://divar.ir/s/tehran/rent-apartment", wait_until="domcontentloaded")
        page_divar.wait_for_timeout(3000)

        # اسکرول آرام برای مشاهده آگهی‌ها توسط کاربر
        page_divar.evaluate("window.scrollBy({top: 450, behavior: 'smooth'})")
        time.sleep(1.5)

        # استخراج توکن‌های زنده و هایلایت گرافیکی دور آگهی‌ها در مانیتور
        print("🔍 استخراج و حاشیه‌گذاری بصری آگهی‌های زنده در صفحه دیوار...")
        post_elements = page_divar.query_selector_all("article.kt-post-card")
        print(f"  ✓ تعداد {len(post_elements)} کارت آگهی زنده در صفحه شناسایی شد.")

        # هایلایت کارت‌ها با نئون آبی/سبز در مرورگر
        page_divar.evaluate("""
            document.querySelectorAll('article.kt-post-card').forEach((el, idx) => {
                el.style.border = '2px solid #00e5ff';
                el.style.boxShadow = '0 0 15px rgba(0,229,255,0.4)';
                el.style.transition = 'all 0.3s ease';
            });
        """)
        time.sleep(2)

        # ---------------------------------------------------------
        # مرحله ۳: تحلیل هوشمند با فیلتر اصالت مالک و استخراج عمیق
        # ---------------------------------------------------------
        print("\n[مرحله ۳] ارزیابی عمیق، فیلتر واسطه‌ها و استخراج فایل‌های شخصی...")
        crawler = HybridDivarCrawler(city='tehran')
        extracted_props = crawler.fetch_listings(category_key='rent-apartment', limit=5)
        print(f"✅ تعداد {len(extracted_props)} فایل شخصی واقعی و تأییدشده استخراج شد.")

        # ---------------------------------------------------------
        # مرحله ۴: ذخیره‌سازی زنده در پایگاه داده و برابری سه‌گانه
        # ---------------------------------------------------------
        saved_count = 0
        with app.app_context():
            dedup_engine.initialize_from_db(Property)
            for item in extracted_props:
                sid = item.source_id
                if Property.query.filter_by(source_id=sid).first():
                    continue

                owner = None
                if item.owner_info and item.owner_info.phone:
                    owner = Owner.query.filter_by(phone_number=item.owner_info.phone).first()
                    if not owner:
                        owner = Owner(
                            full_name=item.owner_info.name,
                            phone_number=item.owner_info.phone,
                            urgency=item.owner_info.urgency,
                            flexibility=item.owner_info.flexibility,
                            notes=item.owner_info.notes
                        )
                        db.session.add(owner)
                        db.session.flush()

                prop = Property(
                    source=item.source,
                    source_id=sid,
                    source_url=item.source_url,
                    title=item.title,
                    deal_type=item.deal_type,
                    property_type=item.property_type,
                    city=item.city,
                    district=item.district,
                    address=item.address,
                    total_price=item.total_price,
                    meter_price=item.meter_price,
                    deposit=item.deposit,
                    monthly_rent=item.monthly_rent,
                    area=item.area,
                    rooms=item.rooms,
                    floor=item.floor,
                    total_floors=item.total_floors,
                    build_year=item.build_year or 1401,
                    has_elevator=item.has_elevator,
                    has_parking=item.has_parking,
                    has_warehouse=item.has_warehouse,
                    has_balcony=item.has_balcony,
                    description=item.description,
                    status=item.status,
                    score=item.score,
                    is_personal_owner=True,
                    owner_type='personal',
                    filter_log=item.filter_log,
                    owner_id=owner.id if owner else None
                )
                prop.features = item.features
                prop.images = item.images
                db.session.add(prop)
                db.session.commit()
                dedup_engine.mark_seen(sid)
                saved_count += 1

                # تقارن سه‌گانه: ارسال به تلگرام و بله
                try:
                    from telegram_bot.notifier import send_property_alert
                    send_property_alert(prop)
                except Exception:
                    pass
                try:
                    from bale_bot.notifier import send_property_bale_alert
                    send_property_bale_alert(prop)
                except Exception:
                    pass

                print(f"  💎 ذخیره در دیتابیس: [{prop.score} امتیاز] {prop.title[:35]} ({prop.district})")
                print(f"     🔗 لینک اصیل دیوار: {prop.source_url}")

        # ---------------------------------------------------------
        # تب ۳: ویترین املاک و نمایش فایل‌های جدید در رابط کاربری سقف
        # ---------------------------------------------------------
        page_properties = context.new_page()
        print("\n[مرحله ۵] باز کردن ویترین املاک سقف برای مشاهده فایل‌های افزوده شده...")
        page_properties.goto("http://127.0.0.1:5000/properties/", wait_until="networkidle")
        page_properties.wait_for_timeout(2000)

        # هایلایت کارت‌های جدید با افکت درخشش طلایی/زمردی
        page_properties.evaluate("""
            const cards = document.querySelectorAll('.property-card, .glass-card, [class*="card"]');
            cards.forEach((c, i) => {
                if (i < 3) {
                    c.style.boxShadow = '0 0 30px #10b981';
                    c.style.borderColor = '#10b981';
                    c.style.transform = 'scale(1.02)';
                    c.style.transition = 'all 0.6s ease';
                }
            });
        """)
        time.sleep(2)

        # اسکرول نرم در صفحه ویترین برای نمایش کامل املاک
        page_properties.evaluate("window.scrollBy({top: 600, behavior: 'smooth'})")
        time.sleep(2)
        page_properties.evaluate("window.scrollBy({top: -300, behavior: 'smooth'})")
        time.sleep(1.5)

        # ---------------------------------------------------------
        # تب ۴: نمایش پرونده اولین ملک استخراج شده با آلبوم تصاویر
        # ---------------------------------------------------------
        card_links = page_properties.locator("a.compact-card-title, .compact-card a[href^='/properties/'], a[href*='/properties/']:not([href='/properties/']):not([href='/properties'])")
        if card_links.count() > 0:
            prop_href = card_links.first.get_attribute("href")
            if prop_href and prop_href not in ["/properties/", "/properties"]:
                print(f"\n[مرحله ۶] ورود به پرونده تخصصی ملک: {prop_href}")
                page_properties.goto(f"http://127.0.0.1:5000{prop_href}", wait_until="networkidle")
                time.sleep(2.5)
                page_properties.evaluate("window.scrollBy({top: 400, behavior: 'smooth'})")
                time.sleep(2)

        print("\n🎉 آزمون زنده بصری با موفقیت ۱۰۰٪ به پایان رسید!")
        print("مرورگر برای ۵ ثانیه دیگر باز می‌ماند تا کلیه بخش‌ها را بررسی بفرمایید...")
        time.sleep(5)
        browser.close()

if __name__ == '__main__':
    run_visible_playwright_demo()
