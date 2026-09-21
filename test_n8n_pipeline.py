import sys
import json
import urllib.request
import urllib.error

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_URL = "http://127.0.0.1:5000"

def post_json(path, data):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {'raw': body}

def get_req(path):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={'Accept': 'text/html,application/json'})
    try:
        with urllib.request.urlopen(req) as resp:
            content_type = resp.headers.get('Content-Type', '')
            raw = resp.read().decode('utf-8', errors='replace')
            if 'application/json' in content_type:
                return resp.status, json.loads(raw)
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='replace')

def run_all_tests():
    print("================================================================")
    print("🚀 آغاز آزمون جامع پایپ‌لاین اتوماسیون n8n و دوگانه CRM سقف")
    print("================================================================")

    channels = ['voip', 'sms', 'instagram', 'whatsapp', 'telegram', 'bale', 'eitaa', 'rubika']
    
    # 1. Ingest endpoints test
    print("\n--- [1] آزمون وب‌هوک‌های ۸ کانال ارتباطی ---")
    sample_payloads = {
        'voip': {'caller_number': '09121112233', 'audio_url': 'https://saghf.ir/audio/call-01.wav', 'transcript': 'سلام آپارتمان ۲۰۰ متری در کامرانیه برای اجاره دارم', 'sender_name': 'مهندس علوی'},
        'sms': {'from': '09123334455', 'body': 'خرید واحد ۳ خواب در ولنجک بودجه ۳۰ میلیارد'},
        'instagram': {'user_id': 'amir_rezaei', 'message': 'قیمت ملک زعفرانیه چنده؟ قصد خرید دارم'},
        'whatsapp': {'phone': '09125556677', 'text': 'فروش ویلا در لواسان تک برگ سند'},
        'telegram': {'username': 'sara_farhadi', 'text': 'رهن و اجاره در اقدسیه تا ۵۰۰ رهن'},
        'bale': {'sender': '09127778899', 'message': 'یک باب مغازه تجاری در تجریش'},
        'eitaa': {'from_user': 'dr_ahmadi', 'content': 'فروش پنت‌هاوس ۲۵۰ متری فرمانیه'},
        'rubika': {'sender_id': 'rubika_user_99', 'text': 'خرید واحد اداری در ونک'}
    }

    for ch in channels:
        status, res = post_json(f"/api/n8n/ingest/{ch}", sample_payloads[ch])
        print(f"  ✓ کانال {ch.upper():<10}: Status={status} -> {res.get('message', 'OK')}")
        assert status == 200, f"Error in channel {ch}: {res}"

    # 2. LLM Semantic Router Test (Owner text)
    print("\n--- [2] آزمون تفکیک معنایی هوش مصنوعی (نقش مالک) ---")
    owner_text = "سلام، بنده مالک یک واحد ۱۸۰ متری نوساز تک‌برگ سند در نیاوران طبقه ۵ هستم. قصد فروش با قیمت متری ۲۲۰ میلیون تومان دارم."
    status, res = post_json("/api/n8n/router/classify-and-extract", {
        "text": owner_text,
        "phone": "09121113344",
        "channel": "eitaa"
    })
    print(f"  ✓ Status={status}, Role: {res.get('role')} ({res.get('role_persian')})")
    print(f"  ✓ استخراج متادیتا: {res.get('extracted', {}).get('entities', {})}")
    assert status == 200
    assert res.get('role') == 'property_owner'

    # 3. LLM Semantic Router Test (Buyer text)
    print("\n--- [3] آزمون تفکیک معنایی هوش مصنوعی (نقش متقاضی / خریدار) ---")
    buyer_text = "سلام وقت بخیر، دنبال خرید آپارتمان حدود ۱۲۰ تا ۱۴۰ متر دو خوابه تو سعادت‌آباد یا شهرک غرب هستم با بودجه بین ۱۸ تا ۲۲ میلیارد تومان."
    status, res = post_json("/api/n8n/router/classify-and-extract", {
        "text": buyer_text,
        "phone": "09125558899",
        "channel": "whatsapp"
    })
    print(f"  ✓ Status={status}, Role: {res.get('role')} ({res.get('role_persian')})")
    print(f"  ✓ استخراج متادیتا: {res.get('extracted', {}).get('entities', {})}")
    assert status == 200
    assert res.get('role') == 'lead_buyer_tenant'

    # 4. Save to CRM 1: Properties & Owners CRM
    print("\n--- [4] آزمون ذخیره‌سازی در پایگاه داده CRM 1 (مالکین و املاک) ---")
    owner_crm_payload = {
        "owner_name": "دکتر احمدرضا جلالی",
        "phone": "09121002030",
        "platform_id": "eitaa",
        "title": "آپارتمان ۲۰۰ متری سوپرلوکس نیاوران",
        "deal_type": "sale",
        "property_type": "apartment",
        "district": "نیاوران",
        "area": 200,
        "price": 40000000000,
        "floor": "6",
        "deed_status": "سند تک‌برگ رسمی عرصه و اعیان",
        "description": "نوساز کلیدنخورده، متریال وارداتی، ۲ پارکینگ سندی، استخر و سونا فعال"
    }
    status, res = post_json("/api/n8n/crm/owner-property", owner_crm_payload)
    print(f"  ✓ Status={status} -> Property ID: {res.get('property', {}).get('id')}")
    print(f"  ✓ وضعیت مدارک/تصاویر: {res.get('property', {}).get('media_intake_status')}")
    print(f"  ✓ آلارم تلگرامی طلایی: {res.get('telegram_alert', {}).get('color_emoji')} {res.get('telegram_alert', {}).get('tag')}")
    assert status == 200
    assert res.get('success') is True

    # 5. Save to CRM 2: Buyers & Tenants CRM
    print("\n--- [5] آزمون ذخیره‌سازی در پایگاه داده CRM 2 (متقاضیان و تطبیق هوشمند) ---")
    buyer_crm_payload = {
        "full_name": "مهندس سهراب پارسا",
        "phone": "09123004050",
        "deal_type": "sale",
        "target_districts": ["نیاوران", "فرمانیه", "سعادت‌آباد"],
        "min_area": 150,
        "budget": 45000000000,
        "preferred_channel": "whatsapp",
        "priorities": ["نورگیر جنوبی", "پارکینگ سندی", "سند تک برگ"]
    }
    status, res = post_json("/api/n8n/crm/buyer-tenant", buyer_crm_payload)
    print(f"  ✓ Status={status} -> Lead ID: {res.get('lead', {}).get('id')}")
    print(f"  ✓ فایل‌های پیشنهادی استخراج‌شده از موتور تطبیق: {len(res.get('matched_properties', []))} مورد")
    print(f"  ✓ آلارم تلگرامی سبز: {res.get('telegram_alert', {}).get('color_emoji')} {res.get('telegram_alert', {}).get('tag')}")
    assert status == 200
    assert res.get('success') is True

    # 6. Follow-up 24h Cron Job Test
    print("\n--- [6] آزمون کران جاب فالوآپ ۲۴ ساعته خودکار (Smart Follow-up Cron) ---")
    status, res = post_json("/api/n8n/cron/follow-up-24h", {"dry_run": False})
    print(f"  ✓ Status={status} -> Processed: {res.get('processed_count')} leads")
    print(f"  ✓ پیام‌های تولید و ارسال‌شده: {len(res.get('dispatched', []))}")
    assert status == 200

    # 7. Customer Feedback Processing Test (Schedule visit)
    print("\n--- [7] آزمون پردازش بازخورد مشتری (درخواست بازدید) ---")
    feedback_payload = {
        "lead_id": 1,
        "feedback_text": "سلام، فایل اولی نیاوران خیلی عالیه. امکانش هست فردا ساعت ۵ عصر هماهنگ کنید برای بازدید حضوری؟"
    }
    status, res = post_json("/api/n8n/feedback/process", feedback_payload)
    print(f"  ✓ Status={status} -> Action: {res.get('action')}")
    print(f"  ✓ پیام سیستم: {res.get('message')}")
    assert status == 200
    assert res.get('action') in ['schedule_visit', 'visit_scheduled']

    # 8. Customer Feedback Processing Test (Refine criteria)
    print("\n--- [8] آزمون پردازش بازخورد مشتری (عدم تمایل و درخواست گزینه‌های دیگر) ---")
    feedback_payload2 = {
        "lead_id": 1,
        "feedback_text": "این فایل‌ها کمی گرون بودن و طبقه پایین دوست ندارم. اگر مورد دیگری در فرمانیه متری کمتر سراغ دارید بفرستید."
    }
    status, res = post_json("/api/n8n/feedback/process", feedback_payload2)
    print(f"  ✓ Status={status} -> Action: {res.get('action')}")
    print(f"  ✓ تعداد گزینه‌های جایگزین ارسالی: {res.get('replacement_count')}")
    assert status == 200
    assert res.get('action') in ['refine_criteria', 'criteria_adjusted_replacements_sent']

    # 9. Admin Stats Endpoint
    print("\n--- [9] آزمون آمار و داده‌های داشبورد ادمین CRM ---")
    status, res = get_req("/api/n8n/admin/stats")
    print(f"  ✓ Status={status}")
    print(f"  ✓ آمار کلی: {res}")
    assert status == 200

    # 10. Telegram Mini App HTML Template Test
    print("\n--- [10] آزمون وب‌اپلیکیشن تلگرام ادمین (Telegram Mini App) ---")
    status, html = get_req("/admin/telegram-mini-app")
    print(f"  ✓ Status={status}, Length={len(html)} bytes")
    assert status == 200
    assert "Telegram.WebApp" in html
    assert "سقف" in html
    print("  ✓ Mini App UI با موفقیت لود شد و حاوی SDK تلگرام و تم لوکس مشکی و طلایی است.")

    print("\n================================================================")
    print("✨ تمامی آزمون‌های اتوماسیون n8n و تفکیک دوگانه CRM با موفقیت ۱۰۰٪ پاس شدند! ✨")
    print("================================================================")

if __name__ == '__main__':
    run_all_tests()
