"""
لایه کنترل، مانیتورینگ و آلارم ادمین در پوسته تلگرام (Telegram Admin Interface)
ارسال لحظه‌ای نوتیفیکیشن تفکیک‌شده:
🟡 آلارم طلایی (Gold Alert) برای ثبت ملک جدید توسط مالک مستقیم
🟢 آلارم سبز (Green Alert) برای ورود سرنخ و متقاضی جدید ملک
با دکمه‌های شیشه‌ای تایید دستی، ویرایش CRM و ورود مستقیم مشاور به چت در پیام‌رسان‌ها
"""

import html
import logging
from typing import Optional
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import Config
from database.models import Property, Owner, CustomerLead
from services.messenger_service import OmniMessengerService

logger = logging.getLogger(__name__)

def _get_bot():
    from telegram_bot.bot import get_bot
    return get_bot()

def _get_admin_chat_id() -> Optional[str]:
    return Config.TELEGRAM_CHANNEL_ID or Config.ADMIN_TELEGRAM_ID or None

def send_gold_property_alert(prop: Property, owner: Optional[Owner] = None, target_chat_id: Optional[str] = None) -> bool:
    """Disabled: Telegram alerts are shown only in on-demand dashboards."""
    return False

def send_green_lead_alert(lead: CustomerLead, target_chat_id: Optional[str] = None) -> bool:
    """Disabled: Telegram alerts are shown only in on-demand dashboards."""
    return False
