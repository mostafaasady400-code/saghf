"""
=============================================================================
کلاینت اختصاصی و کامل ارتباط با API رسمی ربات بله (Bale Bot API Client)
مستندات مرجع: https://tapi.bale.ai/bot{token}/
پروتکل کاملاً منطبق بر معماری بات تلگرام با ساختار استاندارد JSON
=============================================================================
"""

import json
import logging
import requests
from typing import Dict, Any, List, Optional, Union
from config import Config

logger = logging.getLogger(__name__)


class BaleBotClient:
    """
    کلاینت رسمی پیام‌رسان بله برای تعامل با @Saghf_bot
    """
    BASE_URL = "https://tapi.bale.ai/bot"

    def __init__(self, token: Optional[str] = None):
        self.token = (token if token is not None else (Config.BALE_BOT_TOKEN or "")).strip()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SaghfRealEstateBot/2.0 (BaleClient)',
            'Content-Type': 'application/json'
        })

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Dict[str, Any]:
        """ارسال درخواست HTTP امن به سرورهای بله"""
        if not self.is_configured:
            logger.debug(f"[Bale Simulated] {endpoint} called without token.")
            return {
                'ok': True,
                'simulated': True,
                'result': {'message_id': 999999},
                'description': 'BALE_BOT_TOKEN is not configured; operation simulated.'
            }

        url = f"{self.BASE_URL}{self.token}/{endpoint}"
        try:
            if method.upper() == 'GET':
                resp = self.session.get(url, params=data, timeout=timeout)
            else:
                resp = self.session.post(url, json=data or {}, timeout=timeout)

            try:
                res_json = resp.json()
            except Exception:
                res_json = {'ok': resp.status_code == 200, 'status_code': resp.status_code, 'text': resp.text}

            if not res_json.get('ok') and resp.status_code != 200:
                logger.warning(f"Bale API Error [{resp.status_code}] on {endpoint}: {resp.text}")

            return res_json

        except requests.exceptions.Timeout:
            logger.error(f"Bale API Timeout on {endpoint}")
            return {'ok': False, 'error': 'timeout', 'description': 'زمان پاسخگویی سرور بله به پایان رسید.'}
        except requests.exceptions.RequestException as e:
            logger.error(f"Bale API Connection Error on {endpoint}: {e}")
            return {'ok': False, 'error': 'network_error', 'description': str(e)}

    # =========================================================================
    # متدهای استاندارد ربات بله
    # =========================================================================

    def get_me(self) -> Dict[str, Any]:
        """استعلام مشخصات بات @Saghf_bot در بله"""
        return self._make_request('GET', 'getMe')

    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        parse_mode: str = 'HTML',
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = True
    ) -> Dict[str, Any]:
        """ارسال پیام متنی به کاربر یا کانال در بله"""
        payload: Dict[str, Any] = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': disable_web_page_preview
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self._make_request('POST', 'sendMessage', payload)

    def send_photo(
        self,
        chat_id: Union[int, str],
        photo: str,
        caption: Optional[str] = None,
        parse_mode: str = 'HTML',
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """ارسال تک عکس با کپشن و دکمه شیشه‌ای"""
        payload: Dict[str, Any] = {
            'chat_id': chat_id,
            'photo': photo,
            'parse_mode': parse_mode
        }
        if caption:
            payload['caption'] = caption
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self._make_request('POST', 'sendPhoto', payload)

    def send_media_group(self, chat_id: Union[int, str], media: List[Dict[str, Any]]) -> Dict[str, Any]:
        """ارسال آلبوم چند عکسی (Media Group) در بله"""
        payload = {
            'chat_id': chat_id,
            'media': media
        }
        return self._make_request('POST', 'sendMediaGroup', payload, timeout=25)

    def edit_message_text(
        self,
        chat_id: Union[int, str],
        message_id: int,
        text: str,
        parse_mode: str = 'HTML',
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """ویرایش متن پیام موجود (جهت نویگیشن در ویزارد ۵ مرحله‌ای)"""
        payload: Dict[str, Any] = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': parse_mode
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        return self._make_request('POST', 'editMessageText', payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Dict[str, Any]:
        """پاسخ به اکشن کلیک روی دکمه‌های شیشه‌ای اینلاین"""
        payload: Dict[str, Any] = {
            'callback_query_id': callback_query_id,
            'show_alert': show_alert
        }
        if text:
            payload['text'] = text
        return self._make_request('POST', 'answerCallbackQuery', payload)

    # =========================================================================
    # مدیریت وبهوک و Polling
    # =========================================================================

    def set_webhook(self, url: str) -> Dict[str, Any]:
        """تنظیم آدرس وبهوک برای دریافت بلادرنگ پیام‌ها"""
        return self._make_request('POST', 'setWebhook', {'url': url})

    def delete_webhook(self) -> Dict[str, Any]:
        """حذف وبهوک فعال جهت سوئیچ به Long Polling"""
        return self._make_request('POST', 'deleteWebhook')

    def get_webhook_info(self) -> Dict[str, Any]:
        """دریافت اطلاعات وضعیت وبهوک فعلی"""
        return self._make_request('GET', 'getWebhookInfo')

    def get_updates(self, offset: Optional[int] = None, limit: int = 100, timeout: int = 20) -> Dict[str, Any]:
        """دریافت پیام‌ها به صورت Long Polling برای محیط لوکال"""
        payload: Dict[str, Any] = {'limit': limit, 'timeout': timeout}
        if offset is not None:
            payload['offset'] = offset
        return self._make_request('POST', 'getUpdates', payload, timeout=timeout + 5)


# نمونه سراسری کلاینت بله
bale_client = BaleBotClient()
