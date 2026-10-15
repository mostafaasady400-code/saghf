import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import db
from database.models import Property, PropertyListing
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.owner_filter import OwnerFilter
from crawler.dedup import dedup_engine

app = create_app()

with app.app_context():
    print(f"[CrawlTest] تعداد املاک اولیه در دیتابیس: {Property.query.count()}")
    dedup_engine.initialize_from_db(Property)
    crawler = HybridDivarCrawler()

    # واکشی فایل‌های واقعی رهن و اجاره منطقه ۵ (پونک و جنت‌آباد)
    results = crawler.fetch_listings(
        category_key='rent-apartment',
        limit=12,
        districts=['پونک', 'جنت آباد']
    )
    print(f"[CrawlTest] تعداد {len(results)} آگهی از دیوار دریافت شد.")

    saved = 0
    for r in results:
        # فیلتر سخت‌گیرانه عدم ورود املاک و همخونه
        fres = OwnerFilter.evaluate('divar', r.title, r.description, raw_text=f"{r.title} {r.description}")
        if not fres.is_personal:
            print(f"[CrawlTest] ❌ رد شد: {r.title[:35]} ({fres.reason})")
            continue

        is_direct = OwnerFilter.is_direct_owner_declared(r.title, r.description)
        score = 99 if is_direct else 90
        district_name = r.district or 'پونک'
        if 'منطقه ۵' not in district_name:
            district_name = f"{district_name} (منطقه ۵)"

        prop = Property(
            title=r.title,
            description=r.description,
            deal_type='rent',
            property_type='apartment',
            total_price=0,
            deposit=r.deposit or 600000000,
            monthly_rent=r.monthly_rent or 20000000,
            area=r.area or 85,
            rooms=r.rooms or 2,
            city='تهران',
            district=district_name,
            address=f"تهران، منطقه ۵، {r.district or 'پونک'}",
            has_parking=r.has_parking,
            has_elevator=r.has_elevator,
            has_warehouse=r.has_warehouse,
            has_balcony=r.has_balcony,
            source='divar',
            source_id=r.source_id,
            source_url=r.source_url,
            score=score
        )
        prop.images = r.images if isinstance(r.images, list) else []
        db.session.add(prop)
        db.session.flush()

        ad_code = str(r.source_id).replace('divar_', '')[-8:]
        pl = PropertyListing(
            ad_code=ad_code,
            source='divar',
            source_url=r.source_url,
            title=r.title,
            description=r.description,
            city='تهران',
            region='5',
            district=district_name,
            deal_type='rent',
            deposit=prop.deposit,
            monthly_rent=prop.monthly_rent,
            total_price=prop.total_price,
            area=prop.area,
            rooms=prop.rooms,
            is_personal_owner=True
        )
        pl.images = prop.images
        db.session.add(pl)
        saved += 1
        print(f"[CrawlTest] ✅ ذخیره شد: {prop.title[:35]} | {prop.district} | {prop.area}متر | {prop.source_url}")

    db.session.commit()
    print(f"[CrawlTest] پایان: تعداد {saved} ملک واقعی مالک در دیتابیس ثبت شد. موجودی کل: {Property.query.count()}")
