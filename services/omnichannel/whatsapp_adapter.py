"""
آداپتور ارسال پیام‌رسان واتساپ (WhatsApp Cloud API Adapter)
"""

import os
import logging
import requests
from typing import Dict, Any
from .base import BaseChannelAdapter

logger = logging.getLogger(__name__)

class WhatsAppAdapter(BaseChannelAdapter):
    def __init__(self, token: str = None, phone_id: str = None):
        self.token = token or os.getenv('WHATSAPP_TOKEN', '')
        self.phone_id = phone_id or os.getenv('WHATSAPP_PHONE_ID', '')

    @property
    def platform_name(self) -> str:
        return 'whatsapp'

    def send_text(self, recipient: str, text: str) -> Dict[str, Any]:
        if not self.token or not self.phone_id:
            logger.info("WhatsApp credentials not configured; simulating payload generation.")
            return {
                'success': True,
                'simulated': True,
                'platform': self.platform_name,
                'recipient': recipient,
                'note': 'کلیدهای واتساپ در .env تنظیم نشده است (ارسال شبیه‌سازی شد).'
            }

        url = f"https://graph.facebook.com/v18.0/{self.phone_id}/messages"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        # تمیزکاری شماره موبایل
        to_phone = recipient.replace('+', '').replace(' ', '')
        if to_phone.startswith('0'):
            to_phone = '98' + to_phone[1:]

        payload = {
            'messaging_product': 'whatsapp',
            'to': to_phone,
            'type': 'text',
            'text': {'body': text}
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code in [200, 201]:
                return {'success': True, 'platform': self.platform_name, 'response': resp.json()}
            return {'success': False, 'platform': self.platform_name, 'status_code': resp.status_code, 'error': resp.text}
        except Exception as e:
            logger.error(f"WhatsAppAdapter error: {e}")
            return {'success': False, 'platform': self.platform_name, 'error': str(e)}

    def send_property_package(self, recipient: str, property_item: Dict[str, Any], text: str) -> Dict[str, Any]:
        return self.send_text(recipient, text)
