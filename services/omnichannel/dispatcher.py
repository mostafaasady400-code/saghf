"""
هسته مرکزی دیسپچ و توزیع چندکاناله (Omnichannel Dispatcher)
با الگوی Adapter، مدیریت ثبت لاگ در جدول OutreachLog و پاسخگویی سریع
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from database.db import db
from database.models import CustomerLead, OutreachLog
from services.regional_matching import RegionalPropertyMatcher
from .base import BaseChannelAdapter
from .telegram_adapter import TelegramAdapter
from .bale_adapter import BaleAdapter
from .eitaa_adapter import EitaaAdapter
from .whatsapp_adapter import WhatsAppAdapter
from .rubika_adapter import RubikaAdapter

logger = logging.getLogger(__name__)

class OmnichannelDispatcher:
    """
    هماهنگ‌کننده و توزیع‌کننده بسته‌های ملکی و پیام‌ها به متقاضیان در پیام‌رسان‌های مختلف
    (Telegram, Bale, Eitaa, WhatsApp, Rubika)
    مجهز به ردیابی تاخیر، ثبت لاگ در OutreachLog، ارسال دسته‌ای و مسیریابی جایگزین
    """

    SUPPORTED_PLATFORMS = ['telegram', 'bale', 'eitaa', 'whatsapp', 'rubika']

    def __init__(self):
        self.adapters: Dict[str, BaseChannelAdapter] = {
            'telegram': TelegramAdapter(),
            'bale': BaleAdapter(),
            'eitaa': EitaaAdapter(),
            'whatsapp': WhatsAppAdapter(),
            'rubika': RubikaAdapter()
        }
        self._metrics = {
            'total_dispatches': 0,
            'successful_dispatches': 0,
            'failed_dispatches': 0,
            'platform_counts': {p: 0 for p in self.SUPPORTED_PLATFORMS},
            'total_latency_ms': 0.0
        }

    def get_adapter(self, platform_name: str) -> BaseChannelAdapter:
        plat = (platform_name or 'telegram').lower().strip()
        return self.adapters.get(plat, self.adapters['telegram'])

    def dispatch_to_lead(
        self,
        lead: CustomerLead,
        property_items: List[Dict[str, Any]],
        platform: Optional[str] = None,
        enable_fallback: bool = True
    ) -> List[Dict[str, Any]]:
        """
        ارسال پکیج گزینش‌شده فایل‌های ملکی به متقاضی و ثبت لاگ در OutreachLog
        همراه با پشتیبانی از بازگشت به پیام‌رسان جایگزین در صورت خطا
        """
        target_platform = (platform or lead.active_messenger or 'telegram').lower().strip()
        adapter = self.get_adapter(target_platform)
        recipient = lead.phone_number

        dispatch_results = []

        for idx, item in enumerate(property_items, 1):
            t_start = time.perf_counter()
            text_package = RegionalPropertyMatcher.format_recommendation_text(item, rank=idx)

            try:
                res = adapter.send_property_package(recipient, item, text_package)
            except Exception as e:
                logger.error(f"Error dispatching item {item.get('ad_code')} via {target_platform}: {e}")
                res = {'success': False, 'error': str(e), 'platform': target_platform}

            # در صورت عدم موفقیت و فعال بودن fallback، ارسال از طریق پلتفرم پشتیبان (مثلا بله یا تلگرام)
            if not res.get('success') and enable_fallback:
                fallback_plat = 'bale' if target_platform == 'telegram' else 'telegram'
                fallback_adapter = self.get_adapter(fallback_plat)
                try:
                    fb_res = fallback_adapter.send_property_package(recipient, item, text_package)
                    if fb_res.get('success'):
                        res = fb_res
                        target_platform = fallback_plat
                        adapter = fallback_adapter
                except Exception as fbe:
                    logger.debug(f"Fallback to {fallback_plat} also failed: {fbe}")

            t_elapsed_ms = (time.perf_counter() - t_start) * 1000
            is_sent = res.get('success', False)
            status = 'sent' if is_sent else 'failed'

            # تله‌متری
            self._metrics['total_dispatches'] += 1
            if is_sent:
                self._metrics['successful_dispatches'] += 1
            else:
                self._metrics['failed_dispatches'] += 1
            self._metrics['platform_counts'][adapter.platform_name] = (
                self._metrics['platform_counts'].get(adapter.platform_name, 0) + 1
            )
            self._metrics['total_latency_ms'] += t_elapsed_ms

            # ثبت در پایگاه داده در جدول OutreachLog
            try:
                listing_id = item.get('id') if item.get('source_type') == 'listing' else None
                ad_code = str(item.get('ad_code') or '---')

                log_entry = OutreachLog(
                    lead_id=lead.id,
                    property_listing_id=listing_id,
                    property_code=ad_code,
                    platform=adapter.platform_name,
                    status=status,
                    server_response=json.dumps(res, ensure_ascii=False),
                    sent_at=datetime.utcnow()
                )
                db.session.add(log_entry)
                db.session.commit()
            except Exception as dbe:
                logger.error(f"Error recording OutreachLog: {dbe}")
                db.session.rollback()

            dispatch_results.append({
                'property_code': item.get('ad_code'),
                'platform': adapter.platform_name,
                'status': status,
                'latency_ms': round(t_elapsed_ms, 2),
                'details': res
            })

        return dispatch_results

    def dispatch_direct_message(self, recipient: str, message: str, platform: str = 'telegram') -> Dict[str, Any]:
        """
        ارسال پیام مستقیم (متن، لینک خوش‌آمد یا هشدارهای سامانه) به مالک یا متقاضی
        """
        t_start = time.perf_counter()
        target_platform = (platform or 'telegram').lower().strip()
        adapter = self.get_adapter(target_platform)

        try:
            res = adapter.send_text(recipient, message)
        except Exception as e:
            logger.error(f"Error sending direct message via {target_platform} to {recipient}: {e}")
            res = {'success': False, 'error': str(e), 'platform': target_platform}

        t_elapsed_ms = (time.perf_counter() - t_start) * 1000
        res['latency_ms'] = round(t_elapsed_ms, 2)

        # تله‌متری
        self._metrics['total_dispatches'] += 1
        if res.get('success'):
            self._metrics['successful_dispatches'] += 1
        else:
            self._metrics['failed_dispatches'] += 1
        self._metrics['platform_counts'][target_platform] = (
            self._metrics['platform_counts'].get(target_platform, 0) + 1
        )
        self._metrics['total_latency_ms'] += t_elapsed_ms

        try:
            log_entry = OutreachLog(
                lead_id=None,
                property_code='direct_msg',
                platform=target_platform,
                status='sent' if res.get('success') else 'failed',
                server_response=json.dumps(res, ensure_ascii=False),
                sent_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception:
            db.session.rollback()

        return res

    def batch_dispatch_direct(
        self,
        recipients: List[str],
        message: str,
        platform: str = 'telegram'
    ) -> List[Dict[str, Any]]:
        """
        ارسال دسته‌ای پیام به چندین مخاطب به صورت منظم با ثبت جداگانه وضعیت هر گیرنده
        """
        results = []
        for rec in recipients:
            if not rec:
                continue
            r = self.dispatch_direct_message(rec, message, platform=platform)
            results.append({
                'recipient': rec,
                'platform': platform,
                'success': r.get('success', False),
                'latency_ms': r.get('latency_ms', 0.0),
                'details': r
            })
        return results

    def get_dispatch_metrics(self) -> Dict[str, Any]:
        """گزارش شاخص‌های عملیاتی و تله‌متری دیسپچر چندکاناله"""
        tot = self._metrics['total_dispatches']
        succ = self._metrics['successful_dispatches']
        avg_lat = (self._metrics['total_latency_ms'] / tot) if tot > 0 else 0.0
        success_rate = (succ / tot * 100.0) if tot > 0 else 100.0

        return {
            'total_dispatches': tot,
            'successful_dispatches': succ,
            'failed_dispatches': self._metrics['failed_dispatches'],
            'success_rate_pct': round(success_rate, 2),
            'avg_latency_ms': round(avg_lat, 2),
            'platform_breakdown': dict(self._metrics['platform_counts'])
        }

omnichannel_dispatcher = OmnichannelDispatcher()

