"""
ماژول اختصاصی ربات تلگرام سامانه سقف (Saghf Telegram Bot Module)
شامل:
- پیکربندی و راه‌اندازی بات تلگرام با pyTelegramBotAPI
- هندلرهای فرامین (/start) و دکمه‌های شیشه‌ای
- روت‌ها و توابع تنظیم وبهوک Flask
- سرویس فوروارد و نوتیفیکیشن خودکار فایل‌های جدید به کانال/گروه
"""

from .bot import get_bot, process_update, setup_webhook, remove_webhook, get_webhook_info, start_polling, is_admin_telegram_user, send_admin_system_alert
from .notifier import send_property_alert, send_property_media_group, format_property_telegram_message

__all__ = [
    'get_bot',
    'process_update',
    'setup_webhook',
    'remove_webhook',
    'get_webhook_info',
    'start_polling',
    'is_admin_telegram_user',
    'send_admin_system_alert',
    'send_property_alert',
    'send_property_media_group',
    'format_property_telegram_message'
]
