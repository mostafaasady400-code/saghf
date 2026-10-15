"""
اسکریپت پاک‌سازی قطعی دیتابیس: حذف تمامی آگهی‌های خارج از منطقه ۲ و ۵ تهران
صرفاً آگهی‌های واقع در مناطق ۲ و ۵ پایتخت حفظ می‌شوند.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import db
from database.models import Property, PropertyListing, Owner, MatchRecord, Visit, Interaction
from data.tehran_districts import is_in_region_2_or_5


def purge_non_region_2_and_5():
    app = create_app()
    with app.app_context():
        all_props = Property.query.all()
        total_before = len(all_props)
        print(f"کل آگهی‌های قبل از پاک‌سازی: {total_before}")

        purged_props = 0
        kept_props = 0

        for p in all_props:
            combined_txt = f"{p.district or ''} {p.title or ''} {p.description or ''} {p.address or ''}"
            if is_in_region_2_or_5(p.district, combined_txt):
                kept_props += 1
            else:
                # حذف وابستگی‌ها
                MatchRecord.query.filter_by(property_id=p.id).delete()
                Visit.query.filter_by(property_id=p.id).delete()
                Interaction.query.filter_by(property_id=p.id).delete()

                # حذف از PropertyListing
                if p.source_id:
                    PropertyListing.query.filter_by(ad_code=str(p.source_id)).delete()
                    ad_code_clean = str(p.source_id).replace('divar_', '')
                    PropertyListing.query.filter_by(ad_code=ad_code_clean).delete()

                db.session.delete(p)
                purged_props += 1

        db.session.commit()
        print(f"تعداد آگهی‌های حذف‌شده (خارج از منطقه ۲ و ۵): {purged_props}")
        print(f"تعداد آگهی‌های حفظ‌شده (منطقه ۲ و ۵): {kept_props}")

        # پاک‌سازی مالکین فاقد هرگونه ملک باقی‌مانده
        orphaned_owners = 0
        all_owners = Owner.query.all()
        for o in all_owners:
            remaining = Property.query.filter_by(owner_id=o.id).count()
            if remaining == 0:
                db.session.delete(o)
                orphaned_owners += 1
        db.session.commit()
        print(f"تعداد مالکین غیرفعال حذف‌شده: {orphaned_owners}")

        remaining_props = Property.query.count()
        remaining_owners = Owner.query.count()
        print(f"وضعیت نهایی دیتابیس: {remaining_props} آگهی (۱۰۰٪ در منطقه ۲ و ۵) | {remaining_owners} مالک")


if __name__ == '__main__':
    purge_non_region_2_and_5()
