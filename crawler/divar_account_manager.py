"""
مدیریت استخر چنداکانتی حساب‌های دیوار (Multi-Account Session Matrix)
ذخیره، چرخش راند-رابین، پایش سهمیه روزانه و تمدید خودکار هر حساب به صورت مستقل
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from crawler.divar_quota_tracker import DivarQuotaTracker

logger = logging.getLogger(__name__)

ACCOUNTS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "instance",
    "divar_accounts.json"
)
TOKEN_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "divar_token.json"
)
STORAGE_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "divar_storage_state.json"
)


class DivarAccountManager:
    """مدیریت ماتریس حساب‌های دیوار با تمدید خودکار و چرخش سهمیه"""

    DAILY_LIMIT_PER_ACCOUNT = 25
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
        'Referer': 'https://divar.ir/'
    }

    @classmethod
    def _ensure_storage(cls) -> None:
        os.makedirs(os.path.dirname(ACCOUNTS_FILE_PATH), exist_ok=True)
        if not os.path.exists(ACCOUNTS_FILE_PATH):
            # اگر فایل وجود ندارد، در صورت وجود نشست در divar_token یا storage_state، اکانت اولیه را اضافه کن
            initial_accounts = []
            primary = cls._detect_legacy_account()
            if primary:
                initial_accounts.append(primary)
            with open(ACCOUNTS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(initial_accounts, f, ensure_ascii=False, indent=2)

    @classmethod
    def _detect_legacy_account(cls) -> Optional[Dict[str, Any]]:
        """تشخیص حساب اولیه موجود از فایل‌های توکن و نشست"""
        token = None
        phone = "09179001377"
        rt = None
        cookies_dict = {}

        if os.path.exists(TOKEN_FILE_PATH):
            try:
                with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                    tdata = json.load(f)
                    token = tdata.get('token')
                    phone = tdata.get('phone') or phone
            except Exception:
                pass

        if os.path.exists(STORAGE_STATE_PATH):
            try:
                with open(STORAGE_STATE_PATH, 'r', encoding='utf-8') as sf:
                    sdata = json.load(sf)
                    for c in sdata.get('cookies', []):
                        cookies_dict[c['name']] = c['value']
                        if c['name'] in ('refresh_token', 'sRefreshToken'):
                            rt = c['value']
                        if not token and c['name'] == 'sAccessToken':
                            token = c['value']
            except Exception:
                pass

        if token or rt:
            return {
                'phone': phone,
                'token': token,
                'refresh_token': rt,
                'cookies': cookies_dict,
                'is_active': True,
                'added_at': time.time(),
                'last_used_at': time.time(),
                'label': 'سیم‌کارت اصلی سیستم'
            }
        return None

    @classmethod
    def list_accounts(cls) -> List[Dict[str, Any]]:
        """لیست تمامی حساب‌ها به همراه آمار سهمیه روزانه هرکدام"""
        cls._ensure_storage()
        try:
            with open(ACCOUNTS_FILE_PATH, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
        except Exception as e:
            logger.error("Error reading accounts: %s", e)
            return []

        result = []
        for acc in accounts:
            phone = acc.get('phone', 'نامشخص')
            quota_key = f"acc_{phone}"
            stats = DivarQuotaTracker.get_today_stats(quota_key)

            item = dict(acc)
            # پنهان‌سازی مقادیر حساس در خروجی‌های لیست
            item['token_preview'] = (acc.get('token') or '')[:15] + '...' if acc.get('token') else ''
            item['has_refresh_token'] = bool(acc.get('refresh_token'))
            item['used_today'] = stats.get('used_count', 0)
            item['remaining_quota'] = stats.get('remaining', cls.DAILY_LIMIT_PER_ACCOUNT)
            item['can_extract'] = stats.get('can_extract', True) and acc.get('is_active', True)
            result.append(item)
        return result

    @classmethod
    def register_account(
        cls,
        phone: str,
        token: str,
        refresh_token: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        label: str = "سیم‌کارت فعال"
    ) -> bool:
        """ثبت یا به‌روزرسانی حساب جدید در استخر"""
        cls._ensure_storage()
        clean_phone = phone.strip()
        try:
            with open(ACCOUNTS_FILE_PATH, 'r', encoding='utf-8') as f:
                accounts = json.load(f)

            updated = False
            for acc in accounts:
                if acc.get('phone') == clean_phone:
                    acc['token'] = token
                    if refresh_token:
                        acc['refresh_token'] = refresh_token
                    if cookies:
                        acc['cookies'] = cookies
                    acc['is_active'] = True
                    acc['updated_at'] = time.time()
                    updated = True
                    break

            if not updated:
                accounts.append({
                    'phone': clean_phone,
                    'token': token,
                    'refresh_token': refresh_token,
                    'cookies': cookies or {},
                    'is_active': True,
                    'added_at': time.time(),
                    'last_used_at': 0,
                    'label': label
                })

            with open(ACCOUNTS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)

            # همگام‌سازی با فایل‌های اصلی سیستم
            from crawler.divar_session_manager import DivarSessionManager
            DivarSessionManager.save_token(token, phone=clean_phone)
            if cookies:
                DivarSessionManager.save_cookies_dict(cookies)

            logger.info("Account %s successfully registered in pool.", clean_phone)
            return True
        except Exception as e:
            logger.error("Error registering account %s: %s", clean_phone, e)
            return False

    @classmethod
    def remove_account(cls, phone: str) -> bool:
        """حذف یک حساب از استخر"""
        cls._ensure_storage()
        clean_phone = phone.strip()
        try:
            with open(ACCOUNTS_FILE_PATH, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            new_accounts = [a for a in accounts if a.get('phone') != clean_phone]
            with open(ACCOUNTS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(new_accounts, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Error removing account: %s", e)
            return False

    @classmethod
    def select_best_account(cls) -> Optional[Dict[str, Any]]:
        """
        انتخاب نوبتی (Round-Robin) حسابی که هنوز سهمیه آزاد دارد.
        حساب‌ها بر اساس کمترین استفاده امروز یا قدیمی‌ترین زمان استفاده مرتب می‌شوند.
        """
        accounts = cls.list_accounts()
        available = [a for a in accounts if a.get('can_extract') and (a.get('token') or a.get('refresh_token'))]
        if not available:
            return None

        # مرتب‌سازی: کمترین استفاده امروز، سپس قدیمی‌ترین زمان استفاده
        available.sort(key=lambda a: (a.get('used_today', 0), a.get('last_used_at', 0)))
        return available[0]

    @classmethod
    def refresh_account_token(cls, phone: str) -> Optional[str]:
        """تمدید خودکار توکن یک حساب با استفاده از refresh_token آن"""
        cls._ensure_storage()
        try:
            with open(ACCOUNTS_FILE_PATH, 'r', encoding='utf-8') as f:
                accounts = json.load(f)

            target = next((a for a in accounts if a.get('phone') == phone), None)
            if not target or not target.get('refresh_token'):
                return None

            rt = target['refresh_token']
            headers = dict(cls.HEADERS)
            res = requests.post(
                'https://api.divar.ir/v5/auth/refresh',
                json={'refresh_token': rt},
                headers=headers,
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                new_token = data.get('access_token')
                if new_token:
                    target['token'] = new_token
                    target['updated_at'] = time.time()
                    with open(ACCOUNTS_FILE_PATH, 'w', encoding='utf-8') as f:
                        json.dump(accounts, f, ensure_ascii=False, indent=2)
                    logger.info("Token refreshed for account %s.", phone)
                    return new_token
        except Exception as e:
            logger.error("Failed to refresh token for account %s: %s", phone, e)
        return None

    @classmethod
    def record_account_usage(cls, phone: str, token_ad: str) -> None:
        """ثبت مصرف سهمیه برای حساب مشخص"""
        cls._ensure_storage()
        quota_key = f"acc_{phone}"
        DivarQuotaTracker.record_attempt(session_id=quota_key, token=token_ad, success=True)

        try:
            with open(ACCOUNTS_FILE_PATH, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
            for acc in accounts:
                if acc.get('phone') == phone:
                    acc['last_used_at'] = time.time()
                    break
            with open(ACCOUNTS_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def get_pool_summary(cls) -> Dict[str, Any]:
        """گزارش خلاصه ظرفیت کلی استخر حساب‌ها"""
        accounts = cls.list_accounts()
        total_accounts = len(accounts)
        active_accounts = sum(1 for a in accounts if a.get('is_active'))
        total_remaining = sum(a.get('remaining_quota', 0) for a in accounts if a.get('is_active'))
        total_used = sum(a.get('used_today', 0) for a in accounts)
        max_daily_capacity = total_accounts * cls.DAILY_LIMIT_PER_ACCOUNT

        return {
            'total_accounts': total_accounts,
            'active_accounts': active_accounts,
            'total_remaining': total_remaining,
            'total_used_today': total_used,
            'max_daily_capacity': max_daily_capacity,
            'accounts': accounts
        }
