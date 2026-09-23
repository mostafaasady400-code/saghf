import logging
import json
import html
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import Config
from .bot import get_bot

logger = logging.getLogger(__name__)

def format_property_telegram_message(prop) -> str:
    """
    Builds an authentic, rich HTML message for Telegram broadcasting.
    Adheres strictly to AGENTS.md:
    - No mock data
    - Direct link with anchor tag <a>لینک آگهی</a>
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

    # Pricing representation
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
            lines.append(f"💡 <i>{ ' • '.join(m_reasons[:2]) }</i>")

    # Amenities
    amenities = []
    if prop.has_parking: amenities.append("🚗 پارکینگ")
    if prop.has_elevator: amenities.append("🛗 آسانسور")
    if prop.has_warehouse: amenities.append("📦 انباری")
    if prop.has_balcony: amenities.append("🌿 بالکن")
    if amenities:
        lines.append(f"✨ امکانات: {' • '.join(amenities)}")

    # Source & authentic direct link
    # AGENTS.md Rule 2: Every crawled/registered ad must include <a href="...">لینک آگهی</a>
    source_name = "دیوار" if prop.source == 'divar' else ("شیپور" if prop.source == 'sheypoor' else "فایل شخصی مشاور")
    lines.append(f"📡 منبع استخراج: <b>{source_name}</b>")

    target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
    safe_url = html.escape(target_url)
    lines.append(f'\n🌐 <a href="{safe_url}">لینک آگهی</a>')

    return "\n".join(lines)

def send_property_alert(prop, target_chat_id=None) -> bool:
    """
    Sends/forwards property details to configured Telegram Channel or Chat ID.
    Guarantees non-blocking, exception-safe behavior.
    """
    chat_id = target_chat_id or Config.TELEGRAM_CHANNEL_ID
    if not chat_id:
        logger.debug("No TELEGRAM_CHANNEL_ID configured; skipping Telegram broadcast.")
        return False

    if not Config.TELEGRAM_BOT_TOKEN:
        logger.warning("No TELEGRAM_BOT_TOKEN configured; cannot broadcast property.")
        return False

    bot = get_bot()
    if not bot:
        return False

    message_text = format_property_telegram_message(prop)
    
    # Inline markup with direct ad link
    target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔗 مشاهده مستقیم (لینک آگهی)", url=target_url))

    # Check for image
    first_image = None
    if prop.images_json:
        try:
            imgs = json.loads(prop.images_json)
            if isinstance(imgs, list) and len(imgs) > 0 and imgs[0]:
                first_image = imgs[0]
        except Exception:
            pass

    try:
        if first_image and str(first_image).startswith(('http://', 'https://')):
            # Send photo with caption
            bot.send_photo(
                chat_id=chat_id,
                photo=first_image,
                caption=message_text[:1024], # Telegram photo caption limit is 1024 chars
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
        logger.info(f"✅ Successfully sent property alert {prop.id} to Telegram ({chat_id})")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send Telegram alert for property {prop.id}: {e}")
        return False

def send_property_media_group(prop, target_chat_id=None) -> dict:
    """
    Sends all images of the property as a Telegram MediaGroup (album).
    If multiple photos exist, sends an InputMediaPhoto album.
    Caption is attached to the first photo and includes property code and authentic <a href="...">لینک آگهی</a>.
    """
    from telebot.types import InputMediaPhoto
    chat_id = target_chat_id or Config.TELEGRAM_CHANNEL_ID
    if not chat_id:
        return {'success': False, 'message': 'شناسه چت یا کانال تلگرام مشخص نشده است.'}
    if not Config.TELEGRAM_BOT_TOKEN:
        return {'success': False, 'message': 'توکن ربات تلگرام تنظیم نشده است.'}

    bot = get_bot()
    if not bot:
        return {'success': False, 'message': 'ربات تلگرام در دسترس نیست.'}

    images = prop.images or []
    # Build caption
    caption_text = format_property_telegram_message(prop)
    if len(caption_text) > 1000:
        caption_text = caption_text[:990] + '...\n' + f'🌐 <a href="{html.escape(prop.source_url or "")}">لینک آگهی</a>'

    try:
        if len(images) > 1:
            media_list = []
            for i, img_url in enumerate(images[:10]):  # Telegram allows max 10 photos in media group
                if i == 0:
                    media_list.append(InputMediaPhoto(media=img_url, caption=caption_text, parse_mode='HTML'))
                else:
                    media_list.append(InputMediaPhoto(media=img_url))
            bot.send_media_group(chat_id=chat_id, media=media_list)
            logger.info(f"✅ Successfully sent media group of {len(media_list)} photos for property {prop.id} ({prop.file_code}) to Telegram ({chat_id})")
            return {'success': True, 'photos_count': len(media_list), 'chat_id': chat_id, 'file_code': prop.file_code}
        elif len(images) == 1:
            target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔗 لینک آگهی", url=target_url))
            bot.send_photo(chat_id=chat_id, photo=images[0], caption=caption_text, parse_mode='HTML', reply_markup=markup)
            return {'success': True, 'photos_count': 1, 'chat_id': chat_id, 'file_code': prop.file_code}
        else:
            target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔗 لینک آگهی", url=target_url))
            bot.send_message(chat_id=chat_id, text=caption_text + "\n\n<i>⚠️ هیچ تصویری برای این آگهی در منبع موجود نبود.</i>", parse_mode='HTML', reply_markup=markup)
            return {'success': True, 'photos_count': 0, 'chat_id': chat_id, 'file_code': prop.file_code}
    except Exception as e:
        logger.warning(f"❌ Failed to send Telegram media group for property {prop.id}: {e}. Retrying with rich text fallback...")
        try:
            target_url = prop.source_url or f"http://127.0.0.1:5000/properties/{prop.id}"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔗 لینک آگهی", url=target_url))
            bot.send_message(
                chat_id=chat_id,
                text=caption_text,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=False
            )
            logger.info(f"✅ Fallback text sent successfully for property {prop.id} ({prop.file_code}) to Telegram ({chat_id})")
            return {'success': True, 'photos_count': 0, 'fallback_text': True, 'chat_id': chat_id, 'file_code': prop.file_code}
        except Exception as e2:
            logger.error(f"❌ Both media group and fallback failed for property {prop.id}: {e2}")
            return {'success': False, 'error': str(e2)}
