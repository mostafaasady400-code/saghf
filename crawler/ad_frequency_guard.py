"""
Ad Frequency Guard for Saghf Platform.
Detects stealth real-estate brokers by analyzing publication frequency per phone number.
If a phone number has posted > 2 distinct properties in 30 days, it is classified as a broker/agency.
"""

from __future__ import annotations

import sqlite3
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'saghf_database.db')


class AdFrequencyGuard:
    """
    محافظ فرکانس آگهی‌ها و کشف خودکار مشاورین پنهان‌کار.
    شماره‌هایی که بیش از ۲ آگهی در ماه ثبت کرده‌اند را به عنوان مشاور املاک شناسایی و بایگانی می‌کند.
    """

    MAX_PERSONAL_ADS_THRESHOLD = 2
    WINDOW_DAYS = 30

    @classmethod
    def _init_db(cls):
        """اطمینان از وجود جدول رکوردهای آگهی‌های هر شماره"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS phone_ad_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number VARCHAR(30) NOT NULL,
                    post_token VARCHAR(100) NOT NULL,
                    title VARCHAR(250),
                    district VARCHAR(100),
                    seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(phone_number, post_token)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS ix_phone_ad_records_phone 
                ON phone_ad_records(phone_number);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_phone_blacklist (
                    phone_number VARCHAR(30) PRIMARY KEY,
                    reason VARCHAR(250),
                    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    ad_count INTEGER DEFAULT 1
                );
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[AdFrequencyGuard] خطای مقداردهی اولیه پایگاه داده: {e}")

    @classmethod
    def normalize_phone(cls, phone: str) -> str:
        """نرمال‌سازی ارقام و پیش‌شماره به فرمت 09xxxxxxxxx"""
        digits = re.sub(r'\D', '', str(phone or ''))
        if digits.startswith('989') and len(digits) == 12:
            return '0' + digits[2:]
        if digits.startswith('9') and len(digits) == 10:
            return '0' + digits
        return digits

    @classmethod
    def record_ad(
        cls,
        phone: str,
        post_token: str,
        title: str = "",
        district: str = ""
    ) -> Dict[str, Any]:
        """
        ثبت مشاهده آگهی برای یک شماره و ارزیابی آنی وضعیت مالکیت.
        خروجی شامل نتیجه تصمیم‌گیری (is_broker, ad_count, reason).
        """
        cls._init_db()
        norm_phone = cls.normalize_phone(phone)
        if not norm_phone or not norm_phone.startswith('09') or len(norm_phone) != 11:
            return {
                'valid': False,
                'phone': norm_phone,
                'is_broker': False,
                'message': 'شماره موبایل نامعتبر است'
            }

        clean_token = str(post_token).replace('divar_', '').strip()
        if '/' in clean_token:
            clean_token = clean_token.rstrip('/').split('/')[-1]

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        try:
            # درج امن با نادیده گرفتن موارد تکراری
            cur.execute("""
                INSERT OR IGNORE INTO phone_ad_records (phone_number, post_token, title, district, seen_at)
                VALUES (?, ?, ?, ?, ?)
            """, (norm_phone, clean_token, title[:240], district[:95], datetime.utcnow()))
            conn.commit()
        except Exception as e:
            print(f"[AdFrequencyGuard] هشدار درج رکورد: {e}")

        # ارزیابی آمار در ۳۰ روز اخیر
        cutoff = datetime.utcnow() - timedelta(days=cls.WINDOW_DAYS)
        cur.execute("""
            SELECT count(DISTINCT post_token) 
            FROM phone_ad_records 
            WHERE phone_number = ? AND seen_at >= ?
        """, (norm_phone, cutoff))
        ad_count = cur.fetchone()[0]

        is_broker = ad_count > cls.MAX_PERSONAL_ADS_THRESHOLD
        reason = ""

        if is_broker:
            reason = f"فعالیت مشکوک به مشاور: ثبت {ad_count} آگهی ملکی متفاوت در ۳۰ روز اخیر (سقف مجاز مالک شخصی: {cls.MAX_PERSONAL_ADS_THRESHOLD})"
            # ثبت در بلک‌لیست مشاورین
            cur.execute("""
                INSERT OR REPLACE INTO broker_phone_blacklist (phone_number, reason, detected_at, ad_count)
                VALUES (?, ?, ?, ?)
            """, (norm_phone, reason, datetime.utcnow(), ad_count))
            conn.commit()
            conn.close()

            # اعمال در دیتابیس املاک
            cls.apply_broker_status_to_db(norm_phone, reason)
        else:
            reason = f"رفتار منطبق بر مالک شخصی ({ad_count} فایل در ماه اخیر)"
            conn.close()

        return {
            'valid': True,
            'phone': norm_phone,
            'token': clean_token,
            'ad_count': ad_count,
            'is_broker': is_broker,
            'reason': reason
        }

    @classmethod
    def is_blacklisted(cls, phone: str) -> bool:
        """بررسی بلک‌لیست مشاورین"""
        cls._init_db()
        norm_phone = cls.normalize_phone(phone)
        if not norm_phone:
            return False

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM broker_phone_blacklist WHERE phone_number = ?", (norm_phone,))
        found = cur.fetchone() is not None
        conn.close()
        return found

    @classmethod
    def apply_broker_status_to_db(cls, phone: str, reason: str):
        """تغییر وضعیت املاک ثبت‌شده با این شماره از مالک شخصی به واسطه در دیتابیس"""
        try:
            from app import create_app
            from database.db import db
            from database.models import Property, Owner

            app = create_app()
            with app.app_context():
                owner = Owner.query.filter_by(phone_number=phone).first()
                if owner:
                    props = Property.query.filter_by(owner_id=owner.id).all()
                    for p in props:
                        p.is_personal_owner = False
                        p.owner_type = 'agency'
                        p.filter_log = reason
                    db.session.commit()
                    if props:
                        print(f"[AdFrequencyGuard] تعداد {len(props)} فایل متعلق به شماره {phone} به واسطه تغییر یافتند.")
        except Exception as e:
            print(f"[AdFrequencyGuard] خطا در اعمال وضعیت مشاور: {e}")

    @classmethod
    def sync_from_existing_properties(cls) -> Dict[str, Any]:
        """
        همگام‌سازی و تحلیل داده‌های فعلی دیتابیس.
        تمامی شماره‌های موجود در جدول مالکین و املاک را اسکن و فرکانس آن‌ها را محاسبه می‌کند.
        """
        cls._init_db()
        try:
            from app import create_app
            from database.models import Property

            app = create_app()
            with app.app_context():
                all_props = Property.query.all()
                recorded = 0
                brokers_found = 0

                for p in all_props:
                    if p.owner and p.owner.phone_number:
                        tok = str(p.source_id or '').replace('divar_', '').strip()
                        if not tok and p.source_url:
                            tok = p.source_url.rstrip('/').split('/')[-1]
                        if tok:
                            res = cls.record_ad(
                                phone=p.owner.phone_number,
                                post_token=tok,
                                title=p.title,
                                district=p.district
                            )
                            recorded += 1
                            if res.get('is_broker'):
                                brokers_found += 1

                return {
                    'total_properties_scanned': len(all_props),
                    'records_indexed': recorded,
                    'brokers_flagged': brokers_found
                }
        except Exception as e:
            return {'error': str(e)}
