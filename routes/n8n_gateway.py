"""
=============================================================================
درگاه وب‌هوک‌ها و API اتصال اتوماسیون n8n به سامانه‌های CRM سقف
مسیر پیش‌فرض: /api/n8n
پشتیبانی از هر ۸ درگاه ورودی + وب‌اپ تلگرام
=============================================================================
"""

import logging
import uuid
from flask import Blueprint, request, jsonify, render_template
from services.stt_service import stt_processor
from services.nlp_extractor import PropertyLeadNLPExtractor
from services.voice_ai_engine import VoiceAiPipeline
from services.n8n_crm_service import (
    PropertiesOwnersCRM, BuyersTenantsCRM, 
    SmartFollowupEngine, TelegramAdminNotifier, CHANNEL_NAMES_FA
)
from database.models import Property, Owner, CustomerLead, OutreachLog

logger = logging.getLogger(__name__)

n8n_bp = Blueprint('n8n_gateway', __name__)

# =====================================================================
# ۱. درگاه‌های ورودی چندکاناله و وب‌هوک‌ها (Omni-Channel Ingestion)
# =====================================================================

@n8n_bp.route('/api/n8n/ingest/<channel>', methods=['POST'])
def ingest_channel(channel):
    """
    دریافت پیام‌ها و رویدادهای ورودی از هریک از ۸ کانال:
    voip, sms, instagram, whatsapp, telegram, bale, eitaa, rubika
    """
    channel = channel.lower()
    if channel not in CHANNEL_NAMES_FA:
        return jsonify({'success': False, 'error': f'درگاه ارتباطی {channel} نامعتبر است.'}), 400

    data = request.get_json(silent=True) or request.form.to_dict() or {}
    
    # استخراج پارامترهای پایه‌ای
    caller_phone = data.get('caller_phone') or data.get('phone_number') or data.get('from') or data.get('sender')
    audio_url = data.get('audio_url') or data.get('recording_url') or data.get('voice_url')
    raw_text = data.get('text') or data.get('message') or data.get('caption') or ''
    sender_id = data.get('sender_id') or data.get('user_id') or caller_phone
    media_urls = data.get('media_urls') or data.get('photos') or []

    # رونویسی صوت در صورت وجود فایل صوتی (VoIP یا Voice پیام‌رسان)
    transcribed_text = raw_text
    if audio_url and not raw_text:
        stt_res = stt_processor.transcribe(audio_url_or_path=audio_url, fallback_text=raw_text)
        transcribed_text = stt_res.get('text', '')

    # پردازش زبانی و تفکیک نقش با LLM / NLP Router
    intent = VoiceAiPipeline.detect_intent(transcribed_text)
    extracted_criteria = PropertyLeadNLPExtractor.extract_criteria(transcribed_text)
    
    # شماره تلفن استخراج شده از متن (اگر در متادیتا نبود)
    if not caller_phone:
        caller_phone = VoiceAiPipeline.extract_phone_number(transcribed_text)

    # بسته آماده برای تفکیک CRM
    payload = {
        'channel': channel,
        'sender_id': sender_id,
        'phone_number': caller_phone,
        'transcribed_text': transcribed_text,
        'audio_url': audio_url,
        'media_urls': media_urls,
        'intent': intent,
        'deal_type': extracted_criteria.get('deal_type', 'sale'),
        'district': extracted_criteria.get('districts', ['تهران'])[0] if extracted_criteria.get('districts') else 'تهران',
        'districts': extracted_criteria.get('districts', []),
        'min_area': extracted_criteria.get('min_area', 0),
        'max_area': extracted_criteria.get('max_area', 0),
        'total_price': extracted_criteria.get('max_budget', 0),
        'max_budget': extracted_criteria.get('max_budget', 0),
        'deposit': extracted_criteria.get('max_deposit', 0),
        'max_deposit': extracted_criteria.get('max_deposit', 0),
        'monthly_rent': extracted_criteria.get('max_rent', 0),
        'max_rent': extracted_criteria.get('max_rent', 0),
        'features': extracted_criteria.get('features', []),
        'deed_type': data.get('deed_type') or 'سند تک‌برگ شخصی'
    }

    # تفکیک و ثبت در پایگاه داده CRM مربوطه
    if intent == 'listing_intake':
        # مسیر شاخه اول: CRM مالکین و املاک
        if not caller_phone:
            caller_phone = '09120000000' # شماره موقت در انتظار تکمیل
            payload['phone_number'] = caller_phone
        result = PropertiesOwnersCRM.register_owner_property(payload)
    else:
        # مسیر شاخه دوم: CRM مشتریان و متقاضیان
        if not caller_phone:
            caller_phone = f"lead_{uuid.uuid4().hex[:6]}"
            payload['phone_number'] = caller_phone
        result = BuyersTenantsCRM.register_or_update_lead(payload)

    result['ingest_channel'] = channel
    result['channel_title'] = CHANNEL_NAMES_FA[channel]
    result['transcription'] = transcribed_text
    return jsonify(result)


