"""
آداپتور ارسال پیام‌رسان ایتا (Eitaa Bot Adapter)
مجهز به وب‌سرویس ایتا یار و مکانیزم تلاش مجدد خودکار (۳ بار Retry)
"""

import os
import time
import logging
import requests
from typing import Dict, Any
from .base import BaseChannelAdapter

logger = logging.getLogger(__name__)

class EitaaAdapter(BaseChannelAdapter):
    BASE_URL = "https://eitaayar.ir/api"

    def __init__(self, token: str = None):
        self.token = token or os.getenv('EITAA_BOT_TOKEN', '')

    @property
    def platform_name(self) -> str:
        return 'eitaa'

    def send_text(self, recipient: str, text: str) -> Dict[str, Any]:
        if not self.token:
            logger.info("Eitaa token not configured; simulating payload generation.")
            return {
                'success': True,
                'simulated': True,
                'platform': self.platform_name,
                'recipient': recipient,
                'note': 'توکن ایتا در .env تنظیم نشده است (ارسال شبیه‌سازی شد).'
            }

        url = f"{self.BASE_URL}/{self.token}/sendMessage"
        payload = {
            'chat_id': recipient,
            'text': text
        }

        max_retries = 3
        last_error = ""

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=10)
                if resp.status_code == 200:
                    return {
                        'success': True,
                        'platform': self.platform_name,
                        'response': resp.json(),
                        'attempt': attempt
                    }
                last_error = f"Status {resp.status_code}: {resp.text}"
            except Exception as e:
                last_error = str(e)
            
            if attempt < max_retries:
                time.sleep(attempt * 0.5)

        return {
            'success': False,
            'platform': self.platform_name,
            'retries_exhausted': True,
            'error': last_error
        }

    def send_property_package(self, recipient: str, property_item: Dict[str, Any], text: str) -> Dict[str, Any]:
        return self.send_text(recipient, text)
