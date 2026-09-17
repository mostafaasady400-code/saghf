"""
آداپتور ارسال پیام‌رسان بله (Bale Bot Adapter)
استفاده از API رسمی بله: https://tapi.bale.ai/bot{token}/sendMessage
"""

import os
import logging
import requests
from typing import Dict, Any
from .base import BaseChannelAdapter

logger = logging.getLogger(__name__)

class BaleAdapter(BaseChannelAdapter):
    BASE_URL = "https://tapi.bale.ai/bot"

    def __init__(self, token: str = None):
        self.token = token or os.getenv('BALE_BOT_TOKEN', '')

    @property
    def platform_name(self) -> str:
        return 'bale'

    def send_text(self, recipient: str, text: str) -> Dict[str, Any]:
        if not self.token:
            logger.info("Bale token not configured; simulating payload generation.")
            return {
                'success': True,
                'simulated': True,
                'platform': self.platform_name,
                'recipient': recipient,
                'note': 'توکن بله در .env تنظیم نشده است (ارسال شبیه‌سازی شد).'
            }

        url = f"{self.BASE_URL}{self.token}/sendMessage"
        payload = {
            'chat_id': recipient,
            'text': text,
            'parse_mode': 'HTML'
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return {
                    'success': True,
                    'platform': self.platform_name,
                    'response': resp.json()
                }
            return {
                'success': False,
                'platform': self.platform_name,
                'status_code': resp.status_code,
                'error': resp.text
            }
        except Exception as e:
            logger.error(f"BaleAdapter exception: {e}")
            return {'success': False, 'platform': self.platform_name, 'error': str(e)}

    def send_property_package(self, recipient: str, property_item: Dict[str, Any], text: str) -> Dict[str, Any]:
        # پیام‌رسان بله متن همراه با لینک آگهی را ارسال می‌کند
        return self.send_text(recipient, text)
