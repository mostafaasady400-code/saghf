"""
اسکریپت اجرای بک‌فیل ۷ روزه عمیق روی کانون‌های اصلی منطقه ۲ و ۵ تهران
"""
import sys
import time
from app import app
from database.models import Property, Owner, PropertyListing
from crawler.regional_incremental_engine import regional_engine

print("=== شروع فرآیند استخراج عمیق ۷ روزه منطقه ۲ و ۵ تهران ===")
start_time = time.time()

# اجرای بک‌فیل عمیق با حداکثر ۳ صفحه برای هر اسلاگ اصلی
result = regional_engine.run_7_day_backfill(max_pages_per_slug=3)
elapsed = time.time() - start_time

print(f"\n✅ اجرای بک‌فیل در {elapsed:.1f} ثانیه پایان یافت.")
print(f"تعداد آگهی‌های بررسی شده: {result.get('total_discovered')}")
print(f"تعداد آگهی‌های مالک جدید ثبت‌شده: {result.get('total_saved')}")
print(f"منطقه ۲: {result.get('region_2_saved')} | منطقه ۵: {result.get('region_5_saved')}")

with app.app_context():
    print(f"\nآمار نهایی پایگاه داده:")
    print(f"- کل املاک: {Property.query.count()}")
    print(f"- کل مالکین: {Owner.query.count()}")
    print(f"- کل آگهی‌ها: {PropertyListing.query.count()}")

    # بررسی تضمینی اینکه هیچ ملکی خارج از منطقه ۲ و ۵ نباشد
    from data.tehran_districts import is_in_region_2_or_5
    all_props = Property.query.all()
    non_2_5 = [p for p in all_props if not is_in_region_2_or_5(p.district, f"{p.title} {p.description}")]
    print(f"- املاک خارج از منطقه ۲ و ۵: {len(non_2_5)} (باید صفر باشد)")
    assert len(non_2_5) == 0, "خطا: ملکی خارج از منطقه ۲ و ۵ در دیتابیس وجود دارد!"
