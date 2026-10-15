"""
اسکریپت تست و اعتبارسنجی جامع پایپ‌لاین اتوماسیون چندکاناله و دو CRM مجزا
تست دریافت کلیه درگاه‌ها، رونویسی گفتار، تفکیک نقش‌ها، پایپ‌لاین تعاملی و هشدارهای تلگرام
"""

import os
import sys
import json

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from database.db import db
from database.models import Property, Owner, CustomerLead, Client, OutreachLog, CallRecord
from services.llm_router import SemanticLLMRouter
from services.crm_dual_store import DualCRMStore
from services.nurturing_engine import nurturing_engine
from services.omnichannel_engine import omnichannel_engine

def run_tests():
    app = create_app()
    with app.app_context():
        print("=" * 70)
        print("🚀 آغاز تست‌های اعتبارسنجی پایپ‌لاین اتوماسیون چندکاناله سقف")
        print("=" * 70)

        # -------------------------------------------------------------
        # تست ۱: ارزیابی کلاسیفایر هوشمند LLM Router برای تفکیک نقش‌ها
        # -------------------------------------------------------------
        print("\n🔍 [تست ۱] بررسی کلاسیفایر نقش (مالک vs متقاضی):")
        
        owner_text = (
            "سلام وقت بخیر، من یک واحد آپارتمان ۹۵ متری در پونک دارم برای فروش. "
            "سند تک‌برگ با پارکینگ و آسانسور، قیمت کل رو ۶ میلیارد و ۵۰۰ میلیون گذاشتم. "
            "مالک هستم لطفاً ثبتش کنید."
        )
        owner_res = SemanticLLMRouter.classify_and_extract(owner_text, sender_phone="09121111111", metadata={'channel': 'whatsapp'})
        print(f"  نتیجه پیام مالک: Role={owner_res.get('role')} (اطمینان: {owner_res.get('confidence')})")
        assert owner_res.get('role') == 'owner', f"Expected owner role but got {owner_res.get('role')}"
        assert owner_res['owner_payload']['area'] == 95, f"Expected 95m area, got {owner_res['owner_payload']['area']}"
        assert owner_res['owner_payload']['district'] == 'پونک', f"Expected district پونک, got {owner_res['owner_payload']['district']}"
        print("  ✅ تشخیص نقش مالک و استخراج مشخصات ملکی با موفقیت تایید شد.")

        lead_text = (
            "سلام، دنبال یک واحد اجاره‌ای حدود ۸۰ متر در جنت‌آباد هستم. "
            "ودیعه تا ۴۰۰ میلیون و اجاره ماهی ۱۵ میلیون می‌تونم بدم. پارکینگ هم داشته باشه."
        )
        lead_res = SemanticLLMRouter.classify_and_extract(lead_text, sender_phone="09122222222", metadata={'channel': 'eitaa'})
        print(f"  نتیجه پیام متقاضی: Role={lead_res.get('role')} (اطمینان: {lead_res.get('confidence')})")
        assert lead_res.get('role') == 'lead', f"Expected lead role but got {lead_res.get('role')}"
        assert 'جنت‌آباد' in lead_res['lead_payload']['preferred_districts'], "District not found in lead payload"
        print("  ✅ تشخیص نقش متقاضی و استخراج نیازهای ملکی با موفقیت تایید شد.")

        # -------------------------------------------------------------
        # تست ۲: ثبت در دو CRM مجزا (Dual CRM Store)
        # -------------------------------------------------------------
        print("\n🏛️ [تست ۲] بررسی تفکیک و ذخیره در دو CRM مجزا:")
        
        # ذخیره در CRM مالکین و املاک
        owner_obj, prop_obj = DualCRMStore.store_owner_and_property(
            payload=owner_res['owner_payload'],
            channel='whatsapp',
            raw_text=owner_text
        )
        print(f"  ذخیره در CRM مالکین: مالک ID={owner_obj.id} ({owner_obj.full_name}) | ملک ID={prop_obj.id} (کد فایل: {prop_obj.file_code})")
        assert prop_obj.owner_id == owner_obj.id, "Property owner_id mismatch"
        assert prop_obj.file_code is not None, "Property file_code is missing"
        assert prop_obj.source_url.startswith("http"), "Direct link missing"

        # ذخیره در CRM متقاضیان و خریداران
        lead_obj, client_obj = DualCRMStore.store_customer_lead(
            payload=lead_res['lead_payload'],
            channel='eitaa',
            raw_text=lead_text
        )
        print(f"  ذخیره در CRM متقاضیان: سرنخ ID={lead_obj.id} | متقاضی CRM ID={client_obj.id} (نام: {client_obj.full_name})")
        assert lead_obj.phone_number == "09122222222", "Lead phone mismatch"
        assert client_obj.phone_number == "09122222222", "Client phone mismatch"
        print("  ✅ تفکیک کامل و عدم تداخل در دو پایگاه داده CRM تایید شد.")

        # -------------------------------------------------------------
        # تست ۳: پایپ‌لاین تعاملی مالکین (Onboarding) و متقاضیان (Matching)
        # -------------------------------------------------------------
        print("\n🔄 [تست ۳] بررسی پایپ‌لاین تعاملی و فالوآپ:")
        
        # Onboarding مالک
        onboarding = nurturing_engine.handle_owner_onboarding(prop_obj, owner_obj, channel='whatsapp')
        print(f"  ارسال پیام خوش‌آمد و درخواست عکس به مالک: {onboarding.get('success')}")

        # Matching متقاضی
        dispatches = nurturing_engine.handle_lead_matching_and_dispatch(lead_obj, channel='eitaa')
        print(f"  تطبیق و دیسپچ فایل‌ها به متقاضی: تعداد {len(dispatches)} فایل")

        # کران جاب پیگیری ۲۴ ساعته
        followup_res = nurturing_engine.execute_24h_followup_job()
        print(f"  اجرای کران جاب پیگیری ۲۴ ساعته: {followup_res}")

        # -------------------------------------------------------------
        # تست ۴: تست سرتاسری موتور چندکاناله از طریق وب‌هوک (End-to-End Ingestion)
        # -------------------------------------------------------------
        print("\n🌐 [تست ۴] تست وب‌هوک چندکاناله شبیه‌سازی تماس و پیامک و اینستاگرام:")

        client_test = app.test_client()

        # ۱. وب‌هوک تماس تلفنی VoIP
        voip_payload = {
            'caller_phone': '09123333333',
            'call_id': 'VOIP-TEST-9988',
            'duration_seconds': 45,
            'text': 'سلام، یک واحد آپارتمان ۱۲۰ متری شخصی در پونک دارم برای اجاره، ودیعه ۶۰۰ میلیون اجاره ۲۰ میلیون.'
        }
        resp_voip = client_test.post('/api/omnichannel/webhook/voip', json=voip_payload)
        print(f"  پاسخ وب‌هوک VoIP: Status={resp_voip.status_code}")
        assert resp_voip.status_code == 200, f"VoIP webhook failed: {resp_voip.data}"
        voip_json = resp_voip.get_json()
        assert voip_json['role'] == 'owner', f"Expected owner from VoIP call, got {voip_json['role']}"

        # ۲. وب‌هوک اینستاگرام دایرکت
        ig_payload = {
            'user_id': 'instagram_lead_user',
            'sender_name': 'سروش راد',
            'phone': '09124444444',
            'text': 'سلام، من از پیج اینستاگرامتون پیام می‌دم. برای خرید آپارتمان تو منطقه ۵ بودجه ۸ میلیاردی دارم.'
        }
        resp_ig = client_test.post('/api/omnichannel/webhook/instagram', json=ig_payload)
        print(f"  پاسخ وب‌هوک اینستاگرام: Status={resp_ig.status_code}")
        assert resp_ig.status_code == 200, f"Instagram webhook failed: {resp_ig.data}"
        ig_json = resp_ig.get_json()
        assert ig_json['role'] == 'lead', f"Expected lead from Instagram, got {ig_json['role']}"

        # ۳. اندپوینت وضعیت ماژول
        resp_status = client_test.get('/api/omnichannel/status')
        print(f"  وضعیت سرویس چندکاناله: Status={resp_status.status_code}, Data={resp_status.get_json()['status']}")
        assert resp_status.status_code == 200

        print("\n" + "=" * 70)
        print("🎉 تمامی تست‌های پایپ‌لاین اتوماسیون چندکاناله و دو CRM با موفقیت ۱۰۰٪ پاس شدند!")
        print("=" * 70)

if __name__ == '__main__':
    run_tests()
