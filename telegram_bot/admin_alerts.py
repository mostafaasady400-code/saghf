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
    """
    🟡 ارسال آلارم طلایی لوکس برای ملک جدید ثبت‌شده توسط مالک در تلگرام
    """
    chat_id = target_chat_id or _get_admin_chat_id()
    if not chat_id:
        logger.warning("No Telegram admin chat/channel ID configured for gold alert.")
        return False

    bot = _get_bot()
    if not bot:
        return False

    owner_obj = owner or prop.owner
    owner_name = owner_obj.full_name if owner_obj else "مالک مستقیم"
    owner_phone = owner_obj.phone_number if owner_obj else (prop.owner_type or "ثبت نشده")

    deal_name = "🏷️ فروش" if prop.deal_type == 'sale' else "🔑 رهن و اجاره"
    
    # Financial details
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

    # Amenities
    amenities = []
    if prop.has_parking: amenities.append("🚗 پارکینگ")
    if prop.has_elevator: amenities.append("🛗 آسانسور")
    if prop.has_warehouse: amenities.append("📦 انباری")
    if prop.has_balcony: amenities.append("🌿 بالکن")
    amenities_str = " • ".join(amenities) if amenities else "معمولی"

    # Photo & doc status
    has_photo = len(prop.images) > 0
    photo_icon = f"✅ دارد ({len(prop.images)} عکس)" if has_photo else "❌ بدون تصویر"
    
    lines = [
        "🟡⚜️ <b>آلارم طلایی: فایل شخصی جدید (مالک مستقیم)</b> ⚜️🟡",
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
        "⚖️ <i>وضعیت: نیازمند بررسی و اقدام سریع مشاور</i>"
    ]
    message_text = "\n".join(lines)

    # ساخت دکمه‌های اینلاین هوشمند
    markup = InlineKeyboardMarkup(row_width=2)
    
    # دکمه تایید و انتشار سریع
    btn_approve = InlineKeyboardButton("✅ تایید و انتشار فوری", callback_data=f"adm_pub_{prop.id}")
    
    # لینک مستقیم به پنل وب
    web_prop_url = f"http://127.0.0.1:5000/properties/{prop.id}"
    btn_crm = InlineKeyboardButton("✏️ ویرایش در CRM", url=web_prop_url)

    markup.row(btn_approve, btn_crm)

    # تولید لینک‌های مستقیم ورود مشاور به چت در پیام‌رسان‌ها
    chat_links = OmniMessengerService.get_platform_links(
        phone=owner_phone,
        message=f"سلام {owner_name} گرامی، از دپارتمان سقف در خصوص فایل کد {prop.file_code} مزاحم می‌شم.",
        source_url=web_prop_url
    )

    btn_wa = InlineKeyboardButton("💬 واتس‌اپ", url=chat_links['whatsapp']['url'])
    btn_tg = InlineKeyboardButton("✈️ تلگرام", url=chat_links['telegram']['url'])
    btn_bale = InlineKeyboardButton("🌿 بله", url=chat_links['bale']['url'])
    btn_eitaa = InlineKeyboardButton("🟠 ایتا", url=chat_links['eitaa']['url'])

    markup.row(btn_wa, btn_tg)
    markup.row(btn_bale, btn_eitaa)

    try:
        first_img = prop.images[0] if has_photo else None
        if first_img and str(first_img).startswith(('http://', 'https://')):
            bot.send_photo(
                chat_id=chat_id,
                photo=first_img,
                caption=message_text[:1024],
                parse_mode='HTML',
                reply_markup=markup
            )
        else:
            bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=False
            )
        logger.info(f"✅ Gold property alert for {prop.id} sent successfully to Telegram ({chat_id}).")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send gold property alert: {e}")
        return False

def send_green_lead_alert(lead: CustomerLead, target_chat_id: Optional[str] = None) -> bool:
    """
    🟢 ارسال آلارم سبز برای ورود متقاضی / خریدار جدید به سامانه در تلگرام
    """
    chat_id = target_chat_id or _get_admin_chat_id()
    if not chat_id:
        logger.warning("No Telegram admin chat/channel ID configured for green alert.")
        return False

    bot = _get_bot()
    if not bot:
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
        "🟢🌿 <b>آلارم سبز: متقاضی جدید در سامانه (Buyer/Tenant Lead)</b> 🌿🟢",
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
        "⚡ <i>آماده معرفی سریع فایل‌های منطبق و رزرو بازدید</i>"
    ]
    message_text = "\n".join(lines)

    markup = InlineKeyboardMarkup(row_width=2)
    
    # ارسال سریع فایل‌های پیشنهادی
    btn_dispatch = InlineKeyboardButton("🎯 ارسال ۳ فایل پیشنهادی", callback_data=f"adm_sendmatch_{lead.id}")
    btn_crm_lead = InlineKeyboardButton("📋 مشاهده در CRM", url="http://127.0.0.1:5000/crm/pipeline")

    markup.row(btn_dispatch, btn_crm_lead)

    # دیپ‌لینک‌های ورود به چت با متقاضی
    chat_links = OmniMessengerService.get_platform_links(
        phone=lead.phone_number,
        message=f"سلام {lead.full_name} گرامی، از دپارتمان سقف در خدمت شما هستیم. فایل‌های متناسب با بودجه شما آماده است.",
        source_url="http://127.0.0.1:5000/crm/pipeline"
    )

    btn_wa = InlineKeyboardButton("💬 واتس‌اپ", url=chat_links['whatsapp']['url'])
    btn_tg = InlineKeyboardButton("✈️ تلگرام", url=chat_links['telegram']['url'])
    btn_bale = InlineKeyboardButton("🌿 بله", url=chat_links['bale']['url'])
    btn_eitaa = InlineKeyboardButton("🟠 ایتا", url=chat_links['eitaa']['url'])

    markup.row(btn_wa, btn_tg)
    markup.row(btn_bale, btn_eitaa)

    try:
        bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode='HTML',
            reply_markup=markup,
            disable_web_page_preview=False
        )
        logger.info(f"✅ Green lead alert for {lead.id} sent successfully to Telegram ({chat_id}).")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send green lead alert: {e}")
        return False
