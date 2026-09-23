import re
import secrets
import logging
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from config import Config
from database.db import db
from database.models import User, AuthSession
from services.bale_auth_service import BaleAuthService
from telegram_bot.bot import send_telegram_login_prompt

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def normalize_iran_phone(phone_str: str) -> str:
    """
    نرمال‌سازی شماره همراه ایران به فرمت استاندارد 09xxxxxxxxx
    پشتیبانی از اعداد فارسی، پیشوندهای +98 یا 0098 یا 98
    """
    if not phone_str:
        return ""
    # تبدیل ارقام فارسی و عربی به انگلیسی
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
    raw = str(phone_str).translate(fa_to_en).strip()
    digits = ''.join(c for c in raw if c.isdigit())

    if digits.startswith('0098') and len(digits) == 14:
        digits = '0' + digits[4:]
    elif digits.startswith('98') and len(digits) == 12:
        digits = '0' + digits[2:]
    elif len(digits) == 10 and digits.startswith('9'):
        digits = '0' + digits

    if len(digits) == 11 and digits.startswith('09'):
        return digits
    return digits

@auth_bp.route('/login', methods=['GET'])
@auth_bp.route('/register', methods=['GET'])
def login():
    """
    صفحه مستقل ورود و ثبت‌نام کاربر عادی سقف
    """
    if session.get('user_id') or session.get('is_admin'):
        return redirect(url_for('dashboard.index'))

    return render_template(
        'auth/login.html',
        telegram_bot_username=Config.TELEGRAM_BOT_USERNAME or 'saghf_bot',
        bale_bot_username=BaleAuthService.get_bot_username()
    )

