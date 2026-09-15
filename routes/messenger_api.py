from flask import Blueprint, request, jsonify
from services.messenger_service import OmniMessengerService

messenger_bp = Blueprint('messenger_api', __name__, url_prefix='/api/messenger')

@messenger_bp.route('/package/<int:property_id>', methods=['GET'])
def get_inquiry_package(property_id):
    """دریافت پکیج کامل استعلام پیام‌رسان‌ها برای یک فایل ملکی خاص"""
    result = OmniMessengerService.generate_inquiry_package(property_id)
    if 'error' in result:
        return jsonify({'success': False, 'message': result['error']}), 404
    return jsonify({'success': True, 'package': result})

@messenger_bp.route('/send/<int:property_id>', methods=['POST'])
def send_inquiry(property_id):
    """
    ثبت ارسال پیام استعلام، تغییر وضعیت به در انتظار پاسخ و دریافت لینک‌های باز کردن ۵ پیام‌رسان
    """
    data = request.get_json(silent=True) or request.form
    platform = data.get('platform', 'all')
    agent_id = data.get('agent_id')

    success = OmniMessengerService.mark_inquiry_sent(property_id, agent_id=agent_id, platform=platform)
    if not success:
        return jsonify({'success': False, 'message': 'ملک یافت نشد'}), 404

    package = OmniMessengerService.generate_inquiry_package(property_id)
    return jsonify({
        'success': True,
        'message': 'استعلام در سامانه ثبت شد و آماده ارسال به مالک است.',
        'package': package
    })

@messenger_bp.route('/respond/<int:property_id>', methods=['POST'])
def record_response(property_id):
    """
    ثبت پاسخ مالک (دستی توسط کارشناس یا اتوماتیک) و به‌روزرسانی چرخه عمر فایل:
    - ۱: تایید موجودی و تمدید ۷ روزه
    - ۲: اعلام واگذاری و بایگانی قطعی
    """
    data = request.get_json(silent=True) or request.form
    response_code = data.get('response_code') or data.get('code') or '1'
    platform = data.get('platform', 'whatsapp')
    notes = data.get('notes')

    result = OmniMessengerService.handle_owner_response(
        property_id=property_id,
        response_code=response_code,
        platform=platform,
        notes=notes
    )

    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)

@messenger_bp.route('/webhook', methods=['POST'])
def messenger_webhook():
    """
    وب‌هوک هوشمند دریافت پاسخ‌های خودکار از ربات‌های متصل به تلگرام، بله، ایتا، روبیکا و واتساپ
    """
    payload = request.get_json(silent=True) or {}
    property_id = payload.get('property_id')
    response_code = payload.get('response_code') or payload.get('text')
    platform = payload.get('platform', 'telegram')
    notes = payload.get('notes')

    if not property_id or not response_code:
        return jsonify({'success': False, 'message': 'شناسه ملک و کد پاسخ الزامی است'}), 400

    result = OmniMessengerService.handle_owner_response(
        property_id=property_id,
        response_code=response_code,
        platform=platform,
        notes=notes
    )
    return jsonify(result)