# =====================================================================
# ۲. اندپوینت‌های روتر LLM و تفکیک موجودیت (LLM Router)
# =====================================================================

@n8n_bp.route('/api/n8n/router/classify-and-extract', methods=['POST'])
def router_classify_and_extract():
    """
    گره تحلیل معنایی و تفکیک ساختاریافته JSON برای موتور n8n
    """
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    text = data.get('text', '').strip()

    if not text and data.get('audio_url'):
        stt_res = stt_processor.transcribe(audio_url_or_path=data['audio_url'])
        text = stt_res.get('text', '')

    intent = VoiceAiPipeline.detect_intent(text)
    criteria = PropertyLeadNLPExtractor.extract_criteria(text)
    phone = VoiceAiPipeline.extract_phone_number(text)

    return jsonify({
        'success': True,
        'role': 'property_owner' if intent == 'listing_intake' else 'lead_buyer_tenant',
        'intent': intent,
        'detected_phone': phone,
        'criteria': criteria,
        'clean_text': text
    })


# =====================================================================
# ۳. ثبت مستقیم در دو پایگاه داده CRM مجزا
# =====================================================================

@n8n_bp.route('/api/n8n/crm/owner-property', methods=['POST'])
def crm_owner_property():
    """ثبت مستقیم در پایگاه داده CRM مالکین و املاک"""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    try:
        res = PropertiesOwnersCRM.register_owner_property(data)
        return jsonify(res)
    except Exception as e:
        logger.error(f"Error in crm_owner_property: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@n8n_bp.route('/api/n8n/crm/buyer-tenant', methods=['POST'])
def crm_buyer_tenant():
    """ثبت مستقیم در پایگاه داده CRM مشتریان و متقاضیان"""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    try:
        res = BuyersTenantsCRM.register_or_update_lead(data)
        return jsonify(res)
    except Exception as e:
        logger.error(f"Error in crm_buyer_tenant: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


# =====================================================================
# ۴. پایپلاین فالوآپ ۲۴ ساعته و دریافت فیدبک (Follow-up Cron Job)
# =====================================================================

@n8n_bp.route('/api/n8n/cron/follow-up-24h', methods=['POST', 'GET'])
def cron_followup_24h():
    """اجرای کران‌جاب پیگیری هوشمند ۲۴ ساعته لیدها"""
    res = SmartFollowupEngine.run_daily_followup()
    return jsonify(res)

@n8n_bp.route('/api/n8n/feedback/process', methods=['POST'])
def feedback_process():
    """پردازش فیدبک دریافتی از مشتری در پیام‌رسان و اعمال در CRM"""
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    phone = data.get('phone_number') or data.get('phone') or data.get('from')
    text = data.get('feedback_text') or data.get('text') or data.get('message') or ''
    lead_id = data.get('lead_id')

    if not phone and lead_id:
        lead = CustomerLead.query.get(lead_id)
        if lead:
            phone = lead.phone_number

    if not phone:
        # Fallback to last lead if exists
        last_lead = CustomerLead.query.order_by(CustomerLead.id.desc()).first()
        if last_lead:
            phone = last_lead.phone_number
        else:
            return jsonify({'success': False, 'error': 'شماره تلفن یا شناسه لید الزامی است.'}), 400

    res = SmartFollowupEngine.process_lead_feedback(phone, text)
    return jsonify(res)


# =====================================================================
# ۵. لایه کنترل و مانیتورینگ ادمین در پوسته تلگرام (Telegram Mini App)
# =====================================================================

@n8n_bp.route('/admin/telegram-mini-app')
def telegram_mini_app():
    """
    رابط کاربری ادمین مبتنی بر پوسته تلگرام (Telegram Mini App)
    مدیریت دوگانه CRM، آلارم‌های بلادرنگ و پرش به چت‌ها
    """
    recent_properties = Property.query.filter_by(source='direct_owner').order_by(Property.created_at.desc()).limit(10).all()
    recent_leads = CustomerLead.query.order_by(CustomerLead.created_at.desc()).limit(10).all()
    outreach_logs = OutreachLog.query.order_by(OutreachLog.sent_at.desc()).limit(15).all()

    return render_template(
        'admin/telegram_mini_app.html',
        properties=recent_properties,
        leads=recent_leads,
        logs=outreach_logs,
        channel_names=CHANNEL_NAMES_FA
    )

@n8n_bp.route('/api/n8n/admin/stats')
def admin_stats():
    """آمار زنده برای مینی‌اپ و مانیتورینگ n8n"""
    return jsonify({
        'total_direct_properties': Property.query.filter_by(source='direct_owner').count(),
        'total_leads': CustomerLead.query.count(),
        'total_outreach_dispatched': OutreachLog.query.filter_by(status='sent').count(),
        'active_channels': list(CHANNEL_NAMES_FA.keys())
    })
