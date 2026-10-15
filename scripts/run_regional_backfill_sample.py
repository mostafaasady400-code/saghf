"""
اسکریپت اجرای بک‌فیل و استخراج تایم‌بندی‌شده مناطق ۲ و ۵ تهران
"""
import sys
import time
from app import app
from database.models import Property, Owner, PropertyListing
from crawler.regional_incremental_engine import regional_engine

print("=== پاک‌سازی تضمینی پایگاه‌داده (حذف هرگونه داده غیر از مناطق ۲ و ۵) ===")
purge_res = regional_engine.purge_any_non_region_2_5()
print("نتیجه پاک‌سازی:", purge_res)

with app.app_context():
    print(f"تعداد املاک فعلی در پایگاه داده: {Property.query.count()}")
    print(f"تعداد مالکین در پایگاه داده: {Owner.query.count()}")

print("\n=== اجرای مرحله اول بک‌فیل و پایش تایم‌بندی‌شده مناطق ۲ و ۵ ===")
# اجرای بک‌فیل روی کانون‌های اصلی
start_t = time.time()
res = regional_engine.poll_incremental_new_ads(limit_per_slug=12)
print("نتیجه پایش نوبتی:", res)

with app.app_context():
    p_count = Property.query.count()
    o_count = Owner.query.count()
    print(f"\nآمار نهایی پایگاه داده: {p_count} ملک | {o_count} مالک")
    chk = regional_engine.load_checkpoint()
    print("وضعیت چک‌پوینت:", chk)

    # نمایش ۳ نمونه از آخرین املاک استخراج‌شده
    recent = Property.query.order_by(Property.id.desc()).limit(3).all()
    print("\nنمونه آگهی‌های ثبت‌شده:")
    for p in recent:
        owner_phone = p.owner.phone_number if p.owner else "بدون شماره"
        print(f"- [منطقه {p.district}] {p.title} | شماره: {owner_phone} | لینک: {p.source_url}")
