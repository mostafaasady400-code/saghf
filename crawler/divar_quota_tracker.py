"""
سیستم مدیریت و پایش سهمیه روزانه استخراج شماره تماس دیوار (Divar Quota Tracker)
جلوگیری از مسدودیت حساب کاربری و چالش کپچا با کنترل سقف مصرف مجاز در هر شبانه‌روز
"""
import os
import json
import logging
from datetime import datetime, date
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

QUOTA_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'instance',
    'divar_quota.json'
)

# حداکثر سقف مجاز استخراج در ۲۴ ساعت برای هر نشست جهت جلوگیری از ریت‌لیمیت دیوار
DEFAULT_DAILY_LIMIT = 25


class DivarQuotaTracker:
    """مدیریت سهمیه روزانه استخراج شماره‌های مالک برای حفظ سلامت نشست"""

    @classmethod
    def _ensure_dir(cls):
        os.makedirs(os.path.dirname(QUOTA_FILE_PATH), exist_ok=True)

    @classmethod
    def _get_today_str(cls) -> str:
        return date.today().isoformat()

    @classmethod
    def load_data(cls) -> Dict[str, Any]:
        cls._ensure_dir()
        if os.path.exists(QUOTA_FILE_PATH):
            try:
                with open(QUOTA_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception as e:
                logger.warning(f"[DivarQuotaTracker] خطا در خواندن سهمیه: {e}")
        return {}

    @classmethod
    def save_data(cls, data: Dict[str, Any]):
        cls._ensure_dir()
        try:
            with open(QUOTA_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[DivarQuotaTracker] خطا در ذخیره سهمیه: {e}")

    @classmethod
    def get_today_stats(cls, session_id: str = "default") -> Dict[str, Any]:
        """دریافت آمار سهمیه روز جاری برای یک نشست"""
        data = cls.load_data()
        today = cls._get_today_str()
        day_data = data.get(today, {}).get(session_id, {
            'used_count': 0,
            'success_count': 0,
            'limit': DEFAULT_DAILY_LIMIT,
            'chat_only_skipped': 0,
            'agency_skipped': 0,
            'extracted_tokens': []
        })
        limit = day_data.get('limit', DEFAULT_DAILY_LIMIT)
        used = day_data.get('used_count', 0)
        remaining = max(0, limit - used)
        return {
            'date': today,
            'session_id': session_id,
            'used_count': used,
            'success_count': day_data.get('success_count', 0),
            'limit': limit,
            'remaining': remaining,
            'can_extract': remaining > 0,
            'chat_only_skipped': day_data.get('chat_only_skipped', 0),
            'agency_skipped': day_data.get('agency_skipped', 0),
        }

    @classmethod
    def can_extract(cls, session_id: str = "default") -> bool:
        """بررسی اینکه آیا سهمیه روزانه برای استخراج شماره باقی مانده است"""
        stats = cls.get_today_stats(session_id)
        return stats['can_extract']

    @classmethod
    def record_attempt(
        cls,
        session_id: str = "default",
        token: str = "",
        success: bool = False,
        is_chat_only: bool = False,
        is_agency: bool = False
    ) -> Dict[str, Any]:
        """
        ثبت یک تلاش استخراج در سهمیه روزانه
        اگر آگهی چت‌محور یا متعلق به آژانس باشد، سهمیه روزانه مصرف نمی‌شود!
        """
        data = cls.load_data()
        today = cls._get_today_str()
        if today not in data:
            data[today] = {}
        if session_id not in data[today]:
            data[today][session_id] = {
                'used_count': 0,
                'success_count': 0,
                'limit': DEFAULT_DAILY_LIMIT,
                'chat_only_skipped': 0,
                'agency_skipped': 0,
                'extracted_tokens': []
            }

        s_entry = data[today][session_id]

        if is_chat_only:
            s_entry['chat_only_skipped'] = s_entry.get('chat_only_skipped', 0) + 1
            logger.info(f"[DivarQuotaTracker] آگهی {token} چت‌محور است؛ سهمیه مصرف نشد.")
        elif is_agency:
            s_entry['agency_skipped'] = s_entry.get('agency_skipped', 0) + 1
            logger.info(f"[DivarQuotaTracker] آگهی {token} آژانس/مشاور است؛ سهمیه مصرف نشد.")
        else:
            s_entry['used_count'] = s_entry.get('used_count', 0) + 1
            if success:
                s_entry['success_count'] = s_entry.get('success_count', 0) + 1
                if token and token not in s_entry.get('extracted_tokens', []):
                    s_entry.setdefault('extracted_tokens', []).append(token)
            logger.info(
                f"[DivarQuotaTracker] استخراج شماره {token} ثبت شد (موفق: {success}). "
                f"مصرف: {s_entry['used_count']}/{s_entry.get('limit', DEFAULT_DAILY_LIMIT)}"
            )

        cls.save_data(data)
        return cls.get_today_stats(session_id)

    @classmethod
    def set_limit(cls, new_limit: int, session_id: str = "default"):
        """تنظیم سقف مجاز روزانه"""
        data = cls.load_data()
        today = cls._get_today_str()
        if today not in data:
            data[today] = {}
        if session_id not in data[today]:
            data[today][session_id] = {
                'used_count': 0,
                'success_count': 0,
                'limit': new_limit,
                'chat_only_skipped': 0,
                'agency_skipped': 0,
                'extracted_tokens': []
            }
        else:
            data[today][session_id]['limit'] = new_limit
        cls.save_data(data)
