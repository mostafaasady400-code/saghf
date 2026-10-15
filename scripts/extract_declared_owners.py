"""
اسکریپت استخراج آنلاین شماره تلفن تمام مالکین ۱۰۰٪ تاییدشده دیوار
با استفاده از استخر چرخشی حساب‌های کاربری و ثبت مستقیم در دیتابیس
"""

import sys
import os
import time

# تنظیم مسیر پروژه
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import db
from database.models import Property, Owner
from crawler.divar_session_pool import DivarSessionPool
from crawler.strict_owner_guard import strict_decision
from crawler.text_phone_miner import TextPhoneMiner


def run_extraction():
    app = create_app()
    with app.app_context():
        all_props = Property.query.all()
        print(f"کل آگهی‌های دیتابیس: {len(all_props)}")

        # ۱. فیلتر قطعی و تطبیق ۱۰۰٪ با محافظ مستقل (StrictOwnerGuard)
        disqualified = 0
        declared_owners = []
        for p in all_props:
            guard = strict_decision(p.title, p.description)
            if guard.allowed:
                declared_owners.append(p)
                p.is_personal_owner = True
                p.owner_type = 'personal'
            else:
                if p.is_personal_owner:
                    p.is_personal_owner = False
                    p.owner_type = 'agency'
                    disqualified += 1
        db.session.commit()
        print(f"تعداد {disqualified} آگهی غیرمالک/واسطه/عکس تزیینی از لیست مالکین حذف شدند.")
        print(f"تعداد کل آگهی‌های ۱۰۰٪ تاییدشده مالک: {len(declared_owners)}")

        # ۳. استخراج متن‌کاو (Text Miner) برای مواردی که شماره در متن دارند
        for p in declared_owners:
            if not (p.owner and p.owner.phone_number and p.owner.phone_number.startswith('09')):
                m = TextPhoneMiner.mine_phone(p.description, p.title)
                if m and m.get('phone'):
                    phone = m['phone']
                    owner = Owner.query.filter_by(phone_number=phone).first()
                    if not owner:
                        owner = Owner(
                            full_name=p.title[:50] if p.title else 'مالک دیوار',
                            phone_number=phone,
                            notes='استخراج سریع از متن آگهی (بدون سهمیه)'
                        )
                        db.session.add(owner)
                        db.session.flush()
                    p.owner_id = owner.id
                    db.session.commit()
                    print(f"🎯 شماره از متن استخراج شد: {p.title[:25]} -> {phone}")

        needs_api = [p for p in declared_owners if not (p.owner and p.owner.phone_number and p.owner.phone_number.startswith('09'))]
        print(f"تعداد مالکین ۱۰۰٪ نیازمند استخراج آنلاین: {len(needs_api)}")

        extracted_count = 0
        chat_only_count = 0
        failed_count = 0

        for i, p in enumerate(needs_api, 1):
            token = None
            if p.source_url:
                parts = p.source_url.rstrip('/').split('/')
                if parts and len(parts[-1]) >= 6:
                    token = parts[-1]
            if not token and p.source_id:
                raw = p.source_id.replace('divar_', '')
                if len(raw) >= 6:
                    token = raw

            if not token:
                print(f"[{i}/{len(needs_api)}] شناسه آگهی پیدا نشد برای ID {p.id}")
                continue

            print(f"[{i}/{len(needs_api)}] در حال استخراج ID {p.id} ({p.title[:30]}) | توکن: {token} ...")
            res = DivarSessionPool.extract_owner_phone(token)

            if res.get('success') and res.get('phone'):
                phone = res['phone']
                owner = Owner.query.filter_by(phone_number=phone).first()
                if not owner:
                    owner = Owner(
                        full_name=p.title[:50] if p.title else 'مالک دیوار',
                        phone_number=phone,
                        notes=f"استخراج زنده دیوار ({res.get('channel_used')}) - توکن: {token}"
                    )
                    db.session.add(owner)
                    db.session.flush()
                p.owner_id = owner.id
                p.is_personal_owner = True
                db.session.commit()
                extracted_count += 1
                channel = res.get('channel_used', 'دیوار')
                acc = res.get('account_used') or 'استخر سشن'
                print(f"  ✅ استخراج موفق: {phone} | کانال: {channel} | سهمیه باقی‌مانده: {res.get('remaining_quota')}")
            elif res.get('is_chat_only'):
                chat_only_count += 1
                print("  💬 فقط چت دیوار (فاقد شماره تماس عمومی)")
            elif res.get('quota_exceeded'):
                print(f"  ⚠️ هشدار سهمیه: {res.get('message')}")
                break
            else:
                failed_count += 1
                print(f"  ❌ استخراج ناموفق: {res.get('message')}")

            time.sleep(1.8)

        print("\n" + "=" * 50)
        print(f"🏁 عملیات پایان یافت!")
        print(f"✅ شماره‌های واقعی استخراج‌شده: {extracted_count}")
        print(f"💬 آگهی‌های چت‌محور (بدون شماره عمومی): {chat_only_count}")
        print(f"❌ موارد رد شده/پیدانشده: {failed_count}")
        print("=" * 50)


if __name__ == '__main__':
    run_extraction()
