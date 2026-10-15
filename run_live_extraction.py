"""
اجرای زنده و واقعی استخراج چندترده املاک دیوار با سلنیوم و بیوتیفول‌سوپ
پروژه سقف (Saghf Real Estate Platform)
مبتنی بر معماری ErfanNahidi/Divar_Property_Scraper با فیلتر ۱۰۰٪ مالک شخصی و ذخیره در دیتابیس
"""

import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath('.'))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from app import create_app, db
from database.models import Property, Owner, PropertyListing
from crawler.selenium_scraper.scraper import MultiThreadedDivarScraper
from crawler.selenium_scraper.browser import find_optimal_thread_count
from crawler.schemas import NormalizedPropertySchema
from crawler.dedup import dedup_engine


def main():
    print("=" * 70)
    print("🚀 سامانه استخراج زنده و چندترده آگهی‌های دیوار (سقف - نسخه سلنیوم و سوپ)")
    print("قواعد: ۱۰۰٪ مالک شخصی واقعی | صفر دیتای ماک | ذخیره در CSV و دیتابیس")
    print("=" * 70)

    app = create_app()

    target_count = 25
    thread_count = find_optimal_thread_count(max_cap=6)

    scraper = MultiThreadedDivarScraper(
        city="tehran",
        thread_count=thread_count,
        csv_output_path="divar_properties.csv"
    )

    db_saved = []

    def on_property_found(schema: NormalizedPropertySchema):
        """ذخیره آنی آگهی مالک شخصی در دیتابیس سامانه سقف"""
        with app.app_context():
            try:
                sid = schema.source_id
                existing = Property.query.filter_by(source_id=sid).first()
                if existing:
                    return

                # ایجاد یا تطبیق مالک
                owner = None
                phone = schema.owner_info.phone if schema.owner_info else ""
                if phone:
                    owner = Owner.query.filter_by(phone_number=phone).first()
                    if not owner:
                        owner = Owner(
                            full_name=schema.owner_info.name or f"مالک {schema.district}",
                            phone_number=phone,
                            urgency="high",
                            flexibility="moderate",
                            notes=f'<a href="{schema.source_url}" target="_blank">لینک آگهی</a>'
                        )
                        db.session.add(owner)
                        db.session.flush()

                prop = Property(
                    source="divar",
                    source_id=sid,
                    source_url=schema.source_url,
                    title=schema.title,
                    deal_type=schema.deal_type,
                    property_type=schema.property_type,
                    city=schema.city,
                    district=schema.district,
                    address=schema.address,
                    total_price=schema.total_price,
                    meter_price=schema.meter_price,
                    deposit=schema.deposit,
                    monthly_rent=schema.monthly_rent,
                    area=schema.area,
                    rooms=schema.rooms,
                    floor=schema.floor,
                    total_floors=schema.total_floors,
                    build_year=schema.build_year,
                    has_elevator=schema.has_elevator,
                    has_parking=schema.has_parking,
                    has_warehouse=schema.has_warehouse,
                    has_balcony=schema.has_balcony,
                    description=schema.description,
                    owner_id=owner.id if owner else None,
                    owner_type="personal",
                    is_personal_owner=True,
                    status="verified",
                    score=schema.score,
                    filter_log="استخراج چندترده سلنیوم و بیوتیفول‌سوپ"
                )
                db.session.add(prop)
                db.session.commit()
                db_saved.append(prop.id)
            except Exception as e:
                db.session.rollback()

    start_time = time.time()
    extracted_properties = scraper.run_multi_threaded_extraction(
        category_key='buy-apartment',
        target_count=target_count,
        on_item_found=on_property_found
    )

    # در صورت نیاز به تکمیل تا سقف ۲۵ مورد، جستجو در اجاره آپارتمان نیز اعمال می‌شود
    if len(extracted_properties) < 20:
        remaining = target_count - len(extracted_properties)
        print(f"\nتکمیل تا سقف درخواستی با استخراج {remaining} آگهی از رهن و اجاره آپارتمان...")
        rent_props = scraper.run_multi_threaded_extraction(
            category_key='rent-apartment',
            target_count=remaining,
            on_item_found=on_property_found
        )
        extracted_properties.extend(rent_props)

    total_time = time.time() - start_time

    print("\n" + "=" * 70)
    print(f"📊 گزارش جامع استخراج نهایی:")
    print(f"کل فایل‌های مالک شخصی استخراج‌شده: {len(extracted_properties)}")
    print(f"تعداد ثبت‌شده در دیتابیس سقف: {len(db_saved)}")
    print(f"فایل ذخیره CSV: divar_properties.csv")
    print(f"زمان کل اجرا: {total_time:.2f} ثانیه")
    print("=" * 70)

    print("\n📋 لیست فایل‌های استخراج‌شده مالک شخصی با لینک مستقیم:")
    for idx, item in enumerate(extracted_properties[:30]):
        deal_desc = f"{item.total_price:,} تومان" if item.deal_type == 'sale' else f"رهن: {item.deposit:,} | اجاره: {item.monthly_rent:,}"
        phone_desc = item.owner_info.phone if (item.owner_info and item.owner_info.phone) else "تماس درون‌برنامه‌ای دیوار"
        print(f"\n[{idx+1}] 🏠 {item.title}")
        print(f"    📐 متراژ: {item.area} متر | 🛏️ خواب: {item.rooms} | 🏢 طبقه: {item.floor} | 🏗️ ساخت: {item.build_year}")
        print(f"    📍 محله: {item.district} | 💰 قیمت/شرایط: {deal_desc}")
        print(f"    📞 مالک: {phone_desc}")
        print(f"    🔗 <a href=\"{item.source_url}\" target=\"_blank\">لینک آگهی</a>")


if __name__ == "__main__":
    main()
