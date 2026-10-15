import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from services.crm_sales_assistant import CRMSalesAssistantEngine
from database.models import Visit, Client, Property, Owner

def test_full_sales_cycle():
    app = create_app()
    with app.app_context():
        print("==================================================================")
        print("🎯 آغاز آزمون جامع دستیار هوشمند فروش و CRM تلگرام سقف")
        print("==================================================================")

        client_phone = "09124445566"
        client_name = "مهندس کامران رستگار"

        # مرحله ۱: شروع ارتباط و لیدگیری
        print("\n--- [مرحله ۱: لیدگیری و شروع تعامل با لحن مشاور ارشد] ---")
        init_res = CRMSalesAssistantEngine.start_onboarding(client_phone, client_name)
        print("پیام ارسالی دستیار:")
        print(init_res['message'])
        assert "مشاور ارشد امور ملکی" in init_res['message']
        assert client_name in init_res['message']

        # مرحله ۲: استخراج هوشمند نیازها در مکالمه
        print("\n--- [مرحله ۲: پیام کاربر و استخراج نیازمندی‌ها] ---")
        user_turn1 = "سلام، من دنبال خرید یک آپارتمان حدود ۱۶۰ تا ۱۸۰ متر در نیاوران یا فرمانیه هستم."
        print(f"کاربر: {user_turn1}")
        res1 = CRMSalesAssistantEngine.process_client_turn(client_phone, user_turn1)
        print("پاسخ دستیار (درخواست بودجه):")
        print(res1['message'])

        user_turn2 = "بودجه مد نظرم حدود ۳۵ میلیارد تومان هست و حتماً پارکینگ سندی و آسانسور می‌خوام."
        print(f"\nکاربر: {user_turn2}")
        res2 = CRMSalesAssistantEngine.process_client_turn(client_phone, user_turn2)
        print("پاسخ دستیار و فایل‌های پیشنهادی انطباق بالای ۸۰٪:")
        print(res2['message'][:500] + "...\n[ادامه متن فایل‌ها]")
        
        # اعتبارسنجی قوانین حیاتی محرمانگی:
        # شماره تماس مالک یا لینک خام سورس نباید در کارت‌های مشتری باشد
        for card in res2.get('client_cards', []):
            card_text = card['card_text']
            assert "0912" not in card_text, "نقض محرمانگی: شماره مالک در کارت مشتری یافت شد!"
            assert "source_url" not in card_text
            assert "http://127.0.0.1:5000/properties" not in card_text
            assert "کد فایل اختصاصی" in card_text
            assert "درصد تطابق" in card_text
        print("✓ قانون محرمانگی کاملاً رعایت شد: هیچ شماره تماسی از مالک برای مشتری ارسال نشد.")

        # مرحله ۳ و ۴: فیدبک مشتری و سیگنال قوی خرید -> فاز نهایی هماهنگی بازدید
        print("\n--- [مرحله ۳ و ۴: فیدبک مثبت مشتری و تحویل لید گرم به کارشناس] ---")
        user_feedback = "گزینه اول نیاوران فوق‌العاده است و عکس‌ها و قیمتش دقیقاً همونیه که می‌خواستم. کی می‌تونیم بریم برای بازدید حضوری؟"
        print(f"کاربر: {user_feedback}")

        feedback_res = CRMSalesAssistantEngine.handle_feedback_and_qualification(client_phone, user_feedback)
        print("\nپیام آرامش‌بخش ارسالی به مشتری:")
        print(feedback_res['client_message'])
        assert "هماهنگی بازدید این ملک داره انجام میشه" in feedback_res['client_message'] or "هماهنگی بازدید" in feedback_res['client_message']

        print("\n🚨 اعلان فوری ارسال‌شده به تلگرام کارشناس فروش (Hot Lead Alert):")
        alert = feedback_res['hot_lead_alert']
        print(alert['alert_text'])
        assert "[ وضعیت: آماده بازدید (Hot Lead) ]" in alert['alert_text']
        assert client_phone in alert['alert_text']
        assert alert['owner_phone'] != ""

        # بررسی ثبت در دیتابیس CRM
        client = Client.query.filter_by(phone_number=client_phone).first()
        assert client is not None
        assert client.lead_status == 'visiting'

        visit = Visit.query.filter_by(client_id=client.id).order_by(Visit.id.desc()).first()
        assert visit is not None
        assert visit.status == 'scheduled'
        print(f"\n✓ ثبت موفق نوبت بازدید در CRM: شناسه بازدید #{visit.id} | وضعیت: {visit.status} | لید: {client.full_name}")

        print("\n==================================================================")
        print("✨ آزمون جامع چرخه ۴ مرحله‌ای دستیار هوشمند فروش با موفقیت ۱۰۰٪ پاس شد! ✨")
        print("==================================================================")

if __name__ == '__main__':
    test_full_sales_cycle()
