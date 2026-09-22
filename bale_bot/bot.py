"""
=============================================================================
گرداننده و پردازشگر رویدادهای ربات بله (Bale Bot Runner & Update Processor)
اتصال مستقیم به مغز مرکزی UnifiedBotController جهت تطابق ۱۰۰٪ با تلگرام
پشتیبانی از هر دو حالت Webhook و Long Polling
=============================================================================
"""

import json
import logging
import threading
import time
from typing import Dict, Any, Optional

from config import Config
from bale_bot.client import bale_client, BaleBotClient
from services.unified_bot_controller import UnifiedBotController

logger = logging.getLogger(__name__)

_polling_active = False
_polling_thread: Optional[threading.Thread] = None
_flask_app_instance = None


def set_flask_app(app):
    global _flask_app_instance
    _flask_app_instance = app


def get_flask_app():
    global _flask_app_instance
    if _flask_app_instance is None:
        try:
            from flask import current_app
            if current_app:
                return current_app._get_current_object()
        except Exception:
            pass
        from app import create_app
        _flask_app_instance = create_app()
    return _flask_app_instance


def _send_controller_response(chat_id: Any, response: Dict[str, Any], client: BaleBotClient, message_id: Optional[int] = None):
    """
    مبدل و فرستنده ساختارهای پاسخ UnifiedBotController به سرورهای بله
    """
    rtype = response.get('type')

    if rtype == 'text':
        client.send_message(
            chat_id=chat_id,
            text=response['message'],
            reply_markup=response.get('reply_markup')
        )

    elif rtype == 'edit_or_send':
        if message_id:
            res = client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=response['message'],
                reply_markup=response.get('reply_markup')
            )
            if not res.get('ok'):
                client.send_message(chat_id, response['message'], reply_markup=response.get('reply_markup'))
        else:
            client.send_message(chat_id, response['message'], reply_markup=response.get('reply_markup'))

    elif rtype == 'property_package':
        prop = response.get('property')
        markup = response.get('reply_markup')
        card_text = response.get('card_text') or response.get('message')

        # بررسی وجود تصاویر ملک
        images = []
        if prop and prop.images:
            try:
                images = json.loads(prop.images) if isinstance(prop.images, str) else prop.images
            except Exception:
                images = []

        if images and isinstance(images, list) and len(images) > 0:
            first_img = images[0]
            # ارسال عکس اول همراه با کپشن مشخصات فنی و دکمه‌های اقدام
            client.send_photo(
                chat_id=chat_id,
                photo=first_img,
                caption=card_text,
                reply_markup=markup
            )
            # اگر آلبوم چند عکسی بود، ۲ تصویر دیگر نیز به عنوان پیش‌نمایش ارسال شود
            if len(images) > 1:
                media_items = [{'type': 'photo', 'media': img} for img in images[1:4]]
                client.send_media_group(chat_id=chat_id, media=media_items)
        else:
            client.send_message(chat_id=chat_id, text=card_text, reply_markup=markup)

    elif rtype == 'crm_matches':
        intro = response.get('intro_message')
        if intro:
            client.send_message(chat_id=chat_id, text=intro)

        cards = response.get('cards', [])
        for item in cards:
            prop = item.get('property')
            card_text = item.get('card_text')
            markup = item.get('reply_markup')

            images = []
            if prop and prop.images:
                try:
                    images = json.loads(prop.images) if isinstance(prop.images, str) else prop.images
                except Exception:
                    images = []

            if images and isinstance(images, list) and len(images) > 0:
                client.send_photo(
                    chat_id=chat_id,
                    photo=images[0],
                    caption=card_text,
                    reply_markup=markup
                )
            else:
                client.send_message(chat_id=chat_id, text=card_text, reply_markup=markup)


