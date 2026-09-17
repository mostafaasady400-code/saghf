"""
اینترفیس انتزاعی آداپتورهای ارسال چندکاناله (Omnichannel Base Adapter)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseChannelAdapter(ABC):
    """
    کلاس پایه برای تمام پیام‌رسان‌ها (Telegram, Bale, Eitaa, WhatsApp, Rubika)
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """نام انگلیسی پلتفرم (telegram, bale, eitaa, whatsapp, rubika)"""
        pass

    @abstractmethod
    def send_text(self, recipient: str, text: str) -> Dict[str, Any]:
        """ارسال پیام متنی ساده یا ساختاریافته HTML"""
        pass

    @abstractmethod
    def send_property_package(self, recipient: str, property_item: Dict[str, Any], text: str) -> Dict[str, Any]:
        """ارسال پکیج کامل معرفی فایل ملکی همراه با عکس‌ها و لینک مستقیم آگهی"""
        pass
