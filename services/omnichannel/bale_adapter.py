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
        """ارسال کارت کامل ملک همراه با تصویر و دکمه‌های تعاملی در بله"""
        from bale_bot.client import bale_client
        images = property_item.get('images') or []
        prop_id = property_item.get('id')

        reply_markup = None
        if prop_id:
            from services.unified_bot_controller import UnifiedBotController
            reply_markup = UnifiedBotController.build_property_action_markup('bale', prop_id)

        if images and isinstance(images, list) and len(images) > 0:
            res = bale_client.send_photo(
                chat_id=recipient,
                photo=images[0],
                caption=text,
                reply_markup=reply_markup
            )
            return {
                'success': bool(res.get('ok')),
                'platform': self.platform_name,
                'response': res
            }
        return self.send_text(recipient, text)
