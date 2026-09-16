import os
import sys
import random
import time

sys.path.insert(0, os.path.abspath('.'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

from app import create_app
from database.db import db
from database.models import Property, Owner, Agent
from crawler.dedup import dedup_engine
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.hybrid_sheypoor import HybridSheypoorCrawler
from crawler.owner_filter import OwnerFilter
from services.matching_service import MatchingEngine

def extract_batch():
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("🎯 استخراج هدفمند آگهی‌های ۱۰۰٪ شخصی (فاقد هرگونه نام یا نشان املاک)")
        print("=" * 60)

        agents = Agent.query.all()
        if not agents:
            a1 = Agent(name="علیرضا محمدی", phone="09121111111", role="مشاور ارشد")
            db.session.add(a1)
            db.session.commit()
            agents = Agent.query.all()

        divar_crawler = HybridDivarCrawler(city='tehran')
        sheypoor_crawler = HybridSheypoorCrawler(city='tehran')

        saved_total = 0
        all_real = []

        # ۱. استخراج از دیوار (با صفحات بیشتر)
        divar_cats = ['buy-apartment', 'rent-apartment', 'buy-residential', 'rent-residential', 'commercial-buy']
        for cat in divar_cats:
            print(f"\n[دیوار] اسکن دسته {cat} برای فایل‌های ۱۰۰٪ شخصی...")
            try:
                items = divar_crawler.fetch_listings(category_key=cat, limit=15)
                for it in items:
                    if it.is_personal_owner:
                        all_real.append(it)
                print(f"[دیوار] {len(items)} فایل شخصی معتبر دریافت شد.")
            except Exception as e:
                print(f"[دیوار] خطا در {cat}: {e}")
            time.sleep(1.5)

        # ۲. استخراج از شیپور (با فیلتر جدید تمام‌صفحه‌ای ضد املاک)
        sheypoor_cats = ['buy-apartment', 'rent-apartment', 'real-estate']
        for cat in sheypoor_cats:
            print(f"\n[شیپور] اسکن دسته {cat} با فیلتر هویت آژانس...")
            try:
                items = sheypoor_crawler.fetch_listings(category_key=cat, limit=10)
                for it in items:
                    if it.is_personal_owner:
                        all_real.append(it)
                print(f"[شیپور] {len(items)} فایل شخصی معتبر دریافت شد.")
            except Exception as e:
                print(f"[شیپور] خطا در {cat}: {e}")
            time.sleep(1.5)

        print(f"\n📦 مجموع فایل‌های استخراج شده برای ثبت: {len(all_real)}")

        # ثبت با اعتبارسنجی صفر-تسامح
        FORBIDDEN_WORDS = ['املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس', 'سرمایه گذاری', 'هلدینگ']

        for item in all_real:
            combined = f"{item.title} {item.description or ''}"
            if any(w in combined for w in FORBIDDEN_WORDS):
                print(f"⚠️ رد به علت وجود کلمه ممنوعه: {item.title[:45]}")
                continue

            chk = OwnerFilter.evaluate(platform=item.source, title=item.title, description=item.description or '')
            if not chk.is_personal:
                print(f"⚠️ رد در ارزیابی نهایی: {item.title[:45]} ({chk.reason})")
                continue

            existing = Property.query.filter_by(source_id=item.source_id).first()
            if existing:
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

            agent = random.choice(agents) if agents else None

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
                is_personal_owner=True,
                owner_type='personal',
                filter_log="تأییدشده ۱۰۰٪ شخصی - فاقد هرگونه نشانه یا کلمه املاک",
                owner_id=owner.id if owner else None,
                assigned_agent_id=agent.id if agent else None
            )
            prop.features = item.features
            prop.images = item.images

            db.session.add(prop)
            dedup_engine.mark_seen(item.source_id)
            saved_total += 1

        db.session.commit()
        print(f"\n✅ تعداد {saved_total} فایل جدید ۱۰۰٪ شخصی در دیتابیس ثبت شد.")

        total_props = Property.query.count()
        print(f"📊 مجموع کل فایل‌های ۱۰۰٪ شخصی و پاک در دیتابیس: {total_props}")

        MatchingEngine.refresh_matches_for_all()
        print("🧠 ماتریس هوشمند تطبیق با املاک جدید به‌روزرسانی شد.")

if __name__ == '__main__':
    extract_batch()
