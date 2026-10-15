"""
سیستم مانیتورینگ و آلارم ادمین در پیام‌رسان بله (Bale Admin Alerts)
ارسال لحظه‌ای هشدارهای طلایی (فایل مالک) و سبز (متقاضی جدید) با دکمه‌های شیشه‌ای
"""

import os
import json
import html
import logging
import requests
from typing import Optional

from config import Config
from database.models import Property, Owner, CustomerLead
from services.messenger_service import OmniMessengerService

logger = logging.getLogger(__name__)

BALE_ADMIN_STORAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'bale_admins.json')

def _load_bale_admins() -> set[str]:
    admin_set = set()
    if os.path.exists(BALE_ADMIN_STORAGE_FILE):
        try:
            with open(BALE_ADMIN_STORAGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for a in data.get('admins', []):
                    admin_set.add(str(a).strip())
        except Exception as e:
            logger.error(f"Error loading bale admins: {e}")

    env_admin = str(Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID or "").strip()
    if env_admin:
        admin_set.add(env_admin)
    return admin_set

def send_bale_gold_property_alert(prop: Property, owner: Optional[Owner] = None, target_chat_id: Optional[str] = None) -> bool:
    """
    🟡 ارسال آلارم طلایی برای ثبت ملک جدید توسط مالک مستقیم به بله
    """
    token = Config.BALE_BOT_TOKEN
    if not token:
        logger.warning("Bale bot token not configured; skipping gold alert.")
        return False

    chat_id = target_chat_id or Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID
    if not chat_id:
        # جستجو در ادمین‌های ذخیره شده
        admins = _load_bale_admins()
        if admins:
            chat_id = list(admins)[0]
        else:
            logger.warning("No Bale admin chat ID found.")
            return False

    owner_obj = owner or prop.owner
    owner_name = owner_obj.full_name if owner_obj else "مالک مستقیم"
    owner_phone = owner_obj.phone_number if owner_obj else (prop.owner_type or "ثبت نشده")

    deal_name = "🏷️ فروش" if prop.deal_type == 'sale' else "🔑 رهن و اجاره"

    if prop.deal_type == 'sale':
        if prop.total_price and prop.total_price > 0:
            price_str = f"{prop.total_price / 1_000_000_000:.2f} میلیارد تومان" if prop.total_price >= 1_000_000_000 else f"{prop.total_price / 1_000_000:,.0f} میلیون تومان"
        else:
            price_str = "توافقی"
        finance_info = f"💰 <b>قیمت کل:</b> {price_str}"
    else:
        dep = f"{prop.deposit / 1_000_000:,.0f} میلیون" if prop.deposit else "توافقی"
        rnt = f"{prop.monthly_rent / 1_000_000:,.0f} میلیون" if prop.monthly_rent else "توافقی"
        finance_info = f"💳 <b>ودیعه:</b> {dep} | 💵 <b>اجاره:</b> {rnt}"

    amenities = []
    if prop.has_parking: amenities.append("🚗 پارکینگ")
    if prop.has_elevator: amenities.append("🛗 آسانسور")
    if prop.has_warehouse: amenities.append("📦 انباری")
    if prop.has_balcony: amenities.append("🌿 بالکن")
    amenities_str = " • ".join(amenities) if amenities else "معمولی"

    has_photo = len(prop.images) > 0
    photo_icon = f"✅ دارد ({len(prop.images)} عکس)" if has_photo else "❌ بدون تصویر"

    lines = [
        "🟡⚜️ <b>آلارم طلایی بله: فایل شخصی جدید (مالک مستقیم)</b> ⚜️🟡",
        "───────────────────────",
        f"📋 <b>کد فایل:</b> <code>{prop.file_code}</code> | {deal_name}",
        f"📌 <b>عنوان:</b> {html.escape(prop.title or 'بدون عنوان')}",
        f"📍 <b>منطقه/محله:</b> {html.escape(prop.district or 'نامشخص')} | 📐 {prop.area} متر | {prop.rooms} خواب",
        f"🏢 <b>طبقه:</b> {prop.floor or 1} | ✨ <b>امکانات:</b> {amenities_str}",
        f"{finance_info}",
        "───────────────────────",
        f"👤 <b>مالک:</b> {html.escape(owner_name)}",
        f"📞 <b>تماس مالک:</b> <code>{owner_phone}</code>",
        f"📸 <b>وضعیت تصویر:</b> {photo_icon}",
        "───────────────────────",
        "⚖️ <i>وضعیت: نیازمند اقدام و بررسی مشاور</i>"
    ]
    message_text = "\n".join(lines)

    web_prop_url = f"http://127.0.0.1:5000/properties/{prop.id}"

    # دکمه‌های پیام‌رسان‌ها
    chat_links = OmniMessengerService.get_platform_links(
        phone=owner_phone,
        message=f"سلام {owner_name} گرامی، از دپارتمان سقف در خصوص فایل کد {prop.file_code} مزاحم می‌شم.",
        source_url=web_prop_url
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ تایید و انتشار فوری", "callback_data": f"bale_adm_pub_{prop.id}"},
                {"text": "✏️ ویرایش در CRM", "url": web_prop_url}
            ],
            [
                {"text": "💬 واتس‌اپ", "url": chat_links['whatsapp']['url']},
                {"text": "✈️ تلگرام", "url": chat_links['telegram']['url']}
            ],
            [
                {"text": "🌿 بله", "url": chat_links['bale']['url']},
                {"text": "🟠 ایتا", "url": chat_links['eitaa']['url']}
            ]
        ]
    }

    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        logger.info(f"Bale gold alert sent: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Error sending Bale gold alert: {e}")
        return False

