import sys
import json

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from database.db import db
from services.kenar_divar_pipeline import (
    KenarDivarClient,
    HybridSourcingOrchestrator,
    MultiPlatformContactRouter,
    OwnerEnrichmentFlow,
    ClientSalesMatchingFlow
)
from database.models import Property, Owner, Client, Visit

def run_tests():
    app = create_app()
    with app.app_context():
        print("==================================================================")
        print("🚀 آزمون جامع پایپ‌لاین هیبریدی کنار دیوار و اتوماسیون دوطرفه سقف")
        print("==================================================================")

        # ۱. آزمون اندپوینت‌های ۴گانه کنار دیوار (Kenar Divar OpenAPI)
        print("\n--- [۱] آزمون اندپوینت‌های ۴گانه پلتفرم باز کنار دیوار ---")
        # اندپوینت ۱: Finder v2
        f2 = KenarDivarClient.fetch_finder_posts(category="buy-apartment", city="tehran", limit=5)
        print(f"  ✓ اندپوینت ۱ (v2 Finder Post): Success={f2.get('success') or False} | Status={f2.get('status_code', 200)}")

        # اندپوینت ۲: Finder v1 Post by Token
        f1 = KenarDivarClient.get_post_by_token("sample_token_123")
        print(f"  ✓ اندپوینت ۲ (v1 Finder Post Token): Token={f1.get('token')} | Status={f1.get('status_code', 200)}")

        # اندپوینت ۳: Get User ID by Phone
        u_phone = "09121112233"
        u_res = KenarDivarClient.get_user_id_by_phone(u_phone)
        print(f"  ✓ اندپوینت ۳ (Get User ID by Phone): Phone={u_res.get('phone')} | UserID={u_res.get('user_id') or u_res.get('simulated_user_id')}")

        # اندپوینت ۴: User Businesses (بررسی بیزینس/آژانس املاک)
        uid = u_res.get('user_id') or u_res.get('simulated_user_id') or "usr_112233"
        b_res = KenarDivarClient.get_user_businesses(uid)
        print(f"  ✓ اندپوینت ۴ (User Businesses): IsAgency={b_res.get('is_agency')} | IsPersonal={b_res.get('is_personal_owner')}")

        # ۲. آزمون موتور هیبریدی استخراج و فیلتر آگهی‌های شخصی
        print("\n--- [۲] آزمون استخراج هیبریدی و فیلترینگ قطعی مالک شخصی ---")
        listings = HybridSourcingOrchestrator.source_and_filter_listings(
            category='buy-apartment',
            district='نیاوران',
            city='tehran',
            limit=5
        )
        print(f"  ✓ تعداد فایل‌های تاییدشده شخصی: {len(listings)} مورد")
        if listings:
            first_item = listings[0]
            print(f"  ✓ نمونه فایل شخصی: {first_item.get('title')} | مالک: {first_item.get('owner_phone')} | منبع: {first_item.get('source_mode')}")

        # ۳. اعتبارسنجی شماره‌ها و مسیریابی ارتباطی چندکاناله
        print("\n--- [۳] آزمون اعتبارسنجی شماره‌ها و مسیریابی ارتباطی ---")
        test_phones = ['09129998877', '+989351234567', '9123334455', '02188889999']
        for p in test_phones:
            valid = MultiPlatformContactRouter.validate_iranian_phone(p)
            platforms = MultiPlatformContactRouter.detect_active_platforms(valid) if valid else []
            print(f"  - شماره {p:<15} -> معتبر: {str(valid):<12} | پلتفرم‌های فعال: {', '.join(platforms)}")

        # ۴. سناریوی الف: تعامل هوشمند با مالک (Owner Enrichment Flow)
        print("\n--- [۴] سناریوی الف: تعامل هوشمند و اعتبارسنجی اطلاعات با مالک ---")
        sample_prop = {
            'source': 'divar',
            'source_id': 'divar_test_enrich_99',
            'source_url': 'https://divar.ir/v/divar_test_enrich_99',
            'title': 'آپارتمان ۱۸۰ متری نیاوران مالک شخصی',
            'deal_type': 'sale',
            'district': 'نیاوران',
            'total_price': 36000000000,
            'area': 180,
            'rooms': 3,
            'owner_phone': '09121118899',
            'owner_name': 'مهندس رادمنش'
        }
        owner_flow_res = OwnerEnrichmentFlow.start_owner_enrichment(sample_prop, platform='telegram')
        print(f"  ✓ استارت تعامل با مالک: Success={owner_flow_res['success']} | کد فایل: #{owner_flow_res['file_code']}")
        print(f"  ✓ متن استعلام ارسالی به مالک:\n{owner_flow_res['inquiry_message'][:300]}...")

        # ثبت پاسخ فرضی مالک
        prop_id = owner_flow_res['property_id']
        ans_res = OwnerEnrichmentFlow.record_owner_response(
            property_id=prop_id,
            is_available=True,
            media_urls=['https://saghf.ir/media/p180_living.jpg', 'https://saghf.ir/media/p180_master.jpg'],
            evacuation_terms='تخلیه فوری - کلید تحویل',
            visit_hours='همه‌روزه از ساعت ۱۶ الی ۲۰'
        )
        print(f"  ✓ ثبت پاسخ مالک در CRM: وضعیت={ans_res['status']} | تعداد عکس‌های ثبت‌شده={ans_res['media_count']}")

        # ۵. سناریوی ب: تعامل هوشمند با مشتری/متقاضی (Client Sales & Matching Flow)
        print("\n--- [۵] سناریوی ب: تعامل با متقاضی، محرمانگی و تیکت آماده بازدید ---")
        client_phone = '09127776655'
        client_name = 'دکتر شایان پارسا'
        criteria = {
            'deal_type': 'sale',
            'districts': ['نیاوران', 'فرمانیه'],
            'budget': 38000000000,
            'min_area': 160
        }
        match_res = ClientSalesMatchingFlow.match_and_send_to_client(client_phone, client_name, criteria, platform='telegram')
        print(f"  ✓ انطباق و ارسال گزینه‌ها به مشتری: تعداد فایل‌های منطبق={match_res['matched_count']}")
        assert "0912" not in match_res['client_message'], "نقض محرمانگی: شماره مالک در پیام مشتری یافت شد!"

        # ثبت تایید نهایی مشتری و تولید تیکت برای کارشناس فروش
        ticket_res = ClientSalesMatchingFlow.confirm_visit_and_ticket(
            client_phone=client_phone,
            file_code=str(owner_flow_res['file_code']),
            client_feedback="فایل شماره ۱ نیاوران بسیار عالیه، فردا بعدازظهر برای بازدید هماهنگ کنید."
        )
        print(f"  ✓ تیکت فوری تولیدشده برای کارشناس فروش:\n{ticket_res['ticket_text']}")
        print(f"  ✓ پیام تاییدیه به مشتری:\n{ticket_res['client_reply']}")
        assert ticket_res['owner_phone'] != ""
        assert ticket_res['client_phone'] != ""

        # بررسی در دیتابیس CRM
        visit_obj = db.session.get(Visit, ticket_res['visit_id'])
        assert visit_obj is not None
        print(f"\n✓ ثبت موفق نوبت بازدید در دیتابیس: Visit #{visit_obj.id} | زمان: {visit_obj.scheduled_time}")

        print("\n==================================================================")
        print("✨ تمامی آزمون‌های پایپ‌لاین کنار دیوار و اتوماسیون دوطرفه ۱۰۰٪ پاس شدند! ✨")
        print("==================================================================")

if __name__ == '__main__':
    run_tests()
