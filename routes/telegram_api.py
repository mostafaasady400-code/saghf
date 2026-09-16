import logging
from flask import Blueprint, request, jsonify
from config import Config
from telegram_bot.bot import get_bot, process_update, setup_webhook, remove_webhook, get_webhook_info
from telegram_bot.notifier import send_property_alert
from database.db import db
from database.models import Property

logger = logging.getLogger(__name__)

telegram_bp = Blueprint('telegram_api', __name__, url_prefix='/api/telegram')

@telegram_bp.route('/webhook', methods=['POST'])
def telegram_webhook():
    """
    Main webhook receiver endpoint for Telegram Bot updates.
    Exempt from CSRF validation.
    """
    if not request.is_json:
        return jsonify({'error': 'Invalid content type, expected JSON'}), 400

    update_data = request.get_json(silent=True)
    if not update_data:
        return jsonify({'error': 'Empty JSON payload'}), 400

    try:
        success = process_update(update_data)
        return jsonify({'status': 'ok', 'processed': success}), 200
    except Exception as e:
        logger.error(f"Error handling Telegram webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@telegram_bp.route('/status', methods=['GET'])
def telegram_status():
    """
    Returns bot credentials check, bot username, and current webhook status.
    """
    if not Config.TELEGRAM_BOT_TOKEN:
        return jsonify({
            'configured': False,
            'message': 'توکن ربات تلگرام در متغیرهای محیطی (.env) یافت نشد.'
        }), 200

    bot = get_bot()
    bot_info = None
    try:
        me = bot.get_me()
        bot_info = {
            'id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'can_join_groups': me.can_join_groups,
            'can_read_all_group_messages': me.can_read_all_group_messages
        }
    except Exception as e:
        bot_info = {'error': str(e)}

    webhook_info = get_webhook_info()

    return jsonify({
        'configured': True,
        'token_masked': f"{Config.TELEGRAM_BOT_TOKEN[:10]}...{Config.TELEGRAM_BOT_TOKEN[-5:]}" if Config.TELEGRAM_BOT_TOKEN else None,
        'channel_id': Config.TELEGRAM_CHANNEL_ID or None,
        'bot_info': bot_info,
        'webhook_info': webhook_info
    })

@telegram_bp.route('/setup-webhook', methods=['POST'])
def setup_webhook_endpoint():
    """
    Configures Telegram webhook to point to the server.
    Accepts JSON: {"webhook_url": "https://..."} or falls back to Config.TELEGRAM_WEBHOOK_URL.
    """
    data = request.get_json(silent=True) or request.form or {}
    url = data.get('webhook_url') or Config.TELEGRAM_WEBHOOK_URL
    
    if not url:
        # If no explicit webhook URL provided, infer from current request
        host_url = request.host_url.rstrip('/')
        url = f"{host_url}/api/telegram/webhook"

    if not url.startswith('https://'):
        return jsonify({
            'success': False,
            'message': 'تلگرام صرفاً از آدرس‌های دارای پروتکل امن HTTPS برای وبهوک پشتیبانی می‌کند. (برای تست لوکال از Ngrok یا Cloudflare Tunnel استفاده کنید).'
        }), 400

    result = setup_webhook(url)
    return jsonify(result)

@telegram_bp.route('/remove-webhook', methods=['POST'])
def remove_webhook_endpoint():
    """
    Removes the webhook from Telegram servers.
    """
    res = remove_webhook()
    return jsonify(res)

@telegram_bp.route('/test-alert', methods=['POST'])
def test_alert_endpoint():
    """
    Sends a sample property notification to the configured channel or specified chat_id.
    """
    data = request.get_json(silent=True) or request.form or {}
    chat_id = data.get('chat_id') or Config.TELEGRAM_CHANNEL_ID
    
    if not chat_id:
        return jsonify({
            'success': False,
            'message': 'شناسه چت یا کانال (TELEGRAM_CHANNEL_ID) مشخص نشده است.'
        }), 400

    # Get the latest property
    latest_prop = Property.query.order_by(Property.created_at.desc()).first()
    if not latest_prop:
        return jsonify({
            'success': False,
            'message': 'هیچ ملکی در دیتابیس برای ارسال تست یافت نشد.'
        }), 404

    success = send_property_alert(latest_prop, target_chat_id=chat_id)
    return jsonify({
        'success': success,
        'property_id': latest_prop.id,
        'property_title': latest_prop.title,
        'target_chat_id': chat_id
    })

@telegram_bp.route('/send-property-photos', methods=['POST'])
def send_property_photos_endpoint():
    """
    Sends all images of a specific property as an album (Media Group) to Telegram.
    Accepts JSON: {"property_id": 1} or {"file_code": "10001", "chat_id": "optional"}
    """
    from telegram_bot.notifier import send_property_media_group

    data = request.get_json(silent=True) or request.form or {}
    prop_id = data.get('property_id')
    file_code = data.get('file_code')
    chat_id = data.get('chat_id') or Config.TELEGRAM_CHANNEL_ID

    if not prop_id and not file_code:
        return jsonify({
            'success': False,
            'message': 'شناسه ملک (property_id) یا کد فایل (file_code) الزامی است.'
        }), 400

    prop = None
    if prop_id:
        prop = db.session.get(Property, prop_id)
    elif file_code:
        prop = Property.get_by_code(file_code)

    if not prop:
        return jsonify({
            'success': False,
            'message': 'ملک مورد نظر در سامانه یافت نشد.'
        }), 404

    # If no chat_id is configured yet, inform the user with direct bot deep-link
    if not chat_id:
        deep_link = f"https://t.me/saghf_bot?start=code_{prop.file_code}"
        return jsonify({
            'success': True,
            'channel_configured': False,
            'deep_link': deep_link,
            'file_code': prop.file_code,
            'message': f'کانال تلگرام هنوز تنظیم نشده است. می‌توانید با باز کردن لینک زیر در تلگرام، تصاویر فایل کد {prop.file_code} را مستقیماً دریافت کنید.'
        })

    result = send_property_media_group(prop, target_chat_id=chat_id)
    if result.get('success'):
        return jsonify({
            'success': True,
            'channel_configured': True,
            'file_code': prop.file_code,
            'photos_count': result.get('photos_count', 0),
            'chat_id': chat_id,
            'message': f'آلبوم تصاویر فایل کد {prop.file_code} ({result.get("photos_count", 0)} تصویر) با موفقیت به تلگرام ارسال شد.'
        })
    else:
        return jsonify({
            'success': False,
            'error': result.get('error') or result.get('message'),
            'message': f'خطا در ارسال تصاویر به تلگرام: {result.get("error") or result.get("message")}'
        }), 500
