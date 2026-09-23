"""
اندپوینت‌های وب‌هوک و API یکپارچه چندکاناله (Omni-Channel Ingestion & Automation API)
مسیر پایه: /api/omnichannel
پشتیبانی از کلیه درگاه‌های: VoIP, SMS, Telegram, WhatsApp, Bale, Eitaa, Rubika, Instagram
و ارتباط متقابل با ورک‌فلوهای n8n
"""

import os
import logging
from flask import Blueprint, request, jsonify
from services.omnichannel_engine import omnichannel_engine
from services.crm_dual_store import DualCRMStore
from services.nurturing_engine import nurturing_engine
from database.models import Property, CustomerLead

logger = logging.getLogger(__name__)

omnichannel_bp = Blueprint('omnichannel_api', __name__, url_prefix='/api/omnichannel')

@omnichannel_bp.route('/webhook/<channel>', methods=['POST'])
def handle_omnichannel_webhook(channel):
    """
    وب‌هوک سرتاسری دریافت رویداد از کلیه کانال‌های ارتباطی:
    - تماس تلفنی و سانترال/VoIP (صوت و متادیتا)
    - پیامک ورودی
    - واتساپ و تلگرام
    - بله، ایتا و روبیکا
    - دایرکت و کامنت اینستاگرام
    """
    channel = channel.lower().strip()
    valid_channels = ['voip', 'call', 'sms', 'telegram', 'whatsapp', 'bale', 'eitaa', 'rubika', 'instagram']
    if channel not in valid_channels:
        return jsonify({'success': False, 'error': f'کانال «{channel}» پشتیبانی نمی‌شود.'}), 400

    data = request.get_json(silent=True) or request.form.to_dict() or {}

    sender_id = (
        data.get('sender_phone') or
        data.get('phone') or
        data.get('from') or
        data.get('caller_phone') or
        data.get('user_id') or
        data.get('chat_id') or
        data.get('username') or
        '09120000000'
    ).strip()

    content = data.get('text') or data.get('message') or data.get('content') or data.get('caption')
    audio_url = data.get('audio_url') or data.get('recording_url') or data.get('voice_url')

    # اگر فایلی به صورت فرم چندبخشی (Multipart File) ارسال شده باشد
    if 'audio' in request.files:
        audio_file = request.files['audio']
        upload_dir = os.path.join('static', 'uploads', 'audio')
        os.makedirs(upload_dir, exist_ok=True)
        saved_path = os.path.join(upload_dir, audio_file.filename)
        audio_file.save(saved_path)
        audio_url = saved_path

    metadata = {
        'call_id': data.get('call_id'),
        'duration_seconds': data.get('duration_seconds', data.get('call_duration', 0)),
        'sender_name': data.get('sender_name') or data.get('full_name') or data.get('name'),
        'post_id': data.get('post_id'),
        'comment_id': data.get('comment_id'),
        'media_attachments': data.get('media_attachments') or []
    }

    try:
        process_res = omnichannel_engine.process_incoming_interaction(
            channel=channel,
            sender_id=sender_id,
            content=content,
            audio_url=audio_url,
            metadata=metadata
        )
        return jsonify(process_res), 200
    except Exception as e:
        logger.error(f"Error processing webhook for channel {channel}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

@omnichannel_bp.route('/owner/create', methods=['POST'])
def create_owner_from_n8n():
    """
    اندپوینت اختصاصی ثبت ملک و مالک از طریق n8n یا سرویس‌های هوش مصنوعی بیرونی
    """
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'success': False, 'error': 'داده JSON الزامی است'}), 400

    channel = data.get('channel', 'n8n_automation')
    raw_text = data.get('raw_text', '')

    owner, prop = DualCRMStore.store_owner_and_property(data, channel=channel, raw_text=raw_text)
    
    # ارسال پیام خوش‌آمد
    nurturing_res = nurturing_engine.handle_owner_onboarding(prop, owner, channel=channel)

    return jsonify({
        'success': True,
        'property_id': prop.id,
        'file_code': prop.file_code,
        'owner_id': owner.id,
        'onboarding': nurturing_res
    })

