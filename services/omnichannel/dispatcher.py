"""
هسته مرکزی دیسپچ و توزیع چندکاناله (Omnichannel Dispatcher)
با الگوی Adapter، مدیریت ثبت لاگ در جدول OutreachLog و پاسخگویی سریع
"""

import json
import logging
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
    هماهنگ‌کننده و توزیع‌کننده بسته‌های ملکی به متقاضیان در پیام‌رسان‌های مختلف
    """

    def __init__(self):
        self.adapters: Dict[str, BaseChannelAdapter] = {
            'telegram': TelegramAdapter(),
            'bale': BaleAdapter(),
            'eitaa': EitaaAdapter(),
            'whatsapp': WhatsAppAdapter(),
            'rubika': RubikaAdapter()
        }

    def get_adapter(self, platform_name: str) -> BaseChannelAdapter:
        plat = (platform_name or 'telegram').lower().strip()
        return self.adapters.get(plat, self.adapters['telegram'])

    def dispatch_to_lead(self, lead: CustomerLead, property_items: List[Dict[str, Any]], platform: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        ارسال پکیج گزینش‌شده فایل‌های ملکی به متقاضی و ثبت لاگ در OutreachLog
        """
        target_platform = platform or lead.active_messenger or 'telegram'
        adapter = self.get_adapter(target_platform)
        recipient = lead.phone_number

        dispatch_results = []

        for idx, item in enumerate(property_items, 1):
            text_package = RegionalPropertyMatcher.format_recommendation_text(item, rank=idx)
            
            try:
                res = adapter.send_property_package(recipient, item, text_package)
            except Exception as e:
                logger.error(f"Error dispatching item {item.get('ad_code')} via {target_platform}: {e}")
                res = {'success': False, 'error': str(e), 'platform': target_platform}

            is_sent = res.get('success', False)
            status = 'sent' if is_sent else 'failed'

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
                'details': res
            })

        return dispatch_results

omnichannel_dispatcher = OmnichannelDispatcher()
