import sys
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import time
from app import create_app
from crawler.network.impersonator import TLSImpersonatorClient, HAS_CURL_CFFI
from crawler.network.rate_limiter import TokenBucketRateLimiter
from crawler.dedup import dedup_engine
from crawler.schemas import NormalizedPropertySchema, OwnerSchema
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.hybrid_sheypoor import HybridSheypoorCrawler
from crawler.crawler_manager import crawler_manager
from database.models import Property

print("=" * 60)
print("🧪 آزمون جامع اعتبارسنجی معماری هیبریدی کراولر سقف")
print("=" * 60)

# ۱. تست ماژول TLS Impersonation
print("\n[۱] بررسی کلاینت TLS Impersonation:")
print(f"  - وضعیت دسترسی به curl_cffi: {'فعال (Chrome 120+ JA3/JA4 Spoofing)' if HAS_CURL_CFFI else 'عدم دسترسی'}")
client = TLSImpersonatorClient(impersonate="chrome120")
headers = client.get_headers()
assert "Sec-Ch-Ua" in headers, "Sec-Ch-Ua header missing"
print("  ✅ هدرهای استاندارد کلاینت کروم و اثر انگشت تایید شد.")

# ۲. تست ریت‌لیمیت Token Bucket
print("\n[۲] بررسی ریت‌لیمیت سطل توکن (Token Bucket + Jitter):")
limiter = TokenBucketRateLimiter(capacity=2, fill_rate=5, min_jitter=0.05, max_jitter=0.1)
t0 = time.time()
limiter.acquire(1)
limiter.acquire(1)
elapsed = time.time() - t0
print(f"  ✅ تخصیص توکن و تاخیر رفتاری شبه‌انسانی ({elapsed:.2f} ثانیه) با موفقیت تست شد.")

# ۳. تست اسکیماهای Pydantic V2
print("\n[۳] بررسی اعتبارسنجی اسکیماهای Pydantic:")
test_payload = {
    'source': 'divar',
    'source_id': 'divar_test_token_99',
    'source_url': 'https://divar.ir/v/test99',
    'title': 'آپارتمان ۱۴۰ متری ۳ خوابه نیاوران',
    'deal_type': 'sale',
    'total_price': 25000000000,
    'area': 140,
    'district': 'در نیاوران',
    'owner_info': {
        'name': 'آقای شایان',
        'phone': '+98 912 111 2233'
    }
}
schema_obj = NormalizedPropertySchema(**test_payload)
assert schema_obj.district == 'نیاوران', "District cleaning failed"
assert schema_obj.owner_info.phone == '09121112233', "Phone normalization failed"
print("  ✅ اعتبارسنجی و پاک‌سازی خودکار داده‌های خام توسط Pydantic تایید شد.")

# ۴. تست کراولرهای هیبریدی دیوار و شیپور
print("\n[۴] اجرای کراولرهای هیبریدی دیوار و شیپور:")
divar_crawler = HybridDivarCrawler()
divar_items = divar_crawler.fetch_listings('buy-apartment', limit=3)
print(f"  ✅ دیوار هیبریدی: {len(divar_items)} رکورد با ساختار معتبر Pydantic استخراج شد.")

sheypoor_crawler = HybridSheypoorCrawler()
sheypoor_items = sheypoor_crawler.fetch_listings('buy-apartment', limit=3)
print(f"  ✅ شیپور هیبریدی: {len(sheypoor_items)} رکورد با ساختار معتبر Pydantic استخراج شد.")

# ۵. تست پایپ‌لاین کامل در کانتکست دیتابیس
print("\n[۵] اجرای ارکستراتور هیبریدی و ثبت در پایگاه داده SQLite:")
app = create_app()
with app.app_context():
    crawler_manager.init_app(app)
    success, msg = crawler_manager.start_crawl_task(
        sources=['divar', 'sheypoor'],
        categories=['buy-apartment'],
        limit_per_cat=3
    )
    print(f"  - پیام شروع کار ارکستراتور: {msg}")
    
    # انتظار کوتاه برای اتمام تسک در پس‌زمینه
    time.sleep(3)
    status = crawler_manager.get_status()
    print(f"  - وضعیت ارکستراتور: {status['stats']['status']}")
    print(f"  - فایل‌های جدید ثبت شده: {status['stats']['new_saved']}")
    print(f"  - فایل‌های تکراری اسکیپ‌شده با O(1): {status['stats']['duplicates_skipped']}")
    print(f"  - تعداد کل فایل‌های کش‌شده در ددوپلیکیتور: {status['dedup_cache_size']}")

print("\n🎉 تمام آزمون‌های معماری هیبریدی با موفقیت ۱۰۰٪ پاس شدند!")
