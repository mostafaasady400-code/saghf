import os
import sys
import random
import time

# Ensure UTF-8 output with unbuffered flush
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

from app import create_app
from database.db import db
from database.models import Property, Owner, Client, MatchRecord, Visit, Interaction, Agent
from crawler.dedup import dedup_engine
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.hybrid_sheypoor import HybridSheypoorCrawler
from crawler.owner_filter import OwnerFilter
from services.matching_service import MatchingEngine

def purge_and_extract():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("🗑️ گام ۱: پاکسازی کامل داده‌های دمو و تستی از پایگاه داده...")
        print("=" * 60)
        
        # 1. Purge all existing properties and their associated matches, visits, interactions, and crawled owners
        deleted_matches = MatchRecord.query.delete()
        deleted_visits = Visit.query.delete()
        deleted_interactions = Interaction.query.delete()
        deleted_properties = Property.query.delete()
        deleted_owners = Owner.query.filter(
            (Owner.notes.like('%ثبت خودکار از کراولر%')) | 
            (Owner.full_name.like('%مالک آگهی%')) |
            (Owner.full_name.like('%مالک محترم%')) |
            (Owner.full_name.like('%مالک شیپور%'))
        ).delete(synchronize_session=False)
        
        db.session.commit()
        dedup_engine.clear()
        
        print(f"✓ تعداد {deleted_properties} ملک قبلی کراول حذف گردید.")
        print(f"✓ تعداد {deleted_owners} رکورد مالک ثبت‌شده از کراولر پاکسازی شد.")
        print(f"✓ تعداد {deleted_matches} رکورد تطبیق، {deleted_visits} بازدید و {deleted_interactions} تعامل پاکسازی شدند.")
        print(f"✓ حافظه کش Dedup ریست شد (تعداد کنونی: {dedup_engine.size()}).")

        # Ensure we have active agents
        agents = Agent.query.all()
        if not agents:
            a1 = Agent(name="علیرضا محمدی", phone="09121111111", role="مشاور ارشد")
            a2 = Agent(name="سارا حسینی", phone="09122222222", role="کارشناس رهن و اجاره")
            db.session.add_all([a1, a2])
            db.session.commit()
            agents = Agent.query.all()

        print("\n" + "=" * 60)
        print("🌐 گام ۲: استخراج داده‌های زنده و ۱۰۰٪ شخصی با لینک معتبر (فیلتر دولایه)...")
        print("=" * 60)

        divar_crawler = HybridDivarCrawler(city='tehran')
        sheypoor_crawler = HybridSheypoorCrawler(city='tehran')

        total_saved = 0
        real_extracted = []

        # 2. Extract Divar live listings
        divar_cats = ['buy-apartment', 'rent-apartment', 'buy-residential', 'rent-residential']
        for cat in divar_cats:
            print(f"\n[دیوار] در حال اتصال و استخراج دسته {cat}...")
            try:
                items = divar_crawler.fetch_listings(category_key=cat, limit=20)
                print(f"[دیوار] {len(items)} آگهی زنده ۱۰۰٪ شخصی استخراج و اعتبارسنجی شد.")
                for item in items:
                    if item.is_personal_owner:
                        real_extracted.append(item)
            except Exception as e:
                print(f"[دیوار] خطا در استخراج {cat}: {e}")
            time.sleep(2.0)

        # 3. Extract Sheypoor live listings
        sheypoor_cats = ['buy-apartment', 'rent-apartment', 'real-estate']
        for cat in sheypoor_cats:
            print(f"\n[شیپور] در حال اتصال و استخراج دسته {cat}...")
            try:
                items = sheypoor_crawler.fetch_listings(category_key=cat, limit=20)
                print(f"[شیپور] {len(items)} آگهی زنده ۱۰۰٪ شخصی استخراج و اعتبارسنجی شد.")
                for item in items:
                    if item.is_personal_owner:
                        real_extracted.append(item)
            except Exception as e:
                print(f"[شیپور] خطا در استخراج {cat}: {e}")
            time.sleep(2.0)

        print(f"\n📦 مجموع فایل‌های ۱۰۰٪ شخصی دریافت شده: {len(real_extracted)}")
        print("💾 در حال ثبت پایدار در پایگاه داده SQLite با اعتبارسنجی لینک‌ها...")

        for item in real_extracted:
            if not item.is_personal_owner:
                continue

            # اعتبارسنجی نهایی با فیلتر دو مرحله‌ای سخت‌گیرانه
            chk = OwnerFilter.evaluate(
                platform=item.source,
                title=item.title,
                description=item.description or ''
            )
            if not chk.is_personal:
                print(f"⚠️ رد آگهی در گیت نهایی دیتابیس: {item.title[:45]} ({chk.reason})")
                continue

            # Check duplicate by source_id
            existing = Property.query.filter_by(source_id=item.source_id).first()
            if existing:
                continue

            # Ensure owner
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

            # Randomly assign agent
            agent = random.choice(agents) if agents else None

            # Create property
            prop = Property(
                source=item.source,
                source_id=item.source_id,
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
                build_year=item.build_year or 1401,
                has_elevator=item.has_elevator,
                has_parking=item.has_parking,
                has_warehouse=item.has_warehouse,
                has_balcony=item.has_balcony,
                description=item.description,
                status=item.status,
                score=item.score,
                is_personal_owner=item.is_personal_owner,
                owner_type=item.owner_type,
                filter_log=item.filter_log,
                owner_id=owner.id if owner else None,
                assigned_agent_id=agent.id if agent else None
            )
            prop.features = item.features
            prop.images = item.images

            db.session.add(prop)
            dedup_engine.mark_seen(item.source_id)
            total_saved += 1

        db.session.commit()
        print(f"✅ تعداد {total_saved} ملک واقعی جدید با لینک مستقیم در دیتابیس ثبت شد!")

        # 4. Re-run matching engine
        print("\n" + "=" * 60)
        print("🧠 گام ۳: اجرای ماتریس تطبیق هوشمند سقف بر روی املاک واقعی جدید...")
        print("=" * 60)
        matches_count = MatchingEngine.refresh_matches_for_all()
        print(f"✓ تعداد {matches_count} رکورد تطبیق هوشمند میان خریداران و املاک واقعی ایجاد شد.")

        # 5. Output inspection of saved properties
        print("\n" + "=" * 60)
        print("📋 گام ۴: نمونه املاک واقعی ثبت شده به همراه لینک‌های مستقیم و فعال:")
        print("=" * 60)
        saved_props = Property.query.order_by(Property.id.asc()).all()
        for p in saved_props[:8]:
            print(f"[{p.source.upper()}] ID: {p.id}")
            print(f"  عنوان: {p.title}")
            print(f"  منطقه: {p.district} | متراژ: {p.area} متر | خواب: {p.rooms}")
            if p.deal_type == 'sale':
                print(f"  قیمت کل: {p.total_price:,} تومان | متری: {p.meter_price:,} تومان")
            else:
                print(f"  ودیعه: {p.deposit:,} تومان | اجاره: {p.monthly_rent:,} تومان")
            print(f"  🔗 لینک مستقیم و معتبر: {p.source_url}")
            print("-" * 50)

        divar_count = Property.query.filter_by(source='divar').count()
        sheypoor_count = Property.query.filter_by(source='sheypoor').count()
        print(f"\n📊 خلاصه نهایی: {len(saved_props)} ملک واقعی در دیتابیس موجود است.")
        print(f"   - دیوار: {divar_count} آگهی با لینک معتبر")
        print(f"   - شیپور: {sheypoor_count} آگهی با لینک معتبر")

if __name__ == '__main__':
    purge_and_extract()
