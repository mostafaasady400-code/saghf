"""
آداپتور ارسال تلگرام سقف (Telegram Bot Adapter)
"""

import logging
from typing import Dict, Any, Optional
from .base import BaseChannelAdapter
from config import Config

logger = logging.getLogger(__name__)

class TelegramAdapter(BaseChannelAdapter):
    @property
    def platform_name(self) -> str:
        return 'telegram'

    def _get_bot(self):
        from telegram_bot.bot import get_bot
        return get_bot()

    def _resolve_target(self, recipient: str) -> Optional[str]:
        # اگر شناسه عددی تلگرام یا کانال پیکربندی شده باشد اولویت دارد
        if Config.TELEGRAM_CHANNEL_ID:
            return Config.TELEGRAM_CHANNEL_ID
        if Config.ADMIN_TELEGRAM_ID:
            return str(Config.ADMIN_TELEGRAM_ID).strip()
        
        target = str(recipient or "").strip()
        if target.startswith('@') or (target.lstrip('-').isdigit() and not target.startswith('09')):
            return target
        return None

    def send_text(self, recipient: str, text: str) -> Dict[str, Any]:
        """
        ارسال پیام متنی به کاربر یا کانال تلگرام با قالب‌بندی HTML
        """
        target = self._resolve_target(recipient)
        if not target:
            logger.info(f"Recipient {recipient} is not a valid Telegram chat_id and no channel configured. Simulating dispatch.")
            return {
                'success': True,
                'simulated': True,
                'platform': self.platform_name,
                'recipient': recipient,
                'note': 'شناسه تلگرام عددی کاربر تنظیم نشده بود (شبیه‌سازی شد).'
            }
        
        try:
            bot = self._get_bot()
            msg = bot.send_message(chat_id=target, text=text, parse_mode='HTML', disable_web_page_preview=False)
            return {
                'success': True,
                'platform': self.platform_name,
                'message_id': msg.message_id,
                'recipient': target
            }
        except Exception as e:
            logger.error(f"TelegramAdapter error sending text: {e}")
            return {
                'success': False,
                'platform': self.platform_name,
                'error': str(e)
            }

    def send_property_package(self, recipient: str, property_item: Dict[str, Any], text: str) -> Dict[str, Any]:
        """
        ارسال پکیج عکس و متن فایل ملکی با تگ مستقیم لینک آگهی
        """
        target = self._resolve_target(recipient)
        if not target:
            logger.info(f"Recipient {recipient} is not a valid Telegram chat_id and no channel configured. Simulating dispatch.")
            return {
                'success': True,
                'simulated': True,
                'platform': self.platform_name,
                'recipient': recipient,
                'note': 'شناسه تلگرام عددی کاربر تنظیم نشده بود (شبیه‌سازی شد).'
            }

        bot = self._get_bot()
        images = property_item.get('images', [])

        try:
            if images and len(images) > 0:
                from telebot.types import InputMediaPhoto
                # حداکثر ۳ عکس برای پکیج ارسالی
                media = []
                for i, img_url in enumerate(images[:3]):
                    caption = text if i == 0 else ""
                    media.append(InputMediaPhoto(media=img_url, caption=caption, parse_mode='HTML'))
                
                try:
                    msgs = bot.send_media_group(chat_id=target, media=media)
                    return {
                        'success': True,
                        'platform': self.platform_name,
                        'message_ids': [m.message_id for m in msgs],
                        'recipient': target
                    }
                except Exception as me:
                    logger.warning(f"Telegram media group failed, falling back to single text: {me}")

            # در صورت عدم وجود عکس یا خطای ارسال مدیا، ارسال پیام متنی با لینک
            msg = bot.send_message(chat_id=target, text=text, parse_mode='HTML', disable_web_page_preview=False)
            return {
                'success': True,
                'platform': self.platform_name,
                'message_id': msg.message_id,
                'recipient': target
            }
        except Exception as e:
            logger.error(f"TelegramAdapter send_property_package error: {e}")
            return {
                'success': False,
                'platform': self.platform_name,
                'error': str(e)
            }
