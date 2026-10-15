"""Controlled, polite live test of the accessible Divar search pipeline."""

import sys
import os
import json
import time

sys.path.insert(0, r"c:\saghf سقف")

from app import create_app
from database.db import db
from database.models import AccessibleListing, SearchRun, SearchRunItem, Property
from services.search_run_service import SearchRunService
from crawler.divar_accessible_search import AccessibleSearchCriteria, DivarAccessibleSearchCrawler

def run_live_test():
    print("=" * 70)
    print("🔍 اجرای آزمون زندهٔ کنترل‌شده و محدود سقف (Accessible Divar Search)")
    print("=" * 70)

    app = create_app()
    with app.app_context():
        # Pre-count existing records
        pre_listings_count = AccessibleListing.query.count()
        print(f"📊 تعداد رکوردهای پایدار قبلی در accessible_listings: {pre_listings_count}")

        # Create search run for real Divar query
        criteria_dict = {
            "city": "tehran",
            "districts": ["پونک"],
            "deal_type": "sale",
            "property_type": "apartment",
            "window_hours": 24,
        }
        run = SearchRunService.create_run(criteria_dict, query_text="خرید آپارتمان در پونک")
        print(f"✅ اجرای جست‌وجو در پایگاه داده ایجاد شد: run_id = {run.run_id}")

        # Instantiate live crawler with polite delays (1.2s between pages)
        crawler = DivarAccessibleSearchCrawler(
            request_delay_seconds=1.2,
            semantic_timeout_seconds=5.0,
        )

        print("🌐 در حال اتصال به مسیر عمومی دیوار و دریافت داده‌های زنده (محدود به سقف ۲۰ ثانیه)...")
        start_time = time.monotonic()
        try:
            executed_run = SearchRunService.execute(
                run.run_id,
                crawler=crawler,
                max_runtime_seconds=20.0,
            )
        except Exception as exc:
            print(f"⚠️ خطای کنترل‌شده در حین دریافت زنده: {exc}")
            executed_run = SearchRun.query.filter_by(run_id=run.run_id).first()

        elapsed = time.monotonic() - start_time
        print(f"⏱️ زمان سپری‌شده آزمون زنده: {elapsed:.2f} ثانیه")

        # Refresh run
        db.session.refresh(executed_run)
        report = executed_run.report or {}
        post_listings_count = AccessibleListing.query.count()
        new_listings_stored = post_listings_count - pre_listings_count

        items = SearchRunItem.query.filter_by(run_id=executed_run.run_id).all()

        print("\n" + "=" * 70)
        print("📈 گزارش شمارنده‌های واقعی شواهد‌محور (Audit Counters):")
        print(f"- وضعیت اجرا (Status):                  {executed_run.status}")
        print(f"- وضعیت پوشش (Coverage Status):         {executed_run.coverage_status}")
        print(f"- وضعیت منبع (Source Status):           {executed_run.source_status}")
        print(f"- علت توقف (Stop Reason):               {executed_run.stop_reason}")
        print(f"- نشانگر ادامه (Has Next Cursor):       {bool((executed_run.checkpoint or {}).get('cursor'))}")
        print(f"- صفحات پیمایش‌شده (Pages Traversed):   {report.get('pages_traversed', 0)}")
        print(f"- کاندیدهای یکتای دریافتی:              {report.get('unique_received', 0)}")
        print(f"- رکوردهای جدید اضافه‌شده به دیتابیس:   {new_listings_stored}")
        print(f"- داخل بازه ۲۴ ساعته (Within Window):  {report.get('within_window', 0)}")
        print(f"- زمان نامشخص (Uncertain Time):        {report.get('uncertain_time', 0)}")
        print(f"- خارج از بازه (Outside Window):       {report.get('outside_window', 0)}")
        print(f"- منطبق با مشخصات (Criteria Matched):  {report.get('criteria_matched', 0)}")
        print(f"- مالک احتمالی (Likely Owner):         {report.get('likely_owner', 0)}")
        print(f"- مشاور صریح (Explicit Agency):        {report.get('explicit_agency', 0)}")
        print(f"- واسطه احتمالی (Likely Intermediary): {report.get('likely_intermediary', 0)}")
        print(f"- نامشخص (Unknown):                    {report.get('unknown', 0)}")
        print(f"- در انتظار تحلیل مدل (Pending Review): {report.get('pending_model_review', 0)}")
        print("=" * 70)

        # Inspect first 3 sample items
        sample_rows = (
            db.session.query(AccessibleListing, SearchRunItem)
            .join(SearchRunItem, SearchRunItem.listing_id == AccessibleListing.id)
            .filter(SearchRunItem.run_id == executed_run.run_id)
            .limit(3)
            .all()
        )

        print("\n🔎 نمونه‌های واقعی ثبت‌شده در دیتابیس پایدار:")
        for idx, (listing, ritem) in enumerate(sample_rows, 1):
            print(f"[{idx}] شناسه: {listing.source_id}")
            print(f"    عنوان: {listing.title}")
            print(f"    لینک مستقیم دیوار: {listing.source_url}")
            print(f"    محله: {listing.district} | متراژ: {listing.area} متر | قیمت: {listing.total_price}")
            print(f"    زمان انتشار: {listing.published_at} (دقت: {listing.publication_accuracy}, متن: {listing.publication_source_text})")
            print(f"    دسته‌بندی ناشر: {listing.effective_publisher_category} (اطمینان: {listing.publisher_confidence})")
            print(f"    دلیل دسته‌بندی: {listing.publisher_reason}")
            print(f"    وضعیت در این اجرا: temporal={ritem.temporal_status}, match={ritem.criteria_match}")
            print("-" * 50)

        # Test paginated results API
        page_results = SearchRunService.paginated_results(executed_run.run_id, section="main", page=1, per_page=10)
        print(f"\n🌐 دسترسی در رابط وب (صفحه نتایج):")
        print(f"- آدرس مشاهده: /crawler/search-runs/{executed_run.run_id}/view")
        print(f"- تعداد نتایج در بخش اصلی (مالک احتمالی): {page_results['pagination']['total']}")

        return executed_run.to_dict()

if __name__ == '__main__':
    run_live_test()
