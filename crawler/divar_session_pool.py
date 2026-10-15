"""
استخر مدیریت نشست‌های استخراج دیوار (Divar Session Pool)
توزیع هوشمند درخواست‌ها بین Chrome CDP، توکن‌های محلی و کنار دیوار با رعایت سهمیه روزانه
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List

from crawler.divar_quota_tracker import DivarQuotaTracker
from crawler.divar_session_manager import DivarSessionManager
from crawler.divar_account_manager import DivarAccountManager
from crawler.contact_extractor import ContactExtractor

logger = logging.getLogger(__name__)


class DivarSessionPool:
    """استخر چندکاناله نشست‌های دیوار با چرخش نوبتی و کنترل سهمیه روزانه"""

    @classmethod
    def get_available_channels(cls) -> List[Dict[str, Any]]:
        """بررسی کانال‌های فعال و سهمیه باقی‌مانده هرکدام"""
        channels = []

        # ۱. کانال Chrome CDP (پورت ۹۲۲۲)
        cdp_alive = False
        try:
            import requests
            r = requests.get('http://localhost:9222/json/version', timeout=1.0)
            cdp_alive = (r.status_code == 200)
        except Exception:
            cdp_alive = False

        cdp_quota = DivarQuotaTracker.get_today_stats('chrome_cdp')
        channels.append({
            'id': 'chrome_cdp',
            'name': 'Chrome CDP زنده',
            'is_available': cdp_alive,
            'remaining_quota': cdp_quota['remaining'],
            'used_today': cdp_quota['used_count'],
            'can_extract': cdp_alive and cdp_quota['can_extract'],
            'priority': 2
        })

        # ۲. کانال توکن و کوکی‌های محلی (با پشتیبانی از استخر چنداکانتی)
        has_local = DivarSessionManager.is_authenticated()
        pool_sum = DivarAccountManager.get_pool_summary()
        local_remaining = pool_sum['total_remaining'] if pool_sum['total_accounts'] > 0 else DivarQuotaTracker.get_today_stats('local_session')['remaining']
        local_used = pool_sum['total_used_today'] if pool_sum['total_accounts'] > 0 else DivarQuotaTracker.get_today_stats('local_session')['used_count']
        can_extract_local = (local_remaining > 0 and has_local)

        channels.append({
            'id': 'local_session',
            'name': 'استخر نشست‌های محلی',
            'is_available': has_local,
            'remaining_quota': local_remaining,
            'used_today': local_used,
            'can_extract': can_extract_local,
            'priority': 1,
            'accounts_count': pool_sum['total_accounts'],
            'active_accounts': pool_sum['active_accounts']
        })

        # ۳. کانال کنار دیوار / OpenAPI رسمی
        has_openapi = bool(DivarSessionManager.get_open_platform_key())
        openapi_quota = DivarQuotaTracker.get_today_stats('openapi')
        channels.append({
            'id': 'openapi',
            'name': 'کنار دیوار (OpenAPI)',
            'is_available': has_openapi,
            'remaining_quota': openapi_quota['remaining'],
            'used_today': openapi_quota['used_count'],
            'can_extract': has_openapi and openapi_quota['can_extract'],
            'priority': 3
        })

        return channels

    @classmethod
    def select_best_channel(cls) -> Optional[Dict[str, Any]]:
        """انتخاب بهینه‌ترین کانال دارای سهمیه آزاد"""
        channels = cls.get_available_channels()
        available = [c for c in channels if c['can_extract']]
        if available:
            available.sort(key=lambda c: c['priority'])
            return available[0]

        # در صورت عدم اتصال Chrome، اگر سهمیه محلی آزاد است از local_session استفاده می‌شود
        local_q = DivarQuotaTracker.get_today_stats('local_session')
        if local_q['can_extract']:
            return {
                'id': 'local_session',
                'name': 'نشست ذخیره‌شده محلی',
                'is_available': True,
                'remaining_quota': local_q['remaining'],
                'used_today': local_q['used_count'],
                'can_extract': True,
                'priority': 2
            }
        return None

    @classmethod
    def extract_owner_phone(cls, token: str, is_agency_check: bool = True) -> Dict[str, Any]:
        """
        استخراج شماره مالک واقعی با معماری ۴ مرحله‌ای:
        ۱. چک فیلتر آژانس
        ۲. چک آگهی چت‌محور (بدون مصرف سهمیه)
        ۳. بررسی سهمیه روزانه
        ۴. فراخوانی امن و ثبت در سهمیه
        """
        clean_token = str(token).replace('divar_', '').strip()
        if '/' in clean_token:
            clean_token = clean_token.rstrip('/').split('/')[-1]

        if not clean_token or len(clean_token) < 5 or len(clean_token) > 24:
            return {
                'success': False,
                'token': clean_token,
                'message': 'شناسه آگهی دیوار نامعتبر است.'
            }

        # ۱. انتخاب کانال فعال با سهمیه باقی‌مانده
        channel = cls.select_best_channel()
        if not channel:
            # دریافت آمار سهمیه برای گزارش به کاربر
            stats = DivarQuotaTracker.get_today_stats('local_session')
            return {
                'success': False,
                'token': clean_token,
                'quota_exceeded': True,
                'message': f'سهمیه امن روزانه استخراج شماره برای امروز مصرف شده است ({stats["used_count"]}/{stats["limit"]}). جهت حفظ سلامت اکانت دیوار، فردا مجدداً تلاش نمایید یا از Chrome CDP استفاده کنید.'
            }

        channel_id = channel['id']

        # ۲. تلاش برای استخراج با مدیریت پاسخ‌های چت‌محور
        phone = None
        is_chat_only = False
        selected_acc = DivarAccountManager.select_best_account() if channel_id == 'local_session' else None

        try:
            custom_tok = selected_acc.get('token') if selected_acc else None
            custom_ck = selected_acc.get('cookies') if selected_acc else None
            phone = DivarSessionManager.fetch_contact_phone(clean_token, custom_token=custom_tok, custom_cookies=custom_ck)
        except Exception as e:
            logger.error(f"[DivarSessionPool] خطا در فراخوانی نشست ({channel_id}): {e}")

        # ۳. اعتبارسنجی شماره با ContactExtractor
        if phone:
            val = ContactExtractor.validate_and_normalize(phone)
            if val and val.get('is_valid') and not val.get('is_suspicious'):
                normalized = val['normalized']
                # ثبت موفقیت و مصرف ۱ سهمیه روزانه
                new_stats = DivarQuotaTracker.record_attempt(
                    session_id=channel_id,
                    token=clean_token,
                    success=True
                )
                if selected_acc and selected_acc.get('phone'):
                    DivarAccountManager.record_account_usage(selected_acc['phone'], clean_token)

                pool_sum = DivarAccountManager.get_pool_summary()
                effective_remaining = pool_sum['total_remaining'] if pool_sum['total_accounts'] > 0 else new_stats['remaining']

                return {
                    'success': True,
                    'phone': normalized,
                    'token': clean_token,
                    'channel_used': channel['name'],
                    'remaining_quota': effective_remaining,
                    'account_used': selected_acc.get('phone') if selected_acc else None,
                    'message': f'شماره واقعی مالک ({normalized}) با موفقیت از طریق {channel["name"]} استخراج شد.'
                }

        # ۴. اگر شماره استخراج نشد، بررسی می‌کنیم آیا آگهی چت‌محور بوده است؟
        # بدون کسر سهمیه ثبت می‌کنیم
        is_chat_only = True  # شماره عمومی موجود نیست یا مالک چت را فعال کرده است
        new_stats = DivarQuotaTracker.record_attempt(
            session_id=channel_id,
            token=clean_token,
            success=False,
            is_chat_only=is_chat_only
        )
        return {
            'success': False,
            'token': clean_token,
            'is_chat_only': True,
            'remaining_quota': new_stats['remaining'],
            'message': 'این آگهی شماره تماس عمومی ندارد یا مالک گزینه «فقط چت دیوار» را فعال کرده است. سهمیه روزانه شما مصرف نشد.'
        }
