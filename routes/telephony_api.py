"""
اندپوینت‌های وب‌هوک مرکز تماس VoIP و پردازش هوشمند صوت و مکالمات ورودی
مسیر: /api/v1/telephony/call-recorded
"""

import logging
from flask import Blueprint, request, jsonify
from services.stt_service import stt_processor
from services.nlp_extractor import PropertyLeadNLPExtractor
from services.regional_matching import RegionalPropertyMatcher
from services.omnichannel.dispatcher import omnichannel_dispatcher
from database.models import CallRecord, CustomerLead

logger = logging.getLogger(__name__)

telephony_bp = Blueprint('telephony_api', __name__, url_prefix='/api/v1/telephony')

@telephony_bp.route('/call-recorded', methods=['POST'])
def handle_call_recorded():
    """
    وب‌هوک دریافت فایل صوتی یا گزارش تماس ضبط‌شده از سانترال / VoIP
    """
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({'success': False, 'error': 'داده‌ای دریافت نشد (فرمت JSON الزامی است).'}), 400

    caller_phone = data.get('caller_phone', '').strip()
    if not caller_phone:
        return jsonify({'success': False, 'error': 'شماره تماس‌گیرنده (caller_phone) الزامی است.'}), 400

    call_id = data.get('call_id')
    audio_url = data.get('audio_url')
    duration = int(data.get('call_duration', data.get('duration_seconds', 0)))
    raw_text = data.get('transcribed_text')

    # ۱. تبدیل صوت به نوشتار (STT)
    stt_res = stt_processor.transcribe(audio_url_or_path=audio_url, fallback_text=raw_text)
    transcribed_text = stt_res.get('text', '')

    if not transcribed_text:
        return jsonify({
            'success': False,
            'error': 'امکان پیاده‌سازی متن از صوت وجود نداشت و متنی نیز ارسال نشده است.'
        }), 422

    # ۲. استخراج شروط معامله با NLP و ثبت در پایگاه داده (CallRecord و CustomerLead)
    process_res = PropertyLeadNLPExtractor.process_call_and_save_lead(
        call_id=call_id,
        caller_phone=caller_phone,
        audio_url=audio_url,
        transcribed_text=transcribed_text,
        duration_seconds=duration
    )

    lead_dict = process_res['customer_lead']
    criteria = process_res['criteria']

    # ۳. اجرای موتور تطبیق منطقه‌ای با تلورانس ۱۰٪ جهت استخراج ۳ فایل برتر
    lead_obj = CustomerLead.query.get(lead_dict['id'])
    matched_properties = RegionalPropertyMatcher.match_lead(lead_obj, limit=3)

    # ۴. دیسپچ پکیج پیشنهادات از طریق کانال ارتباطی کاربر و ثبت لاگ در OutreachLog
    dispatches = []
    if matched_properties:
        dispatches = omnichannel_dispatcher.dispatch_to_lead(
            lead=lead_obj,
            property_items=matched_properties,
            platform=criteria.get('active_messenger')
        )

    return jsonify({
        'success': True,
        'message': 'مکالمه با موفقیت دریافت، تحلیل و پردازش شد.',
        'call_id': process_res['call_record']['call_id'],
        'caller_phone': caller_phone,
        'transcription_engine': stt_res.get('engine'),
        'transcribed_text': transcribed_text,
        'criteria': criteria,
        'top_matches': [
            {
                'ad_code': p['ad_code'],
                'title': p['title'],
                'district': p['district'],
                'score': p['match_score'],
                'reasons': p['match_reasons']
            } for p in matched_properties
        ],
        'dispatches': dispatches
    })

@telephony_bp.route('/calls', methods=['GET'])
def list_calls():
    limit = int(request.args.get('limit', 20))
    calls = CallRecord.query.order_by(CallRecord.created_at.desc()).limit(limit).all()
    return jsonify({
        'total': len(calls),
        'calls': [c.to_dict() for c in calls]
    })

@telephony_bp.route('/leads', methods=['GET'])
def list_leads():
    limit = int(request.args.get('limit', 20))
    leads = CustomerLead.query.order_by(CustomerLead.created_at.desc()).limit(limit).all()
    return jsonify({
        'total': len(leads),
        'leads': [l.to_dict() for l in leads]
    })