def process_bale_update(update: Dict[str, Any], client: Optional[BaleBotClient] = None) -> bool:
    """
    پردازش یک رویداد دریافتی از سرور بله (از طریق Webhook یا Polling)
    """
    client = client or bale_client
    app = get_flask_app()

    with app.app_context():
        # الف) رویداد کلیک روی دکمه شیشه‌ای (Callback Query)
        if 'callback_query' in update:
            cb = update['callback_query']
            cb_id = str(cb.get('id', ''))
            cb_data = cb.get('data', '')
            sender = cb.get('from', {})
            user_name = sender.get('first_name', 'همراه گرامی')
            
            message_obj = cb.get('message', {})
            chat_id = message_obj.get('chat', {}).get('id') or sender.get('id')
            message_id = message_obj.get('message_id')

            # پاسخ سریع به کلیک جهت جلوگیری از لودینگ دکمه
            client.answer_callback_query(cb_id)

            res = UnifiedBotController.handle_callback_query('bale', chat_id, cb_data, user_name)
            _send_controller_response(chat_id, res, client, message_id=message_id)
            return True

        # ب) پیام عادی ورودی (Message)
        if 'message' in update:
            msg = update['message']
            chat = msg.get('chat', {})
            chat_id = chat.get('id')
            sender = msg.get('from', {})
            user_name = sender.get('first_name', 'همراه گرامی')
            user_phone = msg.get('contact', {}).get('phone_number')

            text = (msg.get('text') or '').strip()
            if not text:
                return True

            # ۱. فرمان /start
            if text.startswith('/start'):
                parts = text.split()
                deep_param = parts[1] if len(parts) > 1 else None
                res = UnifiedBotController.handle_start('bale', chat_id, user_name, deep_param)
                _send_controller_response(chat_id, res, client)
                return True

            # ۲. فرامین سوپرادمین (/admin, /stats, /crawl)
            if text in ['/admin', '/stats', '/crawl']:
                res = UnifiedBotController.handle_admin_commands('bale', chat_id, text)
                if res:
                    _send_controller_response(chat_id, res, client)
                    return True

            # ۳. استعلام کد فایل با کامند (/code 10001)
            if text.startswith('/code'):
                parts = text.split()
                if len(parts) > 1:
                    code_val = UnifiedBotController.extract_property_code(parts[1])
                    if code_val:
                        res = UnifiedBotController.handle_code_search('bale', chat_id, code_val)
                        _send_controller_response(chat_id, res, client)
                        return True
                client.send_message(chat_id, "⚠️ لطفاً کد ملک را به صورت <code>/code 10001</code> وارد فرمایید.")
                return True

            # ۴. ورود دستور ویزارد (/filter یا /wizard)
            if text in ['/filter', '/wizard']:
                res = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_start', user_name)
                _send_controller_response(chat_id, res, client)
                return True

            # ۵. استعلام عددی مستقیم کد ملک (مانند "10001" یا "کد 10001")
            code_candidate = UnifiedBotController.extract_property_code(text)
            if code_candidate:
                res = UnifiedBotController.handle_code_search('bale', chat_id, code_candidate)
                _send_controller_response(chat_id, res, client)
                return True

            # ۶. متن محاوره‌ای آزاد -> ارسال به مشاور ارشد CRM
            res = UnifiedBotController.handle_natural_text('bale', chat_id, text, user_phone, user_name)
            _send_controller_response(chat_id, res, client)
            return True

    return False


def _bale_polling_worker(flask_app):
    """
    حلقه دریافت پیوسته پیام‌های بله در ترد پس‌زمینه
    """
    global _polling_active
    logger.info("Bale Bot polling worker started.")
    print("🚀 اتصال ربات بله سقف (@Saghf_bot) به سرورهای بله آغاز شد...", flush=True)

    # حذف هرگونه وبهوک پیشین جهت جلوگیری از تداخل
    try:
        bale_client.delete_webhook()
    except Exception:
        pass

    last_update_id = 0
    while _polling_active:
        try:
            updates_res = bale_client.get_updates(offset=last_update_id + 1, timeout=12)
            if updates_res.get('ok') and not updates_res.get('simulated'):
                result = updates_res.get('result', [])
                if isinstance(result, list):
                    for upd in result:
                        upd_id = upd.get('update_id')
                        if upd_id:
                            last_update_id = max(last_update_id, upd_id)
                        process_bale_update(upd)
            elif updates_res.get('error_code') == 401:
                logger.warning("BALE_BOT_TOKEN is rejected by Bale API (401 Unauthorized).")
                print("⚠️ خطای احراز هویت بله: توکن فعلی مورد تأیید سرور بله نیست (401 Unauthorized). در انتظار توکن صحیح...", flush=True)
                time.sleep(20)
            elif updates_res.get('simulated'):
                # بدون توکن، با فواصل استراحت بررسی می‌شود
                time.sleep(10)
            else:
                time.sleep(2)
        except Exception as e:
            logger.warning(f"Bale polling loop exception: {e}")
            time.sleep(3)


def start_bale_polling(flask_app=None):
    """
    راه‌اندازی Long Polling بله در ترد اختصاصی
    """
    global _polling_active, _polling_thread
    if _polling_active:
        logger.info("Bale polling is already running.")
        return

    if flask_app:
        set_flask_app(flask_app)

    _polling_active = True
    _polling_thread = threading.Thread(target=_bale_polling_worker, args=(flask_app,), daemon=True)
    _polling_thread.start()


def stop_bale_polling():
    """
    توقف ایمن حلقه Polling بله
    """
    global _polling_active
    _polling_active = False
    logger.info("Bale polling stop requested.")
