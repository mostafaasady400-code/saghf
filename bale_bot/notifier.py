"""
سیستم اطلاع‌رسانی و ارسال فایل‌های ملکی در پیام‌رسان بله (Bale Notifier)
منطبق بر استانداردهای AGENTS.md:
- عدم استفاده از دیتای ماک
- درج مستقیم تگ <a href="...">لینک آگهی</a>
- برابری و تقارن ۱۰۰٪ با قابلیت‌های نوتیفایر تلگرام
"""

import os
import json
import logging
import html
import requests
from config import Config

logger = logging.getLogger(__name__)

def format_property_bale_message(prop) -> str:
    """
    تولید متن ساختاریافته و شیک HTML برای پیام‌رسان بله
    شامل تمام اطلاعات قیمت، متراژ، منطقه، امکانات و لینک آگهی مستقیم
    """
    deal_name = "🏷️ #فروش" if prop.deal_type == 'sale' else "🔑 #رهن_و_اجاره"
    prop_type_names = {
        'apartment': 'آپارتمان',
        'villa': 'ویلا / باغ',
        'commercial': 'تجاری / اداری',
        'land': 'زمین / کلنگی'
    }
    prop_type = prop_type_names.get(prop.property_type, 'آپارتمان')

    lines = [
        f"⚜️ <b>فایل کد {prop.file_code} در سامانه سقف</b> ⚜️",
        f"🏷️ دسته‌بندی: <b>{deal_name} | {prop_type}</b>",
        f"📌 <b>{html.escape(prop.title or 'بدون عنوان')}</b>",
        f"🏙️ منطقه: <b>{html.escape(prop.district or 'تهران')}</b> | شهر: {html.escape(prop.city or 'تهران')}",
        f"📐 متراژ: <b>{prop.area} متر</b> | 🛏️ اتاق: <b>{prop.rooms} خواب</b> | طبقه: {prop.floor or 1}"
    ]

    # محاسبه قیمت
    if prop.deal_type == 'sale':
        if prop.total_price and prop.total_price > 0:
            price_b = prop.total_price / 1_000_000_000
            price_m = prop.total_price / 1_000_000
            if price_b >= 1:
                price_str = f"{price_b:.2f} میلیارد تومان"
            else:
                price_str = f"{price_m:,.0f} میلیون تومان"
            lines.append(f"💰 قیمت کل: <b>{price_str}</b>")
            if prop.meter_price and prop.meter_price > 0:
                lines.append(f"📊 قیمت هر متر: {prop.meter_price / 1_000_000:,.1f} میلیون تومان")
        else:
            lines.append("💰 قیمت: <b>توافقی</b>")
    else:
        if prop.deposit:
            if prop.deposit >= 1_000_000_000:
                dep_b = prop.deposit / 1_000_000_000
                dep = f"{dep_b:.2f}".rstrip('0').rstrip('.') + " میلیارد تومان"
            else:
                dep = f"{prop.deposit / 1_000_000:,.0f} میلیون تومان"
        else:
            dep = "توافقی"

        if prop.monthly_rent:
            if prop.monthly_rent >= 1_000_000_000:
                rnt_b = prop.monthly_rent / 1_000_000_000
                rnt = f"{rnt_b:.2f}".rstrip('0').rstrip('.') + " میلیارد تومان"
            else:
                rnt = f"{prop.monthly_rent / 1_000_000:,.0f} میلیون تومان"
        else:
            rnt = "توافقی"

        lines.append(f"💳 ودیعه (رهن): <b>{dep}</b>")
        lines.append(f"💵 اجاره ماهانه: <b>{rnt}</b>")

    # Match score & intelligence if evaluated
    m_score = getattr(prop, 'match_score', None)
    if m_score is not None and m_score > 0:
        lines.append(f"🎯 <b>درصد تطابق با نیاز شما: {m_score}٪</b>")
        m_reasons = getattr(prop, 'match_reasons', [])
        if m_reasons:
            lines.append(f"💡 <i>{' • '.join(m_reasons[:2])}</i>")

    # امکانات
    amenities = []
    if prop.has_parking: amenities.append("🚗 پارکینگ")
    if prop.has_elevator: amenities.append("🛗 آسانسور")
    if prop.has_warehouse: amenities.append("📦 انباری")
    if prop.has_balcony: amenities.append("🌿 بالکن")
    if amenities:
        lines.append(f"✨ امکانات: {' • '.join(amenities)}")

    # منبع و لینک مستقیم معتبر (AGENTS.md Rule 2)
    source_name = "دیوار" if prop.source == 'divar' else ("شیپور" if prop.source == 'sheypoor' else "فایل اختصاصی سقف")
    lines.append(f"📡 منبع: <b>{source_name}</b>")

    target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
    safe_url = html.escape(target_url)
    lines.append(f'\n🌐 <a href="{safe_url}">لینک آگهی</a>')

    return "\n".join(lines)

def send_property_bale_alert(prop, target_chat_id: str = None) -> bool:
    """
    ارسال فایل ملکی به چت یا کانال بله همراه با عکس و دکمه شیشه‌ای لینک آگهی
    """
    token = Config.BALE_BOT_TOKEN
    chat_id = target_chat_id or Config.BALE_ADMIN_ID
    if not token or not chat_id:
        logger.warning("Bale token or chat ID is missing for property alert.")
        return False

    return send_property_bale_media(prop, chat_id)

def send_property_bale_media(prop, chat_id: str or int, bot=None) -> bool:
    """
    ارسال تصاویر و پرونده ملک به کاربر در بله به همراه دکمه اینلاین و لینک مستقیم
    """
    token = Config.BALE_BOT_TOKEN
    if not token or not chat_id:
        return False

    text = format_property_bale_message(prop)
    images = prop.images or []
    target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔗 لینک آگهی (مشاهده مستقیم)", "url": target_url}
            ]
        ]
    }

    # ۱. تلاش برای ارسال عکس اگر موجود باشد
    if images and str(images[0]).startswith(('http://', 'https://')):
        photo_url = f"https://tapi.bale.ai/bot{token}/sendPhoto"
        try:
            resp = requests.post(photo_url, json={
                'chat_id': chat_id,
                'photo': images[0],
                'caption': text[:1024],
                'parse_mode': 'HTML',
                'reply_markup': reply_markup
            }, timeout=10)
            if resp.status_code == 200:
                logger.info(f"✅ Photo sent successfully for property {prop.id} to Bale {chat_id}")
                return True
        except Exception as e:
            logger.warning(f"Error sending photo to Bale, falling back to text: {e}")

    # ۲. در صورت عدم وجود عکس یا بروز خطا، ارسال به عنوان پیام متنی
    msg_url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    try:
        resp = requests.post(msg_url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'reply_markup': reply_markup
        }, timeout=10)
        success = resp.status_code == 200
        if success:
            logger.info(f"✅ Text message sent successfully for property {prop.id} to Bale {chat_id}")
        return success
    except Exception as e:
        logger.error(f"Error sending text to Bale: {e}")
        return False
