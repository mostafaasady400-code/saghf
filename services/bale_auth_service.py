import logging
import requests
from datetime import datetime
from config import Config
from database.db import db
from database.models import AuthSession, User
from werkzeug.security import generate_password_hash
import secrets

logger = logging.getLogger(__name__)

class BaleAuthService:
    """
    سرویس جامع احراز هویت و ارسال پیام‌های تایید ورود از طریق پیام‌رسان بله (Bale Messenger)
    منطبق بر مستندات رسمی توسعه‌دهندگان بله (tapi.bale.ai)
    """

    BASE_URL = "https://tapi.bale.ai"

    @classmethod
    def get_token(cls) -> str:
        return (Config.BALE_BOT_TOKEN or "").strip()

    @classmethod
    def get_bot_username(cls) -> str:
        return (Config.BALE_BOT_USERNAME or "saghf_auth_bot").strip().lstrip('@')

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls.get_token())

    @classmethod
    def get_deep_link(cls, session_token: str) -> str:
        """
        تولید دیپ‌لینک اختصاصی بله برای تایید ورود فوری
        فرمت استاندارد: https://ble.ir/<bot_username>?start=login_<session_token>
        """
        bot_uname = cls.get_bot_username()
        return f"https://ble.ir/{bot_uname}?start=login_{session_token}"

    @classmethod
    def send_login_prompt(cls, chat_id: str or int, session_token: str, phone: str = "") -> dict:
        """
        ارسال پیام تعاملی دکمه‌دار در پیام‌رسان بله جهت تایید ورود یا ثبت‌نام
        """
        token = cls.get_token()
        if not token:
            logger.info("⚠️ BALE_BOT_TOKEN is not configured; skipping actual HTTP call to tapi.bale.ai.")
            return {'ok': False, 'error': 'TOKEN_NOT_CONFIGURED'}

        url = f"{cls.BASE_URL}/bot{token}/sendMessage"
        display_phone = phone if phone else "نامشخص"
        current_time = datetime.now().strftime('%H:%M')

        text = (
            "⚜️ <b>درخواست ورود به سامانه هوشمند فایلینگ سقف</b> ⚜️\n\n"
            f"همراه گرامی، درخواستی جهت ورود به سایت سقف با شماره <code>{display_phone}</code> ثبت شده است.\n"
            f"⏰ زمان درخواست: <b>{current_time}</b>\n\n"
            "آیا تایید می‌فرمایید که وارد سایت شوید؟"
        )

        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ تایید و ورود به سامانه سقف",
                        "callback_data": f"bale_confirm_{session_token}"
                    }
                ],
                [
                    {
                        "text": "❌ لغو و انصراف",
                        "callback_data": f"bale_reject_{session_token}"
                    }
                ]
            ]
        }

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": reply_markup
        }

        try:
            resp = requests.post(url, json=payload, timeout=8)
            res_data = resp.json() if resp.status_code == 200 else {}
            logger.info(f"Bale sendMessage response: {resp.status_code} - {resp.text}")
            return {'ok': resp.status_code == 200, 'response': res_data}
        except Exception as e:
            logger.error(f"Error calling Bale sendMessage API: {e}")
            return {'ok': False, 'error': str(e)}

    @classmethod
    def answer_callback_query(cls, callback_query_id: str, text: str = "درخواست شما ثبت شد.") -> bool:
        token = cls.get_token()
        if not token or not callback_query_id:
            return False
        url = f"{cls.BASE_URL}/bot{token}/answerCallbackQuery"
        try:
            requests.post(url, json={'callback_query_id': callback_query_id, 'text': text}, timeout=5)
            return True
        except Exception:
            return False

    @classmethod
    def edit_message_text(cls, chat_id: str or int, message_id: int, text: str) -> bool:
        token = cls.get_token()
        if not token:
            return False
        url = f"{cls.BASE_URL}/bot{token}/editMessageText"
        try:
            requests.post(url, json={
                'chat_id': chat_id,
                'message_id': message_id,
                'text': text,
                'parse_mode': 'HTML'
            }, timeout=5)
            return True
        except Exception:
            return False

    @classmethod
    def process_webhook_update(cls, data: dict) -> dict:
        """
        پردازش وب‌هوک دریافتی از پلتفرم بله:
        ۱. بررسی دستور /start login_<token>
        ۲. بررسی کالبک دکمه bale_confirm_<token> یا bale_reject_<token>
        """
        if not isinstance(data, dict):
            return {'status': 'ignored', 'reason': 'invalid_payload'}

        # ۱. پیام متنی یا دستور استارت
        if 'message' in data:
            msg = data['message']
            chat = msg.get('chat', {})
            chat_id = chat.get('id')
            text = (msg.get('text') or '').strip()
            sender = msg.get('from', {})
            first_name = sender.get('first_name', 'کاربر بله')

            if text.startswith('/start'):
                parts = text.split()
                if len(parts) > 1 and parts[1].startswith('login_'):
                    session_token = parts[1].replace('login_', '').strip()
                    # بررسی سشن
                    auth_sess = AuthSession.query.filter_by(session_token=session_token).first()
                    if auth_sess and not auth_sess.is_expired and auth_sess.status == 'pending':
                        auth_sess.messenger_user_id = str(chat_id)
                        auth_sess.messenger_user_name = first_name
                        db.session.commit()
                        # ارسال پیام تایید به کاربر با دکمه اینلاین
                        cls.send_login_prompt(chat_id, session_token, auth_sess.phone)
                        return {'status': 'prompt_sent', 'token': session_token}
                    else:
                        cls._send_simple_message(chat_id, "⚠️ نشست ورود یافت نشد یا منقضی شده است. لطفاً مجدداً در سایت تلاش فرمایید.")
                        return {'status': 'session_not_found'}

        # ۲. رویداد کالبک دکمه اینلاین
        if 'callback_query' in data:
            cb = data['callback_query']
            cb_id = cb.get('id')
            cb_data = cb.get('data', '')
            sender = cb.get('from', {})
            user_id = sender.get('id')
            user_name = sender.get('first_name', 'کاربر بله')
            message = cb.get('message', {})
            chat_id = message.get('chat', {}).get('id')
            message_id = message.get('message_id')

            if cb_data.startswith('bale_confirm_') or cb_data.startswith('confirm_'):
                token = cb_data.replace('bale_confirm_', '').replace('confirm_', '').strip()
                auth_sess = AuthSession.query.filter_by(session_token=token).first()
                if auth_sess and not auth_sess.is_expired:
                    # تایید ورود و ایجاد/بازیابی کاربر
                    cls.confirm_session_and_login_user(auth_sess, str(user_id), user_name)
                    cls.answer_callback_query(cb_id, "✅ ورود شما به سایت سقف با موفقیت تایید شد.")
                    if chat_id and message_id:
                        cls.edit_message_text(
                            chat_id,
                            message_id,
                            "⚜️ <b>سامانه هوشمند فایلینگ سقف</b>\n\n✅ <b>ورود با موفقیت تایید شد!</b>\nهم‌اکنون نشست کاربری شما در سایت سقف فعال گردید."
                        )
                    return {'status': 'confirmed', 'token': token}
                else:
                    cls.answer_callback_query(cb_id, "❌ این نشست منقضی شده است.")
                    return {'status': 'expired'}

            elif cb_data.startswith('bale_reject_') or cb_data.startswith('reject_'):
                token = cb_data.replace('bale_reject_', '').replace('reject_', '').strip()
                auth_sess = AuthSession.query.filter_by(session_token=token).first()
                if auth_sess:
                    auth_sess.status = 'rejected'
                    db.session.commit()
                cls.answer_callback_query(cb_id, "❌ درخواست ورود لغو شد.")
                if chat_id and message_id:
                    cls.edit_message_text(chat_id, message_id, "❌ <b>درخواست ورود به سقف لغو گردید.</b>")
                return {'status': 'rejected', 'token': token}

        return {'status': 'ignored'}

    @classmethod
    def confirm_session_and_login_user(cls, auth_sess: AuthSession, messenger_id: str, messenger_name: str) -> User:
        """
        تایید نهایی نشست و ثبت‌نام خودکار کاربر در صورتی که کاربر جدید باشد (Seamless Onboarding)
        """
        phone = auth_sess.phone
        user = None

        # جستجوی کاربر با شماره همراه، شناسه بله یا تلگرام
        if phone:
            user = User.query.filter_by(phone=phone).first()

        if not user and messenger_id:
            if auth_sess.platform == 'bale':
                user = User.query.filter_by(bale_id=str(messenger_id)).first()
            else:
                user = User.query.filter_by(telegram_id=str(messenger_id)).first()

        if not user:
            # ایجاد خودکار کاربر جدید (بدون نیاز به پسورد)
            base_uname = f"user_{phone}" if phone else f"{auth_sess.platform}_{messenger_id}"
            # تضمین یکتایی نام کاربری
            existing = User.query.filter_by(username=base_uname).first()
            if existing:
                base_uname = f"{base_uname}_{secrets.token_hex(2)}"

            display_name = messenger_name if messenger_name else (f"کاربر {phone}" if phone else "کاربر گرامی سقف")
            user = User(
                username=base_uname,
                full_name=display_name,
                phone=phone or '',
                role='user',
                is_active=True,
                notes=f'ثبت‌نام خودکار از طریق پیام‌رسان {auth_sess.platform}'
            )
            # تعیین یک رمز عبور تصادفی امن غیرقابل نفوذ برای حفظ محدودیت دیتابیس
            user.set_password(secrets.token_urlsafe(32))

            if auth_sess.platform == 'bale':
                user.bale_id = str(messenger_id)
            else:
                user.telegram_id = str(messenger_id)

            db.session.add(user)
            db.session.flush()
        else:
            # به‌روزرسانی مشخصات و شناسه‌ها در صورت لزوم
            if auth_sess.platform == 'bale' and not user.bale_id:
                user.bale_id = str(messenger_id)
            elif auth_sess.platform == 'telegram' and not user.telegram_id:
                user.telegram_id = str(messenger_id)
            if phone and not user.phone:
                user.phone = phone

        # ثبت ورود و تایید سشن
        user.last_login = datetime.utcnow()
        auth_sess.status = 'confirmed'
        auth_sess.user_id = user.id
        auth_sess.messenger_user_id = str(messenger_id)
        auth_sess.messenger_user_name = messenger_name
        auth_sess.confirmed_at = datetime.utcnow()
        db.session.commit()
        return user

    @classmethod
    def _send_simple_message(cls, chat_id: str or int, text: str):
        token = cls.get_token()
        if not token:
            return
        url = f"{cls.BASE_URL}/bot{token}/sendMessage"
        try:
            requests.post(url, json={'chat_id': chat_id, 'text': text}, timeout=5)
        except Exception:
            pass