@omnichannel_bp.route('/lead/create', methods=['POST'])
def create_lead_from_n8n():
    """
    اندپوینت اختصاصی ثبت متقاضی از طریق n8n یا وب‌هوک‌های جانبی
    """
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'success': False, 'error': 'داده JSON الزامی است'}), 400

    channel = data.get('channel', 'n8n_automation')
    raw_text = data.get('raw_text', '')

    lead, client = DualCRMStore.store_customer_lead(data, channel=channel, raw_text=raw_text)
    
    return jsonify({
        'success': True,
        'lead_id': lead.id,
        'client_id': client.id
    })

@omnichannel_bp.route('/match-and-dispatch', methods=['POST'])
def match_and_dispatch():
    """
    اجرای الگوریتم تطبیق و ارسال کارت‌های ملکی به متقاضی
    """
    data = request.get_json(silent=True) or {}
    lead_id = data.get('lead_id')
    channel = data.get('channel')

    lead = CustomerLead.query.get(lead_id) if lead_id else None
    if not lead:
        return jsonify({'success': False, 'error': 'متقاضی با شناسه ارائه شده یافت نشد.'}), 404

    dispatches = nurturing_engine.handle_lead_matching_and_dispatch(lead, channel=channel)
    return jsonify({
        'success': True,
        'lead_id': lead.id,
        'dispatches_count': len(dispatches),
        'dispatches': dispatches
    })

@omnichannel_bp.route('/followup/check', methods=['POST', 'GET'])
def trigger_followup_job():
    """
    فراخوانی کران جاب پیگیری ۲۴ ساعته (توسط نود Schedule در n8n یا کران لوکال)
    """
    result = nurturing_engine.execute_24h_followup_job()
    return jsonify(result)

@omnichannel_bp.route('/feedback', methods=['POST'])
def record_feedback():
    """
    ثبت بازخورد متقاضی در خصوص گزینه‌های ارسالی
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    phone = data.get('phone') or data.get('sender_id')
    feedback_text = data.get('feedback') or data.get('text') or ''

    if not phone:
        return jsonify({'success': False, 'error': 'شماره تماس متقاضی الزامی است.'}), 400

    res = nurturing_engine.process_lead_feedback(phone, feedback_text)
    return jsonify(res)

@omnichannel_bp.route('/broadcast/<channel>', methods=['POST'])
def broadcast_to_channel(channel):
    """
    ارسال پیام یا اعلان همگام‌سازی به ربات تلگرام یا بله (Tri-Platform Sync)
    """
    channel = channel.lower().strip()
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    prop_id = data.get('property_id')
    event_type = data.get('event', 'property_update')
    title = data.get('title', 'فایل ملکی سقف')
    file_code = data.get('file_code', '')
    url = data.get('url', 'http://127.0.0.1:5000')

    prop = Property.query.get(prop_id) if prop_id else None

    if channel == 'telegram':
        from telegram_bot.admin_alerts import send_gold_property_alert
        from telegram_bot.notifier import send_property_alert
        if prop:
            res = send_gold_property_alert(prop)
        else:
            from telegram_bot.bot import send_admin_system_alert
            res = send_admin_system_alert(f"اعلان همگام‌سازی وب: {title} (کد {file_code})\n{url}")
        return jsonify({'success': True, 'channel': 'telegram', 'sent': res})

    elif channel == 'bale':
        from bale_bot.admin_alerts import send_bale_gold_property_alert
        from bale_bot.notifier import send_property_bale_alert
        if prop:
            res = send_bale_gold_property_alert(prop)
        else:
            from bale_bot.admin_alerts import send_bale_admin_system_alert
            res = send_bale_admin_system_alert(f"اعلان همگام‌سازی وب: {title} (کد {file_code})\n{url}")
        return jsonify({'success': True, 'channel': 'bale', 'sent': res})

    return jsonify({'success': False, 'error': f'کانال {channel} برای برودکست پشتیبانی نمی‌شود.'}), 400
