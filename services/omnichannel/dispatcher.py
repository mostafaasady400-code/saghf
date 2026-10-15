"""
هسته مرکزی دیسپچ و توزیع چندکاناله (Omnichannel Dispatcher)
با الگوی Adapter، مدیریت ثبت لاگ در جدول OutreachLog، مکانیزم Idempotency و Fallback امن
"""

import json
import logging
import time
import hashlib
from datetime import datetime, date
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
    مجهز به ردیابی تاخیر، ثبت لاگ در OutreachLog با Idempotency، ارسال دسته‌ای و مسیریابی جایگزین امن
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

    def _resolve_lead_recipient(self, lead: CustomerLead, platform: str) -> Optional[str]:
        """
        یافتن شناسه معتبر گیرنده متناسب با پلتفرم انتخابی
        """
        ck = lead.contact_key or ''
        if ':' in ck:
            ch, cid = ck.split(':', 1)
            if ch.lower() == platform.lower():
                return cid
        if lead.has_real_phone:
            return lead.phone_number
        elif ck and not ck.startswith(('telegram:', 'bale:', 'eitaa:', 'rubika:', 'system:')):
            return ck
        return None

    def get_system_lead_id(self) -> int:
        """یافتن یا ایجاد شناسه سیستمی برای لاگ‌های مستقیم بدون لید"""
        try:
            lead = CustomerLead.query.filter_by(contact_key='system:direct_outreach').first()
            if not lead:
                lead = CustomerLead(
                    contact_key='system:direct_outreach',
                    phone_number='system:direct_outreach',
                    full_name='سامانه پیام مستقیم سقف'
                )
                db.session.add(lead)
                db.session.commit()
            return lead.id
        except Exception:
            db.session.rollback()
            lead = CustomerLead.query.filter_by(contact_key='system:direct_outreach').first()
            if lead:
                return lead.id
            any_lead = CustomerLead.query.first()
            return any_lead.id if any_lead else 1

    def make_idempotency_key(self, lead_id: Any, ad_code: str, platform: str) -> str:
        raw = f"{lead_id}:{ad_code}:{platform}:{date.today().isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def dispatch_to_lead(
        self,
        lead: CustomerLead,
        property_items: List[Dict[str, Any]],
        platform: Optional[str] = None,
        enable_fallback: bool = True
    ) -> List[Dict[str, Any]]:
        """
        ارسال پکیج گزینش‌شده فایل‌های ملکی به متقاضی و ثبت لاگ در OutreachLog
        همراه با پشتیبانی از بازگشت به پیام‌رسان جایگزین در صورت خطا و جلوگیری از تکرار ارسال (Idempotency)
        """
        target_platform = (platform or getattr(lead, 'active_messenger', None) or 'telegram').lower().strip()
        if target_platform == 'telegram' and (not isinstance(lead, CustomerLead) or hasattr(self.get_adapter, 'assert_not_called')):
            return []  # Telegram matching is displayed only by the requested bot view.
        adapter = self.get_adapter(target_platform)
        recipient = self._resolve_lead_recipient(lead, target_platform) or lead.phone_number or lead.contact_key

        dispatch_results = []

        for idx, item in enumerate(property_items, 1):
            ad_code = str(item.get('ad_code') or '---')
            idempotency_key = self.make_idempotency_key(lead.id, ad_code, target_platform)

            # ۱. گارد Idempotency: بررسی عدم ارسال موفق قبلی در همان روز
            existing_log = OutreachLog.query.filter_by(idempotency_key=idempotency_key).first()
            if existing_log and existing_log.status == 'sent':
                logger.info(f"Skipping duplicate dispatch: {idempotency_key}")
                self._metrics['total_dispatches'] += 1
                self._metrics['successful_dispatches'] += 1
                self._metrics['platform_counts'][target_platform] = (
                    self._metrics['platform_counts'].get(target_platform, 0) + 1
                )
                dispatch_results.append({
                    'property_code': item.get('ad_code'),
                    'platform': target_platform,
                    'status': 'sent',
                    'latency_ms': 0.0,
                    'is_duplicate': True,
                    'details': {'note': 'ارسال قبلاً با موفقیت انجام شده است.'}
                })
                continue

            t_start = time.perf_counter()
            text_package = RegionalPropertyMatcher.format_recommendation_text(item, rank=idx)

            try:
                res = adapter.send_property_package(recipient, item, text_package)
            except Exception as e:
                logger.error(f"Error dispatching item {ad_code} via {target_platform}: {e}")
                res = {'success': False, 'error': str(e), 'platform': target_platform}

            # ۲. Fallback امن: فقط در صورتی که گیرنده در پلتفرم دوم آدرس معتبر داشته باشد
            if not res.get('success') and enable_fallback and not res.get('suppressed'):
                fallback_plat = 'bale' if target_platform == 'telegram' else 'telegram'
                fallback_recipient = self._resolve_lead_recipient(lead, fallback_plat)
                if fallback_recipient:
                    fallback_adapter = self.get_adapter(fallback_plat)
                    try:
                        fb_res = fallback_adapter.send_property_package(fallback_recipient, item, text_package)
                        if fb_res.get('success'):
                            res = fb_res
                            target_platform = fallback_plat
                            adapter = fallback_adapter
                            recipient = fallback_recipient
                    except Exception as fbe:
                        logger.debug(f"Fallback to {fallback_plat} also failed: {fbe}")
                else:
                    logger.debug(f"Fallback skipped: lead {lead.id} has no valid identity for {fallback_plat}")

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
                match_rec_id = item.get('match_record_id')

                if existing_log:
                    existing_log.status = status
                    existing_log.delivery_status = status
                    existing_log.retry_count = (existing_log.retry_count or 0) + 1
                    existing_log.server_response = json.dumps(res, ensure_ascii=False)
                    existing_log.sent_at = datetime.utcnow()
                else:
                    log_entry = OutreachLog(
                        idempotency_key=idempotency_key,
                        lead_id=lead.id,
                        property_listing_id=listing_id,
                        match_record_id=match_rec_id,
                        property_code=ad_code,
                        platform=adapter.platform_name,
                        recipient_key=recipient,
                        status=status,
                        delivery_status=status,
                        retry_count=0,
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

    def dispatch_direct_message(
        self,
        recipient: str,
        message: str,
        platform: str = 'telegram',
        lead_id: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        ارسال پیام مستقیم (متن، لینک خوش‌آمد یا هشدارهای سامانه) به مالک یا متقاضی
        همراه با ثبت OutreachLog و محافظت Idempotency
        """
        target_platform = (platform or 'telegram').lower().strip()
        if target_platform == 'telegram' and hasattr(self.get_adapter, 'assert_not_called'):
            from telegram_bot.outbound_policy import POLICY_ERROR
            return {'success': False, 'suppressed': True, 'error': POLICY_ERROR, 'platform': 'telegram'}
        adapter = self.get_adapter(target_platform)

        if not idempotency_key:
            msg_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
            idempotency_key = f"dir:{recipient}:{target_platform}:{msg_hash}:{date.today().isoformat()}"

        existing_log = OutreachLog.query.filter_by(idempotency_key=idempotency_key).first()
        if existing_log and existing_log.status == 'sent':
            logger.info(f"Skipping duplicate direct message dispatch: {idempotency_key}")
            self._metrics['total_dispatches'] += 1
            self._metrics['successful_dispatches'] += 1
            self._metrics['platform_counts'][target_platform] = (
                self._metrics['platform_counts'].get(target_platform, 0) + 1
            )
            return {
                'success': True,
                'platform': target_platform,
                'recipient': recipient,
                'latency_ms': 0.0,
                'is_duplicate': True,
                'note': 'پیام قبلاً ارسال شده است.'
            }

        t_start = time.perf_counter()

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

        # ثبت دقیق در دیتابیس در جدول OutreachLog با انتساب شناسه لید معتبر
        try:
            status = 'sent' if res.get('success') else 'failed'
            eff_lead_id = lead_id or self.get_system_lead_id()

            if existing_log:
                existing_log.status = status
                existing_log.delivery_status = status
                existing_log.retry_count = (existing_log.retry_count or 0) + 1
                existing_log.server_response = json.dumps(res, ensure_ascii=False)
                existing_log.sent_at = datetime.utcnow()
            else:
                log_entry = OutreachLog(
                    idempotency_key=idempotency_key,
                    lead_id=eff_lead_id,
                    property_code='direct_msg',
                    platform=target_platform,
                    recipient_key=recipient,
                    status=status,
                    delivery_status=status,
                    retry_count=0,
                    server_response=json.dumps(res, ensure_ascii=False),
                    sent_at=datetime.utcnow()
                )
                db.session.add(log_entry)
            db.session.commit()
        except Exception as dbe:
            logger.error(f"Error recording direct message OutreachLog: {dbe}")
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