@auth_bp.route('/request-session', methods=['POST'])
def request_session():
    """
    ایجاد نشست احراز هویت با شماره همراه برای تلگرام یا بله
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        raw_phone = data.get('phone', '').strip()
        platform = (data.get('platform') or 'telegram').lower().strip()

        if platform not in ['telegram', 'bale']:
            return jsonify({'success': False, 'message': 'پلتفرم نامعتبر است. فقط telegram یا bale مجاز است.'}), 400

        norm_phone = normalize_iran_phone(raw_phone)
        if not norm_phone or len(norm_phone) != 11 or not norm_phone.startswith('09'):
            return jsonify({
                'success': False,
                'message': 'لطفاً شماره همراه معتبر ۱۱ رقمی (مانند ۰۹۱۲۳۴۵۶۷۸۹) وارد فرمایید.'
            }), 400

        # تولید توکن امن تصادفی
        session_token = secrets.token_hex(20)
        expires_at = datetime.utcnow() + timedelta(minutes=5)

        auth_sess = AuthSession(
            session_token=session_token,
            phone=norm_phone,
            platform=platform,
            status='pending',
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr),
            user_agent=(request.headers.get('User-Agent') or '')[:250],
            created_at=datetime.utcnow(),
            expires_at=expires_at
        )
        db.session.add(auth_sess)
        db.session.commit()

        direct_sent = False
        # بررسی اینکه آیا کاربر قبلاً شناسه چت ثبت‌شده در سیستم دارد یا خیر
        user = User.query.filter_by(phone=norm_phone).first()
        if user:
            if platform == 'telegram' and user.telegram_id:
                direct_sent = send_telegram_login_prompt(user.telegram_id, session_token, norm_phone)
            elif platform == 'bale' and user.bale_id:
                res = BaleAuthService.send_login_prompt(user.bale_id, session_token, norm_phone)
                direct_sent = res.get('ok', False)

        # تولید دیپ‌لینک پیام‌رسان
        if platform == 'telegram':
            bot_uname = Config.TELEGRAM_BOT_USERNAME or 'saghf_bot'
            deep_link = f"https://t.me/{bot_uname}?start=login_{session_token}"
        else:
            deep_link = BaleAuthService.get_deep_link(session_token)

        return jsonify({
            'success': True,
            'session_token': session_token,
            'platform': platform,
            'phone': norm_phone,
            'deep_link': deep_link,
            'direct_prompt_sent': direct_sent,
            'expires_in_seconds': 300,
            'message': 'پیام تایید با موفقیت آماده شد.'
        })

    except Exception as e:
        logger.error(f"Error requesting auth session: {e}")
        return jsonify({'success': False, 'message': f'خطا در ایجاد نشست: {str(e)}'}), 500

@auth_bp.route('/check-session/<token>', methods=['GET'])
def check_session(token):
    """
    بررسی وضعیت لحظه‌ای نشست احراز هویت (Polling اندپوینت)
    به محض تایید در تلگرام یا بله، کوکی سشن لاگین تنظیم و پاسخ موفق داده می‌شود.
    """
    try:
        auth_sess = AuthSession.query.filter_by(session_token=token).first()
        if not auth_sess:
            return jsonify({'success': False, 'status': 'not_found', 'message': 'نشست یافت نشد.'}), 404

        if auth_sess.is_expired and auth_sess.status == 'pending':
            auth_sess.status = 'expired'
            db.session.commit()
            return jsonify({'success': False, 'status': 'expired', 'message': 'زمان اعتبار نشست به پایان رسیده است.'})

        if auth_sess.status == 'rejected':
            return jsonify({'success': False, 'status': 'rejected', 'message': 'درخواست ورود در پیام‌رسان لغو شد.'})

        if auth_sess.status == 'confirmed' and auth_sess.user_id:
            user = db.session.get(User, auth_sess.user_id)
            if not user or not user.is_active:
                return jsonify({'success': False, 'status': 'error', 'message': 'حساب کاربری غیرفعال است.'}), 403

            # تنظیم نشست کوکی Flask برای کاربر لاگین‌شده
            session['user_id'] = user.id
            session['username'] = user.username
            session['user_role'] = user.role
            session['user_phone'] = user.phone or ''
            session['user_full_name'] = user.full_name
            session['is_logged_in'] = True

            # اگر نقش کاربر ادمین باشد، سشن ادمین را نیز ست کن
            if user.role in ['admin', 'super_admin']:
                session['is_admin'] = True
                session['admin_user'] = user.username

            return jsonify({
                'success': True,
                'status': 'confirmed',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'full_name': user.full_name,
                    'phone': user.phone,
                    'role': user.role,
                    'role_title': user.role_title
                },
                'redirect_url': url_for('dashboard.index'),
                'message': 'ورود با موفقیت انجام شد.'
            })

        return jsonify({
            'success': True,
            'status': 'pending',
            'platform': auth_sess.platform,
            'phone': auth_sess.phone
        })

    except Exception as e:
        logger.error(f"Error checking auth session: {e}")
        return jsonify({'success': False, 'status': 'error', 'message': str(e)}), 500

@auth_bp.route('/simulate-confirm', methods=['POST'])
def simulate_confirm():
    """
    اندپوینت شبیه‌سازی تایید ورود (مخصوص تست‌های محلی و خودکار)
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        token = data.get('session_token', '').strip()
        messenger_id = data.get('messenger_id', '99887766')
        messenger_name = data.get('messenger_name', 'کاربر تستی سقف')

        auth_sess = AuthSession.query.filter_by(session_token=token).first()
        if not auth_sess:
            return jsonify({'success': False, 'message': 'نشست یافت نشد.'}), 404

        user = BaleAuthService.confirm_session_and_login_user(auth_sess, str(messenger_id), messenger_name)
        return jsonify({
            'success': True,
            'message': 'نشست با موفقیت تایید شد.',
            'user': user.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@auth_bp.route('/bale/webhook', methods=['POST'])
def bale_webhook():
    """
    وب‌هوک رسمی دریافت رویدادها از پیام‌رسان بله
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        res = BaleAuthService.process_webhook_update(data)
        return jsonify({'ok': True, 'result': res})
    except Exception as e:
        logger.error(f"Error processing Bale webhook: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """
    خروج امن از حساب کاربری
    """
    user_name = session.get('user_full_name') or 'کاربر گرامی'
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('user_role', None)
    session.pop('user_phone', None)
    session.pop('user_full_name', None)
    session.pop('is_logged_in', None)
    session.pop('is_admin', None)
    session.pop('admin_user', None)

    flash(f'{user_name} عزیز، با موفقیت از حساب کاربری خود خارج شدید.', 'info')
    return redirect(url_for('dashboard.index'))

@auth_bp.route('/me', methods=['GET'])
def current_user_info():
    """
    دریافت اطلاعات حساب کاربری لاگین‌شده
    """
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'logged_in': False})

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'logged_in': False})

    return jsonify({
        'logged_in': True,
        'user': user.to_dict()
    })