def send_bale_green_lead_alert(lead: CustomerLead, target_chat_id: Optional[str] = None) -> bool:
    """
    🟢 ارسال آلارم سبز برای ثبت متقاضی جدید به بله
    """
    token = Config.BALE_BOT_TOKEN
    if not token:
        return False

    chat_id = target_chat_id or Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID
    if not chat_id:
        admins = _load_bale_admins()
        if admins:
            chat_id = list(admins)[0]
        else:
            return False

    deal_txt = "خرید ملک" if lead.deal_type == 'sale' else "رهن و اجاره"
    districts_str = "، ".join(lead.preferred_districts) if lead.preferred_districts else "منطقه ۵"

    if lead.deal_type == 'sale':
        budget_str = f"تا {lead.max_budget / 1_000_000_000:.2f} میلیارد تومان" if lead.max_budget >= 1_000_000_000 else (f"تا {lead.max_budget / 1_000_000:,.0f} میلیون" if lead.max_budget else "مشخص نشده")
        budget_info = f"💰 <b>بودجه خرید:</b> {budget_str}"
    else:
        dep = f"{lead.max_deposit / 1_000_000:,.0f} میلیون" if lead.max_deposit else "منعطف"
        rnt = f"{lead.max_rent / 1_000_000:,.0f} میلیون" if lead.max_rent else "منعطف"
        budget_info = f"💳 <b>حداکثر ودیعه:</b> {dep} | 💵 <b>حداکثر اجاره:</b> {rnt}"

    features_str = " • ".join(lead.preferred_features) if lead.preferred_features else "استاندارد"

    lines = [
        "🟢🌿 <b>آلارم سبز بله: متقاضی جدید در سامانه (Lead)</b> 🌿🟢",
        "───────────────────────",
        f"👤 <b>نام متقاضی:</b> {html.escape(lead.full_name or 'مشتری جدید')}",
        f"📞 <b>شماره تماس:</b> <code>{lead.phone_number}</code>",
        f"🎯 <b>نوع تقاضا:</b> <b>{deal_txt}</b>",
        f"📍 <b>مناطق هدف:</b> {html.escape(districts_str)}",
        f"📐 <b>حداقل متراژ:</b> {lead.min_area or 60} متر",
        f"{budget_info}",
        f"✨ <b>اولویت‌های ضروری:</b> {features_str}",
        f"📱 <b>پیام‌رسان فعال:</b> {lead.active_messenger}",
        "───────────────────────",
        "⚡ <i>آماده معرفی سریع فایل‌های منطبق</i>"
    ]
    message_text = "\n".join(lines)

    chat_links = OmniMessengerService.get_platform_links(
        phone=lead.phone_number,
        message=f"سلام {lead.full_name} گرامی، از دپارتمان سقف در خدمت شما هستیم. فایل‌های متناسب با بودجه شما آماده است.",
        source_url="http://127.0.0.1:5000/crm/pipeline"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🎯 ارسال ۳ فایل پیشنهادی", "callback_data": f"bale_adm_sendmatch_{lead.id}"},
                {"text": "📋 مشاهده در CRM", "url": "http://127.0.0.1:5000/crm/pipeline"}
            ],
            [
                {"text": "💬 واتس‌اپ", "url": chat_links['whatsapp']['url']},
                {"text": "✈️ تلگرام", "url": chat_links['telegram']['url']}
            ],
            [
                {"text": "🌿 بله", "url": chat_links['bale']['url']},
                {"text": "🟠 ایتا", "url": chat_links['eitaa']['url']}
            ]
        ]
    }

    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "reply_markup": reply_markup
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        logger.info(f"Bale green alert sent: {resp.status_code}")
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Error sending Bale green alert: {e}")
        return False

def send_bale_admin_system_alert(text: str) -> bool:
    """
    ارسال پیام سیستمی به تمام مدیران بله
    """
    token = Config.BALE_BOT_TOKEN
    if not token:
        return False
    admins = _load_bale_admins()
    if not admins:
        return False

    success = False
    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    for aid in admins:
        try:
            requests.post(url, json={
                "chat_id": aid,
                "text": f"🔔 <b>هشدار سیستمی بله (Saghf Alert):</b>\n\n{text}",
                "parse_mode": "HTML"
            }, timeout=8)
            success = True
        except Exception:
            pass
    return success
