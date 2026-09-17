"""
اسکریپت تست خودکار و یکپارچه پایپلاین هوشمند رویدادمحور املاک سقف (Pipeline Integration Test)
پوشش کامل مراحل:
۱. ایجاد و ثبت پروفایل فیلتر هدفمند (رهن و اجاره منطقه ۵)
۲. درج داده‌های تست در PropertyListing با لینک‌های معتبر مطابق AGENTS.md
۳. شبیه‌سازی وب‌هوک مکالمه تلفنی VoIP و فراخوانی STT + NLP
۴. بررسی ایجاد و به‌روزرسانی CallRecord و CustomerLead
۵. اجرای موتور تطبیق منطقه‌ای با تلورانس ۱۰٪ و انتخاب ۳ فایل برتر
۶. دیسپچ پکیج به پیام‌رسان‌ها و بررسی ثبت لاگ در جدول OutreachLog
"""

import sys
import json
from app import create_app
from database.db import db
from database.models import FilterProfile, PropertyListing, CallRecord, CustomerLead, OutreachLog
from services.regional_matching import RegionalPropertyMatcher
from services.omnichannel.dispatcher import omnichannel_dispatcher

def run_test():
    print("=" * 60)
    print("🚀 آغاز تست جامع و یکپارچه پایپلاین هوشمند املاک سقف")
    print("=" * 60)

    app = create_app()
    with app.app_context():
        # گام ۱: ایجاد پروفایل فیلتر هدفمند
        print("\n[گام ۱] ثبت پروفایل فیلتر هدفمند (رهن و اجاره منطقه ۵)...")
        profile = FilterProfile.query.filter_by(name='رهن و اجاره منطقه ۵ (پونک و جنت‌آباد)').first()
        if not profile:
            profile = FilterProfile(
                name='رهن و اجاره منطقه ۵ (پونک و جنت‌آباد)',
                city='تهران',
                region='5',
                deal_type='rent',
                min_deposit=400_000_000,
                max_deposit=800_000_000,
                min_rent=15_000_000,
                max_rent=35_000_000,
                min_area=75,
                max_area=130,
                is_auto_crawl_active=True
            )
            profile.active_districts = ['پونک', 'جنت‌آباد', 'شاهین']
            db.session.add(profile)
            db.session.commit()
            print("✅ پروفایل جدید با موفقیت ایجاد شد.")
        else:
            print(f"✅ پروفایل از پیش موجود بازیابی شد: ID={profile.id}")

        # گام ۲: درج یا اطمینان از وجود فایل‌های منطقه‌ای معتبر در PropertyListing
        print("\n[گام ۲] بررسی و درج داده‌های نمونه در PropertyListing با تگ مستقیم لینک آگهی...")
        sample_listings_data = [
            {
                'ad_code': '50101',
                'title': 'آپارتمان ۸۵ متری فول امکانات پونک همیلا',
                'district': 'پونک',
                'city': 'تهران',
                'region': '5',
                'deal_type': 'rent',
                'deposit': 550_000_000,
                'monthly_rent': 22_000_000,
                'area': 85,
                'rooms': 2,
                'floor': 3,
                'build_year': 1401,
                'has_parking': True,
                'has_elevator': True,
                'has_warehouse': True,
                'has_balcony': True,
                'phone_number': '09121112233',
                'source_url': 'https://divar.ir/v/50101'
            },
            {
                'ad_code': '50102',
                'title': '۹۵ متر ۲ خوابه نوساز جنت‌آباد مرکزی مخبری',
                'district': 'جنت‌آباد',
                'city': 'تهران',
                'region': '5',
                'deal_type': 'rent',
                'deposit': 650_000_000,  # مشمول تلورانس ۱۰٪ سقف ۶۰۰ میلیون (۶۰۰ * ۱.۱۰ = ۶۶۰)
                'monthly_rent': 24_000_000,
                'area': 95,
                'rooms': 2,
                'floor': 2,
                'build_year': 1402,
                'has_parking': True,
                'has_elevator': True,
                'has_warehouse': True,
                'has_balcony': True,
                'phone_number': '09123334455',
                'source_url': 'https://divar.ir/v/50102'
            },
            {
                'ad_code': '50103',
                'title': '۸۰ متری خوش‌نقشه شاهین شمالی لاله',
                'district': 'شاهین',
                'city': 'تهران',
                'region': '5',
                'deal_type': 'rent',
                'deposit': 500_000_000,
                'monthly_rent': 20_000_000,
                'area': 80,
                'rooms': 2,
                'floor': 4,
                'build_year': 1398,
                'has_parking': True,
                'has_elevator': True,
                'has_warehouse': False,
                'has_balcony': True,
                'phone_number': '09125556677',
                'source_url': 'https://divar.ir/v/50103'
            },
            {
                'ad_code': '50104',
                'title': '۱۲۰ متری لوکس سعادت‌آباد علامه (خارج از منطقه درخواستی و بودجه)',
                'district': 'سعادت‌آباد',
                'city': 'تهران',
                'region': '2',
                'deal_type': 'rent',
                'deposit': 1_200_000_000,  # فراتر از تلورانس ۱۰٪
                'monthly_rent': 50_000_000,
                'area': 120,
                'rooms': 3,
                'floor': 5,
                'build_year': 1400,
                'has_parking': True,
                'has_elevator': True,
                'has_warehouse': True,
                'has_balcony': True,
                'phone_number': '09127778899',
                'source_url': 'https://divar.ir/v/50104'
            }
        ]

        for s in sample_listings_data:
            exist = PropertyListing.query.filter_by(ad_code=s['ad_code']).first()
            if not exist:
                pl = PropertyListing(
                    ad_code=s['ad_code'],
                    source='divar',
                    source_url=s['source_url'],
                    title=s['title'],
                    city=s['city'],
                    region=s['region'],
                    district=s['district'],
                    deal_type=s['deal_type'],
                    deposit=s['deposit'],
                    monthly_rent=s['monthly_rent'],
                    area=s['area'],
                    rooms=s['rooms'],
                    floor=s['floor'],
                    build_year=s['build_year'],
                    has_parking=s['has_parking'],
                    has_elevator=s['has_elevator'],
                    has_warehouse=s['has_warehouse'],
                    has_balcony=s['has_balcony'],
                    phone_number=s['phone_number'],
                    is_personal_owner=True
                )
                db.session.add(pl)
        db.session.commit()
        print(f"✅ {len(sample_listings_data)} فایل با موفقیت در پایگاه داده مستقر شدند.")

        # گام ۳: شبیه‌سازی وب‌هوک مرکز تماس VoIP
        print("\n[گام ۳] شبیه‌سازی فراخوانی وب‌هوک /api/v1/telephony/call-recorded...")
        client = app.test_client()
        call_payload = {
            'call_id': 'VOIP-TEST-9921',
            'caller_phone': '09129998877',
            'call_duration': 45,
            'audio_url': 'https://cdn.saghf.ir/records/voip-test-9921.mp3',
            'transcribed_text': (
                "سلام خسته نباشید، من دنبال رهن و اجاره یک واحد آپارتمان حدود ۸۰ تا ۹۰ متری در محله پونک یا جنت‌آباد هستم. "
                "حداکثر ودیعه من ششصد میلیون تومان هست و توان پرداخت تا بیست و پنج میلیون اجاره در ماه رو دارم. "
                "پارکینگ و آسانسور حتماً داشته باشه و ترجیحاً پیام‌ها به تلگرام من ارسال بشه."
            )
        }

        resp = client.post('/api/v1/telephony/call-recorded', json=call_payload)
        assert resp.status_code == 200, f"Webhook failed: {resp.status_code} - {resp.data}"
        resp_data = resp.get_json()
        print("✅ پاسخ موفقیت‌آمیز وب‌هوک دریافت شد:")
        print(f"   - شناسه تماس: {resp_data.get('call_id')}")
        print(f"   - موتور پیاده‌سازی: {resp_data.get('transcription_engine')}")
        print(f"   - شروط استخراج‌شده NLP: {resp_data.get('criteria')}")

        # گام ۴: راستی‌آزمایی رکوردهای ذخیره‌شده در دیتابیس
        print("\n[گام ۴] بررسی ثبت صحیح در CallRecord و CustomerLead...")
        call_rec = CallRecord.query.filter_by(call_id='VOIP-TEST-9921').first()
        assert call_rec is not None, "CallRecord ذخیره نشد!"
        print(f"✅ رکورد تماس با وضعیت '{call_rec.processing_status}' در دیتابیس یافت شد.")

        cust_lead = CustomerLead.query.filter_by(phone_number='09129998877').first()
        assert cust_lead is not None, "CustomerLead ایجاد نشد!"
        assert cust_lead.deal_type == 'rent', "نوع معامله باید rent باشد!"
        assert cust_lead.max_deposit == 600_000_000, f"ودیعه نادرست: {cust_lead.max_deposit}"
        assert cust_lead.max_rent == 25_000_000, f"اجاره نادرست: {cust_lead.max_rent}"
        assert 'پونک' in cust_lead.preferred_districts, "پونک در محله‌ها یافت نشد!"
        print(f"✅ سرنخ متقاضی با موفقیت در جدول CustomerLead ایجاد شد (ID: {cust_lead.id}).")

        # گام ۵: ارزیابی موتور تطبیق منطقه‌ای و تلورانس ۱۰٪
        print("\n[گام ۵] اجرای موتور تطبیق منطقه‌ای با تلورانس ۱۰٪...")
        matches = RegionalPropertyMatcher.match_lead(cust_lead, limit=3)
        print(f"✅ تعداد {len(matches)} فایل برتر منطقه‌ای انتخاب شد:")
        matched_codes = [m['ad_code'] for m in matches]
        for m in matches:
            print(f"   ★ کد {m['ad_code']}: {m['title']} | امتیاز: {m['match_score']}٪ | دلایل: {', '.join(m['match_reasons'])}")

        assert '50101' in matched_codes, "کد 50101 باید در تطابق‌ها باشد!"
        assert '50102' in matched_codes, "کد 50102 (با تلورانس ۱۰٪) باید پذیرفته می‌شد!"
        assert '50104' not in matched_codes, "کد 50104 (سعادت‌آباد و بیش از تلورانس) نباید انتخاب می‌شد!"
        print("✅ قوانین تلورانس ۱۰٪ بودجه و تطابق منطقه‌ای با دقت ۱۰۰٪ تأیید گردید.")

        # گام ۶: ارزیابی ارسال چندکاناله و لاگ‌های OutreachLog
        print("\n[گام ۶] بررسی ثبت لاگ در جدول OutreachLog...")
        logs = OutreachLog.query.filter_by(lead_id=cust_lead.id).all()
        assert len(logs) > 0, "لاگ‌های ارسال در OutreachLog ثبت نشدند!"
        print(f"✅ تعداد {len(logs)} لاگ ارسال در OutreachLog ثبت شد:")
        for l in logs:
            print(f"   - کد فایل: {l.property_code} | پلتفرم: {l.platform} | وضعیت: {l.status}")

        # گام ۷: تأیید قانون AGENTS.md برای تگ مستقیم لینک آگهی
        print("\n[گام ۷] بررسی تگ معتبر و مستقیم <a href='...'>لینک آگهی</a>...")
        for m in matches:
            formatted_text = RegionalPropertyMatcher.format_recommendation_text(m)
            assert 'لینک آگهی' in formatted_text, "برچسب لینک آگهی یافت نشد!"
            assert '<a href=' in formatted_text, "تگ <a> یافت نشد!"
            print(f"✅ برچسب 'لینک آگهی' با تگ <a> معتبر برای فایل {m['ad_code']} احراز شد.")

        print("\n" + "=" * 60)
        print("🎉 تمام ۷ گام آزمون پایپلاین هوشمند با موفقیت ۱۰۰٪ پاس شدند!")
        print("=" * 60)

if __name__ == '__main__':
    run_test()
