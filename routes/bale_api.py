"""
=============================================================================
درگاه وب و اندپوینت‌های رسمی ربات بله (Bale Bot Webhook & API Routes)
مدیریت کامل وب‌هوک، وضعیت اتصال بات @Saghf_bot، ارسال تست و آلبوم تصاویر در بله
=============================================================================
"""

import logging
from flask import Blueprint, request, jsonify
from config import Config
from bale_bot.client import bale_client
from bale_bot.bot import process_bale_update
from database.db import db
from database.models import Property

logger = logging.getLogger(__name__)

bale_bp = Blueprint('bale_api', __name__, url_prefix='/api/bale')


@bale_bp.route('/webhook', methods=['POST'])
def bale_webhook():
    """
    دریافت وب‌هوک رسمی رویدادها از پیام‌رسان بله
    معاف از اعتبارسنجی CSRF
    """
    if not request.is_json:
        return jsonify({'error': 'Invalid content type, expected JSON'}), 400

    update_data = request.get_json(silent=True)
    if not update_data:
        return jsonify({'error': 'Empty JSON payload'}), 400

    try:
        success = process_bale_update(update_data)
        return jsonify({'status': 'ok', 'processed': success}), 200
    except Exception as e:
        logger.error(f"Error handling Bale webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bale_bp.route('/status', methods=['GET'])
def bale_status():
    """
    بررسی وضعیت اتصال بات @Saghf_bot در بله، نام کاربری، وضعیت وبهوک و توکن
    """
    if not Config.BALE_BOT_TOKEN:
        return jsonify({
            'configured': False,
            'message': 'توکن ربات بله (BALE_BOT_TOKEN) در متغیرهای محیطی (.env) تنظیم نشده است.'
        }), 200

    bot_info = bale_client.get_me()
    webhook_info = bale_client.get_webhook_info()

    return jsonify({
        'configured': True,
        'token_masked': f"{Config.BALE_BOT_TOKEN[:8]}...{Config.BALE_BOT_TOKEN[-4:]}" if len(Config.BALE_BOT_TOKEN) > 12 else 'configured',
        'channel_id': Config.BALE_CHANNEL_ID or None,
        'bot_info': bot_info,
        'webhook_info': webhook_info
    })


@bale_bp.route('/setup-webhook', methods=['POST'])
def setup_bale_webhook():
    """
    تنظیم آدرس وبهوک در سرورهای بله
    """
    data = request.get_json(silent=True) or request.form or {}
    url = data.get('webhook_url') or Config.BALE_WEBHOOK_URL

    if not url:
        host_url = request.host_url.rstrip('/')
        url = f"{host_url}/api/bale/webhook"

    if not url.startswith('https://'):
        return jsonify({
            'success': False,
            'message': 'سرور بله برای وب‌هوک نیازمند آدرس با پروتکل امن HTTPS است (برای تست لوکال از Ngrok یا حالت Polling استفاده کنید).'
        }), 400

    res = bale_client.set_webhook(url)
    return jsonify({
        'success': bool(res.get('ok')),
        'webhook_url': url,
        'response': res
    })


@bale_bp.route('/remove-webhook', methods=['POST'])
def remove_bale_webhook():
    """
    حذف وب‌هوک بله جهت فعال‌سازی Long Polling
    """
    res = bale_client.delete_webhook()
    return jsonify({
        'success': bool(res.get('ok')),
        'response': res
    })


@bale_bp.route('/test-alert', methods=['POST'])
def test_bale_alert():
    """
    ارسال کارت تست یک ملک به چت آیدی یا کانال بله
    """
    data = request.get_json(silent=True) or request.form or {}
    chat_id = data.get('chat_id') or Config.BALE_CHANNEL_ID

    if not chat_id:
        return jsonify({
            'success': False,
            'message': 'شناسه چت یا کانال بله (BALE_CHANNEL_ID) مشخص نشده است.'
        }), 400

    latest_prop = Property.query.order_by(Property.created_at.desc()).first()
    if not latest_prop:
        return jsonify({'success': False, 'message': 'هیچ ملکی در دیتابیس یافت نشد.'}), 404

    from services.unified_bot_controller import UnifiedBotController
    card_text = UnifiedBotController.format_client_property_card(latest_prop, score=96)
    markup = UnifiedBotController.build_property_action_markup('bale', latest_prop.id)

    res = bale_client.send_message(chat_id=chat_id, text=card_text, reply_markup=markup)
    return jsonify({
        'success': bool(res.get('ok')),
        'property_id': latest_prop.id,
        'target_chat_id': chat_id,
        'response': res
    })


@bale_bp.route('/send-property-photos', methods=['POST'])
def send_property_photos_bale():
    """
    ارسال آلبوم تصاویر یک ملک به بله
    """
    import json
    data = request.get_json(silent=True) or request.form or {}
    prop_id = data.get('property_id')
    file_code = data.get('file_code')
    chat_id = data.get('chat_id') or Config.BALE_CHANNEL_ID

    if not prop_id and not file_code:
        return jsonify({'success': False, 'message': 'شناسه ملک یا کد فایل الزامی است.'}), 400

    prop = None
    if prop_id:
        prop = db.session.get(Property, prop_id)
    elif file_code:
        prop = Property.get_by_code(file_code)

    if not prop:
        return jsonify({'success': False, 'message': 'ملک مورد نظر یافت نشد.'}), 404

    if not chat_id:
        return jsonify({
            'success': True,
            'channel_configured': False,
            'file_code': prop.file_code,
            'message': f'کانال بله هنوز تنظیم نشده است. کد فایل: {prop.file_code}'
        })

    images = []
    if prop.images:
        try:
            images = json.loads(prop.images) if isinstance(prop.images, str) else prop.images
        except Exception:
            images = []

    if not images:
        from services.unified_bot_controller import UnifiedBotController
        res = bale_client.send_message(
            chat_id=chat_id,
            text=UnifiedBotController.format_client_property_card(prop),
            reply_markup=UnifiedBotController.build_property_action_markup('bale', prop.id)
        )
        return jsonify({'success': bool(res.get('ok')), 'photos_count': 0, 'response': res})

    # ارسال عکس‌ها
    first_img = images[0]
    from services.unified_bot_controller import UnifiedBotController
    res = bale_client.send_photo(
        chat_id=chat_id,
        photo=first_img,
        caption=UnifiedBotController.format_client_property_card(prop),
        reply_markup=UnifiedBotController.build_property_action_markup('bale', prop.id)
    )

    if len(images) > 1:
        media_group = [{'type': 'photo', 'media': img} for img in images[1:4]]
        bale_client.send_media_group(chat_id=chat_id, media=media_group)

    return jsonify({
        'success': bool(res.get('ok')),
        'photos_count': len(images),
        'file_code': prop.file_code,
        'chat_id': chat_id
    })
