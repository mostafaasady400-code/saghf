import sys
import os

# Add root directory to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ensure UTF-8 console output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from database.db import db
from database.models import Property, Owner, MatchRecord, Visit, Interaction
from crawler.dedup import dedup_engine

def reset_crawler_data():
    app = create_app()
    with app.app_context():
        print("=" * 65)
        print("🗑️ آغاز پاکسازی کامل دیتای قبلی کراولر (دیوار و شیپور)...")
        print("=" * 65)

        # 1. پاکسازی تطابق‌ها، بازدیدها و تعامل‌های وابسته
        deleted_matches = MatchRecord.query.delete()
        deleted_visits = Visit.query.delete()
        deleted_interactions = Interaction.query.delete()

        # 2. پاکسازی تمام املاک کراول شده
        deleted_properties = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).delete(synchronize_session=False)

        # 3. پاکسازی مالکین ثبت‌شده خودکار توسط کراولر
        deleted_owners = Owner.query.filter(
            (Owner.notes.like('%ثبت خودکار از کراولر%')) |
            (Owner.full_name.like('%مالک آگهی%')) |
            (Owner.full_name.like('%مالک محترم%')) |
            (Owner.full_name.like('%مالک شیپور%'))
        ).delete(synchronize_session=False)

        db.session.commit()

        # 4. ریست حافظه فیلتر تکراری O(1)
        dedup_engine.clear()

        print(f"✓ تعداد {deleted_properties} ملک کراول‌شده قبلی با موفقیت پاکسازی شد.")
        print(f"✓ تعداد {deleted_owners} پرونده مالک خودکار حذف گردید.")
        print(f"✓ تعداد {deleted_matches} تطبیق هوشمند، {deleted_visits} بازدید و {deleted_interactions} تعامل پاک شدند.")
        print(f"✓ حافظه کش تکراری Dedup Engine کاملاً صفر و بازنشانی شد (ظرفیت فعلی: {dedup_engine.size()}).")
        print("=" * 65)
        print("✨ سیستم با موفقیت به نقطه صفر بازگشت و آماده استخراج داده‌های تازه است.")
        print("=" * 65)

if __name__ == '__main__':
    reset_crawler_data()
