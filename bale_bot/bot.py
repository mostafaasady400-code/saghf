"""
ربات رسمی و هوشمند پیام‌رسان بله سامانه سقف (Saghf Bale Bot)
پیاده‌سازی کامل و ۱۰۰٪ منطبق با قابلیت‌های ربات تلگرام (Tri-Platform Feature Parity):
- احراز هویت بدون رمز و دیپ‌لینک‌ها (Passwordless Login & Deep Links)
- ویزارد ۵ مرحله‌ای پیشرفته استخراج زنده و امتیازدهی هوشمند (Live Scraping & Scoring)
- جستجو و پرزنت فوری آلبوم تصاویر با کد ۵ رقمی ملک
- کنسول مدیریت کامل (Admin Panel, Stats, Crawl, Multi-Admin CRUD)
- امکان فعال‌سازی آنی دسترسی سوپرادمین روی اکانت بله با /admin_login
- استعلام دوگانه ملک و کاربر (/search, /find, /user)
- آلارم‌های لحظه‌ای طلایی و سبز با دکمه‌های شیشه‌ای تایید و انتشار
- اتصال به موتور OmniChannel CRM و پایپ‌لاین‌های اتوماسیون
- رعایت خط قرمزهای AGENTS.md (لینک مستقیم آگهی با تگ <a>لینک آگهی</a> و عدم استفاده از داده ماک)
"""

import os
import json
import logging
import html
from datetime import datetime
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from config import Config

logger = logging.getLogger(__name__)

# Hook telebot apihelper to dynamically route Bale Bot requests to tapi.bale.ai
_orig_make_request = telebot.apihelper._make_request

def _bale_patched_make_request(token, method_name, method='get', params=None, files=None, **kwargs):
    bale_token = (Config.BALE_BOT_TOKEN or "").strip()
    if token and bale_token and token == bale_token:
        old_url = telebot.apihelper.API_URL
        telebot.apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
        try:
            return _orig_make_request(token, method_name, method=method, params=params, files=files, **kwargs)
        finally:
            telebot.apihelper.API_URL = old_url
    return _orig_make_request(token, method_name, method=method, params=params, files=files, **kwargs)

telebot.apihelper._make_request = _bale_patched_make_request

_bot_instance = None
_flask_app_instance = None

def set_flask_app(app):
    """تنظیم نمونه Flask جهت دسترسی به اپلیکیشن در هندلرها"""
    global _flask_app_instance
    _flask_app_instance = app

def get_flask_app():
    """دریافت یا ساخت نمونه Flask جهت اجرای کدهای وابسته به دیتابیس"""
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

def get_bale_bot():
    """
    نمونه یکتای (Singleton) ربات بله
    """
    global _bot_instance
    if _bot_instance is None:
        token = Config.BALE_BOT_TOKEN or ""
        if not token:
            logger.warning("⚠️ BALE_BOT_TOKEN is not configured in environment variables.")
        _bot_instance = telebot.TeleBot(token=token, threaded=False)
        _register_bale_handlers(_bot_instance)
    return _bot_instance

def process_bale_update(update_dict):
    """
    پردازش یک رویداد دریافتی از وب‌هوک بله (سازگار با telebot و JSON خام)
    """
    bot = get_bale_bot()
    if not bot:
        return False
    try:
        if isinstance(update_dict, dict):
            update = telebot.types.Update.de_json(update_dict)
            if update:
                bot.process_new_updates([update])
                return True
    except Exception as e:
        logger.error(f"Error in process_bale_update: {e}")
    return False

# ==========================================
# Persistent Admin Storage for Bale
# ==========================================
BALE_ADMIN_STORAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'bale_admins.json')

def _load_admin_store() -> dict:
    default_store = {
        "super_admins": ["7495565146"],
        "admins": ["7495565146"],
        "admin_metadata": {
            "7495565146": {
                "role": "super_admin",
                "title": "مدیر ارشد و بنیان‌گذار",
                "added_at": "2026-09-18 12:00:00"
            }
        }
    }
    if not os.path.exists(BALE_ADMIN_STORAGE_FILE):
        try:
            os.makedirs(os.path.dirname(BALE_ADMIN_STORAGE_FILE), exist_ok=True)
            with open(BALE_ADMIN_STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error creating default bale admin store: {e}")
        return default_store

    try:
        with open(BALE_ADMIN_STORAGE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            admins = data.setdefault("admins", [])
            super_admins = data.setdefault("super_admins", [])
            if "7495565146" not in super_admins:
                super_admins.append("7495565146")
            if "7495565146" not in admins:
                admins.append("7495565146")

            env_admin = str(Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID or "").strip()
            if env_admin:
                for aid in env_admin.split(','):
                    aid = aid.strip()
                    if aid and aid not in admins:
                        admins.append(aid)
            return data
    except Exception as e:
        logger.error(f"Error reading bale admin store: {e}")
        return default_store

def _save_admin_store(data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(BALE_ADMIN_STORAGE_FILE), exist_ok=True)
        with open(BALE_ADMIN_STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving bale admin store: {e}")
        return False

def get_all_bale_admin_ids() -> set[str]:
    store = _load_admin_store()
    admin_set = set(str(x).strip() for x in store.get("admins", []))
    env_admin = str(Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID or "").strip()
    if env_admin:
        for aid in env_admin.split(','):
            if aid.strip():
                admin_set.add(aid.strip())
    admin_set.add("7495565146")
    return admin_set

def is_bale_admin_user(user_id) -> bool:
    if not user_id:
        return False
    return str(user_id).strip() in get_all_bale_admin_ids()

def is_bale_super_admin(user_id) -> bool:
    if not user_id:
        return False
    uid = str(user_id).strip()
    store = _load_admin_store()
    super_admins = set(str(x).strip() for x in store.get("super_admins", []))
    env_admin = str(Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID or "").strip()
    if env_admin:
        super_admins.add(env_admin)
    super_admins.add("7495565146")
    return uid in super_admins

def claim_bale_superadmin(user_id: str, password: str) -> tuple[bool, str]:
    """
    اعطای فوری و قطعی سطح مدیر ارشد (Super Admin) به اکانت بله کاربر در صورت صحت رمز عبور
    """
    uid = str(user_id).strip()
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    uid = uid.translate(fa_to_en)
    
    expected_pwd = Config.ADMIN_PASSWORD or "SaghfSuperAdmin#2026!"
    if password.strip() != expected_pwd.strip():
        return False, "رمز عبور مدیریت نادرست است. لطفاً مجدداً بررسی فرمایید."

    store = _load_admin_store()
    admins = store.setdefault("admins", [])
    super_admins = store.setdefault("super_admins", [])
    if uid not in super_admins:
        super_admins.append(uid)
    if uid not in admins:
        admins.append(uid)
    store.setdefault("admin_metadata", {})[uid] = {
        "role": "super_admin",
        "title": "مدیر ارشد و بنیان‌گذار (Bale)",
        "claimed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    _save_admin_store(store)

    # همگام‌سازی در جدول User دیتابیس
    app = get_flask_app()
    with app.app_context():
        from database.models import User
        from database.db import db
        s_user = User.query.filter_by(username='saghf_admin').first()
        if s_user:
            s_user.bale_id = uid
            db.session.commit()

    logger.info(f"👑 User {uid} successfully claimed Bale Super Admin status.")
    return True, f"تبریک! حساب کاربری شما با شناسه <code>{uid}</code> به عنوان **مدیر ارشد سامانه سقف** تایید گردید."

def add_bale_admin_user(target_id: str, added_by: str = None) -> tuple[bool, str]:
    target_id = str(target_id).strip()
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    target_id = target_id.translate(fa_to_en)
    
    if not target_id.isdigit() or len(target_id) < 5:
        return False, "شناسه عددی نامعتبر است (باید حداقل ۵ رقم و فقط عدد باشد)."
        
    store = _load_admin_store()
    admins = store.setdefault("admins", [])
    if target_id in admins:
        return False, f"شناسه <code>{target_id}</code> در حال حاضر در لیست مدیران بله وجود دارد."
        
    admins.append(target_id)
    store.setdefault("admin_metadata", {})[target_id] = {
        "role": "admin",
        "title": "مدیر سیستم بله",
        "added_by": str(added_by or ""),
        "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    _save_admin_store(store)
    return True, f"کاربر با شناسه <code>{target_id}</code> با موفقیت به مدیران بله اضافه شد."

def remove_bale_admin_user(target_id: str) -> tuple[bool, str]:
    target_id = str(target_id).strip()
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    target_id = target_id.translate(fa_to_en)
    
    if target_id == "7495565146":
        return False, "امکان حذف مدیر ارشد و بنیان‌گذار (<code>7495565146</code>) وجود ندارد."
        
    env_admin = str(Config.BALE_ADMIN_ID or Config.ADMIN_TELEGRAM_ID or "").strip()
    if env_admin and target_id == env_admin:
        return False, "این شناسه در تنظیمات اصلی سرور ثبت شده و از داخل بات قابل حذف نیست."

    store = _load_admin_store()
    admins = store.get("admins", [])
    if target_id not in admins:
        return False, f"شناسه <code>{target_id}</code> در لیست مدیران بله یافت نشد."
        
    admins.remove(target_id)
    if "admin_metadata" in store and target_id in store["admin_metadata"]:
        del store["admin_metadata"][target_id]
    _save_admin_store(store)
    return True, f"مدیر با شناسه <code>{target_id}</code> با موفقیت از بله حذف گردید."

# ==========================================
# Keyboard Builders (Matching Telegram 100%)
# ==========================================
wizard_sessions = {}

def _build_start_keyboard(user_id=None):
    """
    کیبورد اصلی شیشه‌ای ربات منطبق بر ساختار شیک تلگرام
    """
    markup = InlineKeyboardMarkup(row_width=2)
    if user_id and is_bale_admin_user(user_id):
        markup.add(InlineKeyboardButton("👑 پنل اختصاصی مدیریت (Admin)", callback_data="admin_cb_menu"))

    btn_wizard = InlineKeyboardButton("🎯 فیلتر و استخراج جدید", callback_data="wiz_start")
    btn_sale = InlineKeyboardButton("🏷️ آخرین فایل‌های فروش", callback_data="btn_latest_sale")
    btn_rent = InlineKeyboardButton("🔑 آخرین فایل‌های اجاره", callback_data="btn_latest_rent")
    btn_code_search = InlineKeyboardButton("🔢 دریافت آلبوم با کد فایل", callback_data="btn_code_info")
    btn_search = InlineKeyboardButton("🔍 استعلام و فیلتر پیشرفته", callback_data="btn_search_info")
    btn_myid = InlineKeyboardButton("🆔 شناسه من (User ID)", callback_data="btn_myid")
    
    web_url = "http://127.0.0.1:5000"
    btn_web = InlineKeyboardButton("🌐 مشاهده سامانه تحت وب سقف", url=web_url)

    markup.add(btn_wizard)
    markup.add(btn_sale, btn_rent)
    markup.add(btn_code_search, btn_search)
    markup.add(btn_myid, btn_web)
    return markup

def _build_admin_panel_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 آمار دیتابیس", callback_data="admin_cb_stats"),
        InlineKeyboardButton("🕷️ استخراج فوری", callback_data="admin_cb_crawl")
    )
    markup.add(
        InlineKeyboardButton("👥 لیست مدیران", callback_data="admin_cb_list"),
        InlineKeyboardButton("➕ افزودن مدیر جدید", callback_data="admin_cb_add_guide")
    )
    web_url = "http://127.0.0.1:5000"
    markup.add(
        InlineKeyboardButton("👥 مدیریت کاربران (CRUD)", url=f"{web_url}/admin/users"),
        InlineKeyboardButton("🌐 داشبورد مدیریت وب", url=f"{web_url}/admin/dashboard")
    )
    return markup

def _build_wizard_step1_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🏷️ خرید و فروش", callback_data="wiz_deal_sale"),
        InlineKeyboardButton("🔑 رهن و اجاره", callback_data="wiz_deal_rent")
    )
    markup.add(InlineKeyboardButton("❌ انصراف", callback_data="wiz_cancel"))
    return markup

def _build_wizard_step2_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🏢 آپارتمان", callback_data="wiz_type_apartment"),
        InlineKeyboardButton("🏡 ویلایی / کلنگی", callback_data="wiz_type_villa")
    )
    markup.add(InlineKeyboardButton("🏬 اداری / تجاری", callback_data="wiz_type_commercial"))
    markup.add(
        InlineKeyboardButton("🔙 مرحله قبل", callback_data="wiz_back_1"),
        InlineKeyboardButton("❌ انصراف", callback_data="wiz_cancel")
    )
    return markup

def _build_wizard_step3_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📍 پونک", callback_data="wiz_dist_پونک"),
        InlineKeyboardButton("📍 جنت‌آباد", callback_data="wiz_dist_جنت‌آباد")
    )
    markup.add(
        InlineKeyboardButton("📍 صادقیه / ستارخان", callback_data="wiz_dist_صادقیه"),
        InlineKeyboardButton("📍 شهران", callback_data="wiz_dist_شهران")
    )
    markup.add(
        InlineKeyboardButton("📍 سعادت‌آباد", callback_data="wiz_dist_سعادت‌آباد"),
        InlineKeyboardButton("📍 کل منطقه ۵", callback_data="wiz_dist_منطقه ۵")
    )
    markup.add(InlineKeyboardButton("✍️ تایپ نام محله دلخواه", callback_data="wiz_dist_custom"))
    markup.add(
        InlineKeyboardButton("🔙 مرحله قبل", callback_data="wiz_back_2"),
        InlineKeyboardButton("❌ انصراف", callback_data="wiz_cancel")
    )
    return markup

def _build_wizard_step4_markup(deal_type: str):
    markup = InlineKeyboardMarkup(row_width=1)
    if deal_type == 'sale':
        markup.add(InlineKeyboardButton("📐 متراژ تا ۸۰ م | تا ۶ میلیارد", callback_data="wiz_bud_s1"))
        markup.add(InlineKeyboardButton("📐 متراژ ۸۰ تا ۱۱۰ م | ۶ تا ۱۰ میلیارد", callback_data="wiz_bud_s2"))
        markup.add(InlineKeyboardButton("📐 متراژ ۱۱۰ تا ۱۵۰ م | ۱۰ تا ۱۶ میلیارد", callback_data="wiz_bud_s3"))
        markup.add(InlineKeyboardButton("📐 متراژ ۱۵۰+ م | ۱۶+ میلیارد", callback_data="wiz_bud_s4"))
        markup.add(InlineKeyboardButton("🌐 بدون محدودیت بودجه و متراژ", callback_data="wiz_bud_any"))
    else:
        markup.add(InlineKeyboardButton("💳 ودیعه تا ۵۰۰ م | اجاره تا ۱۵ م", callback_data="wiz_bud_r1"))
        markup.add(InlineKeyboardButton("💳 ودیعه ۵۰۰ تا ۱ م | اجاره ۱۵ تا ۳۰ م", callback_data="wiz_bud_r2"))
        markup.add(InlineKeyboardButton("💳 ودیعه ۱ تا ۲ م | اجاره ۳۰ تا ۵۰ م", callback_data="wiz_bud_r3"))
        markup.add(InlineKeyboardButton("💳 رهن کامل (۱.۵ تا ۳ میلیارد)", callback_data="wiz_bud_r4"))
        markup.add(InlineKeyboardButton("🌐 بدون محدودیت بودجه و متراژ", callback_data="wiz_bud_any"))
    markup.add(
        InlineKeyboardButton("🔙 مرحله قبل", callback_data="wiz_back_3"),
        InlineKeyboardButton("❌ انصراف", callback_data="wiz_cancel")
    )
    return markup

def _build_wizard_step5_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🚀 شروع استخراج و جستجو", callback_data="wiz_exec"))
    markup.add(
        InlineKeyboardButton("🔄 تنظیم مجدد", callback_data="wiz_start"),
        InlineKeyboardButton("❌ انصراف", callback_data="wiz_cancel")
    )
    return markup

def _is_property_code_query(text: str) -> bool:
    if not text or text.startswith('/'):
        return False
    raw = text.strip()
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    cleaned = raw.translate(fa_to_en)
    for kw in ['کد', 'فایل', 'code', 'file', '#', ':', '،', ',', '-', 'شماره']:
        cleaned = cleaned.replace(kw, '')
    cleaned = cleaned.strip()
    return cleaned.isdigit() and (1 <= len(cleaned) <= 6)

def _format_compact_property(p):
    """
    فرمت‌بندی فشرده و استاندارد کارت ملک برای چت بله همراه با تگ مستقیم لینک آگهی
    """
    deal_title = '🏷️ فروش' if p.deal_type == 'sale' else '🔑 رهن و اجاره'
    lines = [
        f"<b>{html.escape(p.title or 'بدون عنوان')}</b>",
        f"📍 منطقه: {html.escape(p.district or 'تهران')}",
        f"📐 متراژ: {p.area} متر | 🛏️ {p.rooms} خواب | طبقه: {p.floor or 1}",
        f"📌 نوع: {deal_title}"
    ]

    if p.deal_type == 'sale':
        if p.total_price and p.total_price > 0:
            price_b = p.total_price / 1_000_000_000
            price_str = f"{price_b:.2f} میلیارد تومان" if price_b >= 1 else f"{p.total_price / 1_000_000:.0f} میلیون تومان"
            lines.append(f"💰 قیمت کل: <b>{price_str}</b>")
        else:
            lines.append("💰 قیمت: توافقی")
    else:
        dep = f"{p.deposit / 1_000_000:.0f} م تومان" if p.deposit else "توافقی"
        rnt = f"{p.monthly_rent / 1_000_000:.0f} م تومان" if p.monthly_rent else "توافقی"
        lines.append(f"💳 ودیعه: <b>{dep}</b> | اجاره: <b>{rnt}</b>")

    amenities = []
    if p.has_parking: amenities.append("پارکینگ")
    if p.has_elevator: amenities.append("آسانسور")
    if p.has_warehouse: amenities.append("انباری")
    if p.has_balcony: amenities.append("بالکن")
    if amenities:
        lines.append(f"✨ امکانات: {' • '.join(amenities)}")

    ad_link = html.escape(p.source_url or f"http://127.0.0.1:5000/properties/{p.id}")
    lines.append(f'\n🌐 <a href="{ad_link}">لینک آگهی</a>')
    return "\n".join(lines)

# ==========================================
# Register Handlers on Bale Bot
# ==========================================
def _register_bale_handlers(bot: telebot.TeleBot):

    # 1. Start & Help command with Deep Link Support
    @bot.message_handler(commands=['start', 'help'])
    def handle_start(message):
        text_parts = message.text.split() if message.text else []
        if len(text_parts) > 1:
            param = text_parts[1].strip()

            # بررسی ورود بدون رمز (Passwordless Login)
            if param.startswith('login_') or param.startswith('auth_'):
                session_token = param.replace('login_', '').replace('auth_', '').strip()
                app = get_flask_app()
                with app.app_context():
                    from database.models import AuthSession
                    from database.db import db
                    auth_sess = AuthSession.query.filter_by(session_token=session_token).first()
                    if auth_sess and not auth_sess.is_expired and auth_sess.status == 'pending':
                        auth_sess.messenger_user_id = str(message.chat.id)
                        auth_sess.messenger_user_name = message.from_user.first_name or ''
                        db.session.commit()

                        markup = InlineKeyboardMarkup(row_width=1)
                        markup.add(
                            InlineKeyboardButton("✅ تایید و ورود به سامانه سقف", callback_data=f"bale_confirm_{session_token}"),
                            InlineKeyboardButton("❌ لغو درخواست", callback_data=f"bale_reject_{session_token}")
                        )
                        disp_phone = auth_sess.phone if auth_sess.phone else "شماره همراه شما"
                        prompt_text = (
                            "⚜️ <b>درخواست ورود به سامانه فایلینگ سقف</b> ⚜️\n\n"
                            f"سلام <b>{html.escape(message.from_user.first_name or 'کاربر گرامی')}</b>،\n"
                            f"درخواستی برای ورود/ثبت‌نام با شماره <code>{disp_phone}</code> به سایت سقف ارسال شده است.\n\n"
                            "آیا تایید می‌فرمایید که با این حساب بله وارد سامانه سقف شوید؟"
                        )
                        bot.send_message(message.chat.id, prompt_text, reply_markup=markup, parse_mode='HTML')
                        return
                    else:
                        bot.send_message(message.chat.id, "⚠️ این نشست ورود منقضی شده یا یافت نشد. لطفاً مجدداً در سایت تلاش فرمایید.")
                        return

            # بررسی جستجو با کد ملک (مثلاً /start code_10001)
            code_candidate = param.replace('code_', '')
            fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            clean_digits = ''.join(filter(str.isdigit, code_candidate.translate(fa_to_en)))
            if clean_digits:
                app = get_flask_app()
                with app.app_context():
                    from database.models import Property
                    from .notifier import send_property_bale_media
                    prop = Property.get_by_code(clean_digits)
                    if prop:
                        bot.send_message(message.chat.id, f"📸 در حال ارسال اطلاعات و تصاویر فایل کد {prop.file_code} ({html.escape(prop.title)})...")
                        send_property_bale_media(prop, message.chat.id, bot=bot)
                        return
                    else:
                        bot.send_message(message.chat.id, f"❌ فایل با کد «{clean_digits}» در سامانه سقف یافت نشد.")

        user_name = message.from_user.first_name or "همراه گرامی"
        welcome_text = (
            f"⚜️ <b>سلام {html.escape(user_name)}، به سامانه هوشمند فایلینگ املاک سقف خوش آمدید!</b> ⚜️\n\n"
            "این ربات مستقیماً به پایپ‌لاین و موتور استخراج هوشمند فایلینگ املاک سقف متصل است.\n\n"
            "💡 <b>پرزنت سریع با کد فایل:</b>\n"
            "کافیست <b>کد ۵ رقمی هر ملک</b> (مثلاً <code>10001</code>) را به همین چت ارسال نمایید تا <b>تصاویر باکیفیت و مشخصات فنی</b> بلافاصله برای شما ارسال شود.\n\n"
            "جهت مشاهده فایل‌های دسته‌بندی‌شده یا استعلام هوشمند، از گزینه‌های زیر استفاده فرمایید:"
        )

        try:
            logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'images', 'saghf_logo_official.jpg')
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as pf:
                    bot.send_photo(
                        message.chat.id,
                        photo=pf,
                        caption=welcome_text,
                        reply_markup=_build_start_keyboard(message.from_user.id),
                        parse_mode='HTML'
                    )
            else:
                bot.reply_to(message, welcome_text, reply_markup=_build_start_keyboard(message.from_user.id), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling /start message in Bale: {e}")
            try:
                bot.reply_to(message, welcome_text, reply_markup=_build_start_keyboard(message.from_user.id), parse_mode='HTML')
            except Exception:
                pass

    # 2. Direct property code command: /code 10001
    @bot.message_handler(commands=['code'])
    def handle_code_command(message):
        try:
            text_parts = message.text.split() if message.text else []
            if len(text_parts) < 2:
                bot.reply_to(message, "⚠️ لطفاً کد ملک را وارد فرمایید.\nمثال: <code>/code 10001</code>", parse_mode='HTML')
                return
            code_arg = text_parts[1].strip()
            fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            clean_digits = ''.join(filter(str.isdigit, code_arg.translate(fa_to_en)))
            if not clean_digits:
                bot.reply_to(message, "❌ کد نامعتبر است.")
                return

            app = get_flask_app()
            with app.app_context():
                from database.models import Property
                from .notifier import send_property_bale_media
                prop = Property.get_by_code(clean_digits)
                if prop:
                    bot.send_message(message.chat.id, f"📸 در حال ارسال اطلاعات و تصویر فایل کد {prop.file_code}...")
                    send_property_bale_media(prop, message.chat.id, bot=bot)
                else:
                    bot.reply_to(message, f"❌ ملکی با کد «{clean_digits}» در سامانه سقف یافت نشد.")
        except Exception as e:
            logger.error(f"Error handling Bale code command: {e}")

    # 3. User ID & Role Discovery: /id, /myid, /whoami
    @bot.message_handler(commands=['id', 'myid', 'whoami'])
    def handle_my_id_command(message):
        user_id = message.from_user.id
        user_name = message.from_user.first_name or "کاربر بله"
        user_handle = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
        is_admin = is_bale_admin_user(user_id)
        is_super = is_bale_super_admin(user_id)
        
        if is_super:
            status_badge = "👑 <b>مدیر ارشد (Super Admin)</b>"
        elif is_admin:
            status_badge = "🛡️ <b>مدیر تاییدشده سیستم (Admin)</b>"
        else:
            status_badge = "👤 <b>کاربر عادی</b>"

        text = (
            f"🆔 <b>مشخصات و شناسه کاربری شما در پیام‌رسان بله:</b>\n\n"
            f"🔢 <b>آیدی عددی اختصاصی شما (Bale ID):</b>\n"
            f"<code>{user_id}</code>  (جهت کپی لمس کنید)\n\n"
            f"👤 <b>نام اکانت:</b> {html.escape(user_name)}\n"
            f"🏷️ <b>شناسه کاربری:</b> {user_handle}\n"
            f"🔰 <b>سطح دسترسی:</b> {status_badge}\n\n"
        )
        if not is_admin:
            text += (
                f"💡 <b>چگونه ادمین شوم؟</b>\n"
                f"کافیست دستور زیر را با رمز عبور مدیریت ارسال فرمایید تا دسترسی مدیر ارشد برای شما فعال شود:\n"
                f"<code>/admin_login SaghfSuperAdmin#2026!</code>\n\n"
                f"یا این شناسه عددی (<code>{user_id}</code>) را به مدیر ارشد ارائه دهید."
            )
        else:
            text += (
                "✨ <b>دسترسی مدیریتی:</b>\n"
                "شما دسترسی کامل به کنسول مدیریت دارید. با ارسال دستور <code>/admin</code> می‌توانید پنل اختصاصی را باز کنید."
            )
            
        bot.reply_to(message, text, reply_markup=_build_admin_panel_markup() if is_admin else None, parse_mode='HTML')

    # 4. Instant Super Admin Claim Command: /admin_login <password>
    @bot.message_handler(commands=['admin_login', 'login', 'auth'])
    def handle_admin_login_command(message):
        user_id = message.from_user.id
        text_parts = message.text.split(maxsplit=1) if message.text else []
        if len(text_parts) < 2:
            bot.reply_to(
                message,
                "⚠️ <b>فرمت ورود به حساب مدیریت ارشد:</b>\n\n"
                "<code>/admin_login &lt;رمز_عبور&gt;</code>\n\n"
                "📌 مثال:\n"
                "<code>/admin_login SaghfSuperAdmin#2026!</code>",
                parse_mode='HTML'
            )
            return

        password = text_parts[1].strip()
        ok, msg = claim_bale_superadmin(user_id, password)
        if ok:
            celebration = (
                f"🎉 <b>تبریک! دسترسی مدیر ارشد فعال شد</b> 👑\n\n"
                f"اکانت بله شما با شناسه <code>{user_id}</code> با موفقیت به عنوان <b>مدیر ارشد (Super Admin)</b> تایید گردید.\n\n"
                f"اکنون تمام امکانات مدیریتی، آمار دیتابیس، کراولینگ و تنظیمات سیستم در دسترس شماست."
            )
            bot.reply_to(message, celebration, reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        else:
            bot.reply_to(message, f"❌ {msg}", parse_mode='HTML')

    # 5. Super Admin & Admin Console: /admin, /panel
    @bot.message_handler(commands=['admin', 'panel'])
    def handle_admin_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"این بخش منحصراً برای <b>مدیران تاییدشده سامانه سقف</b> طراحی شده است.\n"
                f"شناسه عددی شما (<code>{user_id}</code>) در لیست مدیران ثبت نشده است.\n\n"
                f"💡 جهت ورود به عنوان مدیر ارشد کافیست دستور زیر را با رمز عبور سیستم بفرستید:\n"
                f"<code>/admin_login SaghfSuperAdmin#2026!</code>",
                parse_mode='HTML'
            )
            return

        role_title = "مدیر ارشد (Super Admin) 👑" if is_bale_super_admin(user_id) else "مدیر سیستم 🛡️"
        text = (
            f"👑 <b>کنسول هوشمند مدیریت سامانه سقف در بله</b> 👑\n\n"
            f"درود همکار گرامی، به پنل کنترل ربات خوش آمدید.\n"
            f"👤 <b>شناسه شما:</b> <code>{user_id}</code>\n"
            f"🎖️ <b>سطح دسترسی:</b> {role_title}\n\n"
            f"⚡ <b>دسترسی‌های سریع مدیریتی:</b>\n"
            f"از گزینه‌های زیر استفاده کنید یا فرامین متنی را بفرستید:\n\n"
            f"▫️ <code>/stats</code> — گزارش آمار لحظه‌ای دیتابیس، فایل‌ها و متقاضیان\n"
            f"▫️ <code>/crawl</code> — راه‌اندازی فوری تسک کراولینگ دیوار و شیپور\n"
            f"▫️ <code>/admins</code> — مشاهده و مدیریت لیست مدیران سامانه\n"
            f"▫️ <code>/add_admin &lt;آیدی_عددی&gt; [نام]</code> — افزودن ادمین جدید\n"
            f"▫️ <code>/del_admin &lt;آیدی_عددی&gt;</code> — لغو دسترسی ادمین\n"
            f"▫️ <code>/search &lt;کد_یا_نام&gt;</code> — استعلام فایل یا مشخصات کاربر"
        )
        bot.reply_to(message, text, reply_markup=_build_admin_panel_markup(), parse_mode='HTML')

    # 6. Admins list: /admins, /admin_list
    @bot.message_handler(commands=['admins', 'admin_list'])
    def handle_admins_list_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(message, "⛔ دسترسی غیرمجاز!", parse_mode='HTML')
            return
        
        store = _load_admin_store()
        admins = store.get("admins", [])
        super_admins = set(store.get("super_admins", ["7495565146"]))
        super_admins.add("7495565146")
        metadata = store.get("admin_metadata", {})

        lines = ["👥 <b>لیست مدیران مجاز سامانه سقف در پیام‌رسان بله:</b>\n"]
        for idx, aid in enumerate(admins, 1):
            meta = metadata.get(aid, {})
            title = meta.get("title") or ("مدیر ارشد" if aid in super_admins else "مدیر سیستم")
            added_at = meta.get("added_at") or meta.get("claimed_at") or "-"
            crown = "👑" if aid in super_admins else "🛡️"
            lines.append(f"{idx}. {crown} <code>{aid}</code> — <b>{html.escape(title)}</b>\n    └ ثبت: {added_at}")
        
        lines.append("\n💡 <b>فرامین سریع:</b>")
        lines.append("▫️ افزودن مدیر: <code>/add_admin &lt;آیدی&gt; [عنوان]</code>")
        lines.append("▫️ حذف مدیر: <code>/del_admin &lt;آیدی&gt;</code>")
        
        bot.reply_to(message, "\n".join(lines), reply_markup=_build_admin_panel_markup(), parse_mode='HTML')

    # 7. Add Admin: /add_admin <id> [title]
    @bot.message_handler(commands=['add_admin', 'addadmin'])
    def handle_add_admin_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(message, "⛔ دسترسی غیرمجاز!", parse_mode='HTML')
            return
            
        text_parts = message.text.split(maxsplit=2) if message.text else []
        if len(text_parts) < 2:
            bot.reply_to(
                message,
                "⚠️ <b>فرمت دستور افزودن مدیر جدید:</b>\n\n"
                "<code>/add_admin &lt;شناسه_عددی&gt; [نام یا عنوان]</code>\n\n"
                "📌 مثال:\n"
                "<code>/add_admin 123456789 مهندس احمدی</code>",
                parse_mode='HTML'
            )
            return
            
        target_id_raw = text_parts[1].strip()
        title = text_parts[2].strip() if len(text_parts) > 2 else "مدیر سیستم بله"
        
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        target_id_clean = ''.join(filter(str.isdigit, target_id_raw.translate(fa_to_en)))
        
        if not target_id_clean or len(target_id_clean) < 5:
            bot.reply_to(message, "❌ شناسه عددی بله نامعتبر است (حداقل ۵ رقم).", parse_mode='HTML')
            return
            
        ok, msg = add_bale_admin_user(target_id_clean, added_by=str(user_id))
        if ok:
            store = _load_admin_store()
            if "admin_metadata" in store and target_id_clean in store["admin_metadata"]:
                store["admin_metadata"][target_id_clean]["title"] = title
                _save_admin_store(store)
                
            bot.reply_to(
                message,
                f"✅ <b>مدیر جدید با موفقیت به بله اضافه شد!</b>\n\n"
                f"🔢 شناسه: <code>{target_id_clean}</code>\n"
                f"👤 عنوان/نام: <b>{html.escape(title)}</b>\n"
                f"👑 ثبت‌کننده: <code>{user_id}</code>\n\n"
                f"این کاربر از هم‌اکنون به پنل <code>/admin</code> در بله دسترسی دارد.",
                reply_markup=_build_admin_panel_markup(),
                parse_mode='HTML'
            )
            try:
                bot.send_message(
                    int(target_id_clean),
                    f"🎉 <b>تبریک! دسترسی مدیریت فعال شد</b>\n\n"
                    f"حساب کاربری شما توسط مدیر ارشد به عنوان <b>مدیر سامانه املاک سقف</b> در بله تایید شد.\n\n"
                    f"از این پس می‌توانید با ارسال دستور <code>/admin</code> به کنسول مدیریت ربات دسترسی پیدا نمایید.",
                    parse_mode='HTML'
                )
            except Exception:
                pass
        else:
            bot.reply_to(message, f"⚠️ {msg}", parse_mode='HTML')

    # 8. Delete Admin: /del_admin <id>
    @bot.message_handler(commands=['del_admin', 'deladmin', 'remove_admin'])
    def handle_del_admin_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(message, "⛔ دسترسی غیرمجاز!", parse_mode='HTML')
            return
            
        text_parts = message.text.split() if message.text else []
        if len(text_parts) < 2:
            bot.reply_to(
                message,
                "⚠️ <b>فرمت دستور حذف مدیر:</b>\n\n"
                "<code>/del_admin &lt;شناسه_عددی&gt;</code>\n\n"
                "📌 مثال:\n"
                "<code>/del_admin 123456789</code>",
                parse_mode='HTML'
            )
            return
            
        target_id_raw = text_parts[1].strip()
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        target_id_clean = ''.join(filter(str.isdigit, target_id_raw.translate(fa_to_en)))
        
        ok, msg = remove_bale_admin_user(target_id_clean)
        if ok:
            bot.reply_to(message, f"✅ {msg}", reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        else:
            bot.reply_to(message, f"❌ {msg}", parse_mode='HTML')

    # 9. Statistics: /stats
    @bot.message_handler(commands=['stats'])
    def handle_stats_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"مشاهده آمار سیستمی صرفاً برای حساب‌های <b>مدیران سامانه سقف</b> مجاز است.\n"
                f"شناسه شما: <code>{user_id}</code>",
                parse_mode='HTML'
            )
            return

        try:
            app = get_flask_app()
            with app.app_context():
                from database.models import Property, Client
                from crawler.crawler_manager import crawler_manager
                total_props = Property.query.count()
                sales = Property.query.filter_by(deal_type='sale').count()
                rents = Property.query.filter_by(deal_type='rent').count()
                divar_cnt = Property.query.filter_by(source='divar').count()
                sheypoor_cnt = Property.query.filter_by(source='sheypoor').count()
                direct_cnt = Property.query.filter_by(source='direct_owner').count()
                clients_cnt = Client.query.count()
                c_status = crawler_manager.get_status()
                c_running = "در حال کراولینگ 🟢" if c_status.get('is_running') else "آماده‌به‌کار (Idle) ⚪"

                report = (
                    "📊 <b>گزارش آمار جامع سامانه املاک سقف (Bale):</b>\n\n"
                    f"🏛️ <b>کل فایل‌های دیتابیس:</b> {total_props} ملک\n"
                    f"  ├ 🏷️ خرید و فروش: {sales}\n"
                    f"  └ 🔑 رهن و اجاره: {rents}\n\n"
                    f"🌐 <b>تفکیک منابع:</b>\n"
                    f"  ├ دیوار: {divar_cnt}\n"
                    f"  ├ شیپور: {sheypoor_cnt}\n"
                    f"  └ فایل مستقیم دفتر: {direct_cnt}\n\n"
                    f"👥 <b>مشتریان فعال در CRM:</b> {clients_cnt} متقاضی\n"
                    f"🕷️ <b>وضعیت انجین کراولر:</b> {c_running}\n"
                )
                bot.reply_to(message, report, reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error serving admin /stats in Bale: {e}")
            bot.reply_to(message, f"❌ خطا در استخراج آمار: {e}")

    # 10. Live Crawl: /crawl
    @bot.message_handler(commands=['crawl'])
    def handle_crawl_command(message):
        user_id = message.from_user.id
        if not is_bale_admin_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"اجرای تسک‌های کراولر صرفاً برای حساب‌های <b>مدیران سامانه سقف</b> مجاز است.\n"
                f"شناسه شما: <code>{user_id}</code>",
                parse_mode='HTML'
            )
            return

        try:
            app = get_flask_app()
            with app.app_context():
                from crawler.crawler_manager import crawler_manager
                success, msg = crawler_manager.start_crawl_task(
                    sources=['divar', 'sheypoor'],
                    categories=['buy-apartment', 'rent-apartment'],
                    limit_per_cat=6
                )
                if success:
                    bot.reply_to(
                        message,
                        f"🕷️ <b>تسک کراولینگ فوری آغاز شد:</b>\n\n"
                        f"{msg}\n\n"
                        f"فایل‌های جدید پس از پردازش در سامانه و پیام‌رسان‌ها قرار خواهند گرفت.",
                        reply_markup=_build_admin_panel_markup(),
                        parse_mode='HTML'
                    )
                else:
                    bot.reply_to(message, f"⚠️ <b>خطا در شروع کراولینگ:</b>\n{msg}", reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error triggering admin /crawl in Bale: {e}")
            bot.reply_to(message, f"❌ خطای اجرایی: {e}")

    # 11. Search & User Lookup: /search, /find, /user, /check_user
    @bot.message_handler(commands=['search', 'find', 'user', 'check_user'])
    def handle_search_command(message):
        text_parts = message.text.split(maxsplit=1) if message.text else []
        if len(text_parts) < 2:
            bot.reply_to(
                message,
                "🔍 <b>راهنمای جستجو و استعلام در سامانه سقف:</b>\n\n"
                "▫️ <b>استعلام ملک با کد فایل:</b>\n"
                "<code>/search 10001</code>\n\n"
                "▫️ <b>استعلام کاربر یا مدیر با شناسه عددی:</b>\n"
                "<code>/user 7495565146</code>\n\n"
                "▫️ <b>جستجوی کاربر با نام یا شماره:</b>\n"
                "<code>/user رضایی</code>",
                parse_mode='HTML'
            )
            return

        raw_query = text_parts[1].strip()
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        query = raw_query.translate(fa_to_en)
        user_id = message.from_user.id
        is_admin = is_bale_admin_user(user_id)

        app = get_flask_app()
        with app.app_context():
            from database.models import Property, User
            clean_digits = ''.join(filter(str.isdigit, query))

            # ۱. تطبیق با کد فایل ملکی (۱ تا ۶ رقم)
            if clean_digits and (1 <= len(clean_digits) <= 6):
                prop = Property.get_by_code(clean_digits)
                if prop:
                    from .notifier import send_property_bale_media
                    bot.send_message(message.chat.id, f"📸 در حال ارسال کارت فایل کد {prop.file_code} ({html.escape(prop.title)})...")
                    send_property_bale_media(prop, message.chat.id, bot=bot)
                    return

            # ۲. در صورتی که کاربر ادمین باشد: جستجوی جدول کاربران و ادمین‌ها
            if is_admin:
                user_match = None
                if clean_digits:
                    user_match = User.query.filter(
                        (User.bale_id == clean_digits) |
                        (User.telegram_id == clean_digits) |
                        (User.phone.like(f"%{clean_digits}%")) |
                        (User.id == clean_digits)
                    ).first()
                if not user_match:
                    user_match = User.query.filter(
                        (User.username.ilike(f"%{query}%")) |
                        (User.full_name.ilike(f"%{query}%"))
                    ).first()

                if user_match:
                    u = user_match
                    active_label = "فعال 🟢" if u.is_active else "غیرفعال 🔴"
                    role_badge = u.role_title
                    text = (
                        f"👤 <b>اطلاعات کاربر در دیتابیس سامانه سقف:</b>\n\n"
                        f"🆔 شناسه ردیف: <code>{u.id}</code>\n"
                        f"👤 نام و نام‌خانوادگی: <b>{html.escape(u.full_name)}</b>\n"
                        f"🏷️ نام کاربری: <code>{u.username}</code>\n"
                        f"🎖️ نقش: <b>{role_badge}</b>\n"
                        f"🔢 شناسه بله: <code>{u.bale_id or 'ثبت‌نشده'}</code>\n"
                        f"🔢 شناسه تلگرام: <code>{u.telegram_id or 'ثبت‌نشده'}</code>\n"
                        f"📞 شماره همراه: <code>{u.phone or 'ثبت‌نشده'}</code>\n"
                        f"⚡ وضعیت حساب: {active_label}\n"
                        f"📅 تاریخ ثبت: {u.created_at.strftime('%Y/%m/%d') if u.created_at else '-'}\n"
                    )
                    if u.notes:
                        text += f"📝 یادداشت: {html.escape(u.notes)}\n"

                    web_url = "http://127.0.0.1:5000"
                    markup = InlineKeyboardMarkup()
                    markup.add(
                        InlineKeyboardButton("✏️ مدیریت در پنل وب (CRUD)", url=f"{web_url}/admin/users")
                    )
                    bot.reply_to(message, text, reply_markup=markup, parse_mode='HTML')
                    return

                # بررسی مستقیم در فایل bale_admins.json
                store = _load_admin_store()
                if clean_digits in store.get("admins", []):
                    meta = store.get("admin_metadata", {}).get(clean_digits, {})
                    title = meta.get("title", "مدیر سیستم بله")
                    added_at = meta.get("added_at") or meta.get("claimed_at") or "-"
                    text = (
                        f"🛡️ <b>مدیر بله تاییدشده:</b>\n\n"
                        f"🔢 شناسه عددی: <code>{clean_digits}</code>\n"
                        f"👤 عنوان: <b>{html.escape(title)}</b>\n"
                        f"📅 ثبت در سامانه: {added_at}\n\n"
                        "این کاربر دارای دسترسی مجاز به ربات بله است."
                    )
                    bot.reply_to(message, text, parse_mode='HTML')
                    return

            # ۳. نتیجه‌ای یافت نشد
            bot.reply_to(
                message,
                f"❌ نتیجه‌ای برای استعلام «<code>{html.escape(raw_query)}</code>» یافت نشد.\n\n"
                "💡 راهنما:\n"
                "• استعلام فایل ملکی: ارسال کد فایل (مثلاً <code>10001</code>)\n"
                "• استعلام کاربر یا ادمین: ارسال شناسه عددی یا نام کاربری.",
                parse_mode='HTML'
            )

    # 12. Interactive Filter Wizard Commands: /filter, /wizard
    @bot.message_handler(commands=['filter', 'wizard'])
    def handle_filter_command(message):
        chat_id = message.chat.id
        wizard_sessions[chat_id] = {'step': 1}
        text = (
            "🎯 <b>ویزارد فیلترینگ و استخراج هدفمند املاک سقف (گام ۱ از ۵):</b>\n\n"
            "به دستیار استخراج مستقیم سقف در بله خوش آمدید. بدون نیاز به مراجعه به وب‌اپ، فیلترهای مد نظر خود را تعیین فرمایید تا کراولر در لحظه از دیوار استخراج نماید.\n\n"
            "لطفاً <b>نوع معامله</b> را مشخص فرمایید:"
        )
        bot.send_message(chat_id, text, reply_markup=_build_wizard_step1_markup(), parse_mode='HTML')

    # 13. Cancel command: /cancel
    @bot.message_handler(commands=['cancel'])
    def handle_cancel_command(message):
        if message.chat.id in wizard_sessions:
            del wizard_sessions[message.chat.id]
        bot.reply_to(message, "✅ عملیات جاری لغو گردید. جهت شروع مجدد /start را ارسال فرمایید.", reply_markup=_build_start_keyboard(message.from_user.id))

    # ==========================================
    # Callback Query Handlers (Unified Prefix Support)
    # ==========================================

    # 1. Passwordless Login Callbacks: (confirm / reject)
    @bot.callback_query_handler(func=lambda call: call.data and (
        call.data.startswith('bale_confirm_') or call.data.startswith('confirm_') or call.data.startswith('tg_confirm_')
    ))
    def handle_auth_confirm_callback(call):
        try:
            token = call.data.replace('bale_confirm_', '').replace('tg_confirm_', '').replace('confirm_', '').strip()
            app = get_flask_app()
            with app.app_context():
                from database.models import AuthSession, User
                from database.db import db
                import secrets

                auth_sess = AuthSession.query.filter_by(session_token=token).first()
                if not auth_sess or auth_sess.is_expired:
                    bot.answer_callback_query(call.id, "❌ این نشست ورود منقضی شده است.", show_alert=True)
                    return

                user_bale_id = str(call.from_user.id)
                user_name = call.from_user.first_name or "کاربر بله"
                phone = auth_sess.phone

                user = None
                if phone:
                    user = User.query.filter_by(phone=phone).first()
                if not user:
                    user = User.query.filter_by(bale_id=user_bale_id).first()

                if not user:
                    base_uname = f"user_{phone}" if phone else f"bale_{user_bale_id}"
                    existing = User.query.filter_by(username=base_uname).first()
                    if existing:
                        base_uname = f"{base_uname}_{secrets.token_hex(2)}"

                    user = User(
                        username=base_uname,
                        full_name=user_name,
                        phone=phone or '',
                        bale_id=user_bale_id,
                        role='user',
                        is_active=True,
                        notes='ثبت‌نام خودکار از طریق ربات بله'
                    )
                    user.set_password(secrets.token_urlsafe(32))
                    db.session.add(user)
                    db.session.flush()
                else:
                    if not user.bale_id:
                        user.bale_id = user_bale_id
                    if phone and not user.phone:
                        user.phone = phone

                user.last_login = datetime.utcnow()
                auth_sess.status = 'confirmed'
                auth_sess.user_id = user.id
                auth_sess.messenger_user_id = user_bale_id
                auth_sess.messenger_user_name = user_name
                auth_sess.confirmed_at = datetime.utcnow()
                db.session.commit()

                bot.answer_callback_query(call.id, "✅ ورود شما به سامانه سقف با موفقیت تایید شد.")
                try:
                    bot.edit_message_text(
                        "⚜️ <b>سامانه هوشمند فایلینگ سقف</b> ⚜️\n\n"
                        f"✅ <b>ورود با موفقیت تایید شد!</b>\n\n"
                        f"همراه گرامی <b>{html.escape(user_name)}</b>، نشست شما در وب‌سایت فعال گردید.\n"
                        "هم‌اکنون می‌توانید به مرورگر خود بازگردید.",
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        parse_mode='HTML'
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error handling auth confirm callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data and (
        call.data.startswith('bale_reject_') or call.data.startswith('reject_') or call.data.startswith('tg_reject_')
    ))
    def handle_auth_reject_callback(call):
        try:
            token = call.data.replace('bale_reject_', '').replace('tg_reject_', '').replace('reject_', '').strip()
            app = get_flask_app()
            with app.app_context():
                from database.models import AuthSession
                from database.db import db
                auth_sess = AuthSession.query.filter_by(session_token=token).first()
                if auth_sess:
                    auth_sess.status = 'rejected'
                    db.session.commit()
            bot.answer_callback_query(call.id, "❌ درخواست ورود لغو شد.")
            try:
                bot.edit_message_text(
                    "❌ <b>درخواست ورود به سامانه سقف لغو گردید.</b>",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error handling auth reject callback in Bale: {e}")

    # 2. Admin Quick Action Callbacks: (adm_pub / adm_sendmatch)
    @bot.callback_query_handler(func=lambda call: call.data and (call.data.startswith('bale_adm_pub_') or call.data.startswith('adm_pub_')))
    def handle_admin_publish_callback(call):
        try:
            prop_id = int(call.data.replace('bale_adm_pub_', '').replace('adm_pub_', '').strip())
            app = get_flask_app()
            with app.app_context():
                from database.models import Property
                from database.db import db
                prop = Property.query.get(prop_id)
                if prop:
                    prop.status = 'verified'
                    prop.updated_at = datetime.utcnow()
                    db.session.commit()
                    bot.answer_callback_query(call.id, f"✅ ملک کد {prop.file_code} با موفقیت تایید و در سامانه منتشر شد.", show_alert=True)
                    bot.send_message(call.message.chat.id, f"🎉 <b>فایل ملکی کد {prop.file_code} توسط مدیر تایید و منتشر گردید.</b>", parse_mode='HTML')
                else:
                    bot.answer_callback_query(call.id, "❌ فایل ملکی یافت نشد.", show_alert=True)
        except Exception as e:
            logger.error(f"Error publishing property via Bale callback: {e}")
            bot.answer_callback_query(call.id, "خطا در پردازش درخواست.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data and (call.data.startswith('bale_adm_sendmatch_') or call.data.startswith('adm_sendmatch_')))
    def handle_admin_send_matches_callback(call):
        try:
            lead_id = int(call.data.replace('bale_adm_sendmatch_', '').replace('adm_sendmatch_', '').strip())
            app = get_flask_app()
            with app.app_context():
                from database.models import CustomerLead
                from services.nurturing_engine import nurturing_engine
                lead = CustomerLead.query.get(lead_id)
                if lead:
                    bot.answer_callback_query(call.id, "⏳ در حال تطبیق و ارسال فایل‌های برتر...")
                    dispatches = nurturing_engine.handle_lead_matching_and_dispatch(lead)
                    count = len(dispatches)
                    bot.send_message(
                        call.message.chat.id,
                        f"🎯 <b>تعداد {count} فایل ملکی منطبق با موفقیت به متقاضی ({lead.phone_number}) ارسال شد.</b>",
                        parse_mode='HTML'
                    )
                else:
                    bot.answer_callback_query(call.id, "❌ متقاضی یافت نشد.", show_alert=True)
        except Exception as e:
            logger.error(f"Error dispatching matches via Bale callback: {e}")
            bot.answer_callback_query(call.id, "خطا در ارسال فایل‌ها.", show_alert=True)

    # 3. Informational & Menu Callbacks
    @bot.callback_query_handler(func=lambda call: call.data in ['btn_code_info', 'bale_btn_code_info'])
    def handle_code_info_callback(call):
        try:
            bot.answer_callback_query(call.id)
            text = (
                "🔢 <b>راهنمای استعلام و پرزنت تصاویر با کد فایل:</b>\n\n"
                "هر فایل در وب‌اپ سقف دارای یک <b>کد ۵ رقمی اختصاصی</b> (مانند <code>10001</code>) است.\n\n"
                "📌 هر زمان که در حال صحبت تلفنی یا پرزنت به مشتری بودید، کافیست <b>کد فایل را در همین چت بفرستید</b> "
                "تا تمام اطلاعات ملک به همراه مشخصات کامل و لینک مستقیم، به صورت یک کارت تصویری برای شما یا مشتری فوروارد شود."
            )
            bot.send_message(call.message.chat.id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling code info callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['btn_search_info', 'bale_btn_search_info'])
    def handle_search_info_callback(call):
        try:
            bot.answer_callback_query(call.id)
            info_text = (
                "🔍 <b>استعلام و فیلتر فایل‌های اختصاصی سقف:</b>\n\n"
                "برای جستجوی پیشرفته بر اساس منطقه (پونک، جنت‌آباد، صادقیه، سعادت‌آباد و...)، متراژ، قیمت "
                "و بودجه دلخواه خود، می‌توانید مستقیماً از ویزارد استخراج <code>/filter</code> یا داشبورد وب سامانه اقدام کنید.\n\n"
                "🏢 کلیه فایل‌ها دارای راستی‌آزمایی مستمر و استعلام بلادرنگ می‌باشند."
            )
            bot.send_message(call.message.chat.id, info_text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling search callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['btn_myid', 'bale_btn_myid'])
    def handle_btn_myid_callback(call):
        try:
            bot.answer_callback_query(call.id)
            user_id = call.from_user.id
            user_name = call.from_user.first_name or "کاربر بله"
            user_handle = f"@{call.from_user.username}" if call.from_user.username else "ندارد"
            is_admin = is_bale_admin_user(user_id)
            is_super = is_bale_super_admin(user_id)
            
            if is_super:
                status_badge = "👑 <b>مدیر ارشد (Super Admin)</b>"
            elif is_admin:
                status_badge = "🛡️ <b>مدیر تاییدشده سیستم (Admin)</b>"
            else:
                status_badge = "👤 <b>کاربر عادی</b>"

            text = (
                f"🆔 <b>مشخصات و شناسه کاربری شما در پیام‌رسان بله:</b>\n\n"
                f"🔢 <b>آیدی عددی اختصاصی شما (Bale ID):</b>\n"
                f"<code>{user_id}</code>  (جهت کپی لمس کنید)\n\n"
                f"👤 <b>نام اکانت:</b> {html.escape(user_name)}\n"
                f"🏷️ <b>شناسه کاربری:</b> {user_handle}\n"
                f"🔰 <b>سطح دسترسی:</b> {status_badge}\n\n"
            )
            if not is_admin:
                text += (
                    f"💡 <b>چگونه ادمین شوم؟</b>\n"
                    f"جهت فعال‌سازی آنی دسترسی مدیر ارشد، دستور زیر را با رمز عبور ارسال فرمایید:\n"
                    f"<code>/admin_login SaghfSuperAdmin#2026!</code>"
                )
            else:
                text += (
                    "✨ <b>دسترسی مدیریتی:</b>\n"
                    "شما دسترسی کامل به کنسول مدیریت دارید. با ارسال دستور <code>/admin</code> یا فشردن دکمه زیر می‌توانید پنل را باز کنید."
                )
            markup = _build_admin_panel_markup() if is_admin else None
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling btn_myid callback in Bale: {e}")

    # 4. Admin Menu Callbacks
    @bot.callback_query_handler(func=lambda call: call.data in ['admin_cb_menu', 'admin_cb_refresh', 'bale_admin_cb_menu'])
    def handle_admin_menu_callback(call):
        try:
            user_id = call.from_user.id
            if not is_bale_admin_user(user_id):
                bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز! شما مدیر سامانه نیستید.", show_alert=True)
                return
            bot.answer_callback_query(call.id, "در حال بارگذاری پنل...")
            role_title = "مدیر ارشد (Super Admin) 👑" if is_bale_super_admin(user_id) else "مدیر سیستم 🛡️"
            text = (
                f"👑 <b>کنسول هوشمند مدیریت سامانه سقف در بله</b> 👑\n\n"
                f"درود همکار گرامی، به پنل کنترل ربات خوش آمدید.\n"
                f"👤 <b>شناسه شما:</b> <code>{user_id}</code>\n"
                f"🎖️ <b>سطح دسترسی:</b> {role_title}\n\n"
                f"⚡ <b>دسترسی‌های سریع مدیریتی:</b>\n"
                f"▫️ <code>/stats</code> — گزارش آمار فایل‌ها و مشتریان\n"
                f"▫️ <code>/crawl</code> — اجرای فوری کراولر\n"
                f"▫️ <code>/admins</code> — مشاهده مدیران فعال\n"
                f"▫️ <code>/add_admin &lt;آیدی&gt; [نام]</code> — اضافه کردن ادمین\n"
                f"▫️ <code>/del_admin &lt;آیدی&gt;</code> — حذف ادمین"
            )
            bot.send_message(call.message.chat.id, text, reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling admin menu callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['admin_cb_stats', 'bale_admin_cb_stats'])
    def handle_admin_stats_callback(call):
        try:
            user_id = call.from_user.id
            if not is_bale_admin_user(user_id):
                bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز!", show_alert=True)
                return
            bot.answer_callback_query(call.id, "در حال استخراج آمار دیتابیس...")
            handle_stats_command(call.message)
        except Exception as e:
            logger.error(f"Error handling admin stats callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['admin_cb_crawl', 'bale_admin_cb_crawl'])
    def handle_admin_crawl_callback(call):
        try:
            user_id = call.from_user.id
            if not is_bale_admin_user(user_id):
                bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز!", show_alert=True)
                return
            bot.answer_callback_query(call.id, "در حال راه‌اندازی کراولر...")
            handle_crawl_command(call.message)
        except Exception as e:
            logger.error(f"Error handling admin crawl callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['admin_cb_list', 'bale_admin_cb_list'])
    def handle_admin_list_callback(call):
        try:
            user_id = call.from_user.id
            if not is_bale_admin_user(user_id):
                bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            handle_admins_list_command(call.message)
        except Exception as e:
            logger.error(f"Error handling admin list callback in Bale: {e}")

    @bot.callback_query_handler(func=lambda call: call.data in ['admin_cb_add_guide', 'bale_admin_cb_add_guide'])
    def handle_admin_add_guide_callback(call):
        try:
            user_id = call.from_user.id
            if not is_bale_admin_user(user_id):
                bot.answer_callback_query(call.id, "⛔ دسترسی غیرمجاز!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            guide = (
                "➕ <b>راهنمای افزودن مدیر جدید در بله:</b>\n\n"
                "۱. ابتدا از فرد مورد نظر بخواهید به این بات پیام دهد یا دستور <code>/id</code> را بفرستد تا شناسه عددی بله خود را دریافت کند.\n\n"
                "۲. سپس شناسه عددی او را با فرمت زیر در چت ارسال فرمایید:\n"
                "<code>/add_admin &lt;آیدی_عددی&gt; [نام یا نقش]</code>\n\n"
                "📌 <b>مثال:</b>\n"
                "<code>/add_admin 123456789 مهندس سلیمانی</code>\n\n"
                "به محض ارسال، دسترسی او فوراً فعال شده و پیام تایید برای وی ارسال خواهد شد."
            )
            bot.send_message(call.message.chat.id, guide, reply_markup=_build_admin_panel_markup(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling admin add guide callback in Bale: {e}")

    # 5. Latest Sales & Rents Callbacks
    @bot.callback_query_handler(func=lambda call: call.data in ['btn_latest_sale', 'btn_latest_rent', 'bale_btn_latest_sale', 'bale_btn_latest_rent'])
    def handle_latest_properties_callback(call):
        deal_type = 'sale' if ('sale' in call.data) else 'rent'
        deal_title = 'فروش' if deal_type == 'sale' else 'رهن و اجاره'
        
        try:
            bot.answer_callback_query(call.id, text=f"در حال دریافت ۵ فایل آخر {deal_title}...")
        except Exception:
            pass

        try:
            app = get_flask_app()
            with app.app_context():
                from database.models import Property
                props = (
                    Property.query.filter_by(deal_type=deal_type)
                    .filter(Property.status.notin_(['archived', 'sold']))
                    .order_by(Property.created_at.desc())
                    .limit(5)
                    .all()
                )

                if not props:
                    bot.send_message(
                        call.message.chat.id,
                        f"⚠️ در حال حاضر هیچ فایل فعالی در دسته‌بندی {deal_title} یافت نشد.",
                        parse_mode='HTML'
                    )
                    return

                header = f"📋 <b>۵ فایل اخیر {deal_title} در سامانه سقف:</b>\n" + ("—" * 28)
                bot.send_message(call.message.chat.id, header, parse_mode='HTML')

                for p in props:
                    msg = _format_compact_property(p)
                    markup = InlineKeyboardMarkup()
                    target_url = p.source_url or f"http://127.0.0.1:5000/properties/{p.id}"
                    markup.add(InlineKeyboardButton("🔗 لینک آگهی", url=target_url))
                    
                    bot.send_message(
                        call.message.chat.id,
                        msg,
                        reply_markup=markup,
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )

        except Exception as e:
            logger.error(f"Error serving properties callback in Bale: {e}")
            try:
                bot.send_message(call.message.chat.id, "خطا در واکشی فایل‌ها. لطفاً دوباره تلاش نمایید.")
            except Exception:
                pass

    # =========================================================================
    # 6. Interactive Extraction Wizard (5-Step State Machine)
    # =========================================================================

    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_start', 'bale_wiz_start'])
    def handle_wizard_start(call):
        chat_id = call.message.chat.id
        wizard_sessions[chat_id] = {'step': 1}
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = (
            "🎯 <b>ویزارد فیلترینگ و استخراج هدفمند املاک سقف (گام ۱ از ۵):</b>\n\n"
            "لطفاً <b>نوع معامله</b> را انتخاب فرمایید:"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=_build_wizard_step1_markup(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step1_markup(), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_deal_sale', 'wiz_deal_rent', 'bale_wiz_deal_sale', 'bale_wiz_deal_rent'])
    def handle_wizard_step1(call):
        chat_id = call.message.chat.id
        deal_type = 'sale' if 'sale' in call.data else 'rent'
        session = wizard_sessions.setdefault(chat_id, {})
        session['deal_type'] = deal_type
        session['step'] = 2
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        deal_title = '🏷️ خرید و فروش' if deal_type == 'sale' else '🔑 رهن و اجاره'
        text = (
            f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۲ از ۵):</b>\n\n"
            f"نوع معامله: <b>{deal_title}</b>\n\n"
            f"لطفاً <b>نوع کاربری ملک</b> را تعیین فرمایید:"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=_build_wizard_step2_markup(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step2_markup(), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data in [
        'wiz_type_apartment', 'wiz_type_villa', 'wiz_type_commercial',
        'bale_wiz_type_apartment', 'bale_wiz_type_villa', 'bale_wiz_type_commercial'
    ])
    def handle_wizard_step2(call):
        chat_id = call.message.chat.id
        prop_map = {
            'wiz_type_apartment': ('apartment', '🏢 آپارتمان مسکونی'),
            'wiz_type_villa': ('villa', '🏡 ویلایی / کلنگی'),
            'wiz_type_commercial': ('commercial', '🏬 اداری / تجاری'),
            'bale_wiz_type_apartment': ('apartment', '🏢 آپارتمان مسکونی'),
            'bale_wiz_type_villa': ('villa', '🏡 ویلایی / کلنگی'),
            'bale_wiz_type_commercial': ('commercial', '🏬 اداری / تجاری')
        }
        ptype, ptitle = prop_map.get(call.data, ('apartment', '🏢 آپارتمان'))
        session = wizard_sessions.setdefault(chat_id, {})
        session['prop_type'] = ptype
        session['prop_title'] = ptitle
        session['step'] = 3
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        deal_title = '🏷️ خرید و فروش' if session.get('deal_type') == 'sale' else '🔑 رهن و اجاره'
        text = (
            f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۳ از ۵):</b>\n\n"
            f"معامله: <b>{deal_title}</b> | کاربری: <b>{ptitle}</b>\n\n"
            f"لطفاً <b>منطقه یا محله</b> مورد نظر را از گزینه‌های زیر انتخاب کنید، یا دکمه «✍️ تایپ نام محله» را لمس نمایید:"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=_build_wizard_step3_markup(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step3_markup(), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_dist_') or call.data.startswith('bale_wiz_dist_'))
    def handle_wizard_step3(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.setdefault(chat_id, {})
        
        if 'custom' in call.data:
            session['awaiting_custom_district'] = True
            try:
                bot.answer_callback_query(call.id)
            except Exception:
                pass
            text = (
                "✍️ <b>ورود دستی نام محله / منطقه:</b>\n\n"
                "لطفاً نام محله مورد نظر خود را در همین چت تایپ و ارسال فرمایید.\n"
                "مثال‌ها: <code>فردوس</code>، <code>کاشانی</code>، <code>شاهین جنوبی</code>، <code>سازمان برنامه</code>، <code>سعادت آباد</code> و..."
            )
            bot.send_message(chat_id, text, parse_mode='HTML')
            return

        district = call.data.replace('bale_wiz_dist_', '').replace('wiz_dist_', '').strip()
        session['district'] = district
        session['awaiting_custom_district'] = False
        session['step'] = 4
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        deal_type = session.get('deal_type', 'sale')
        text = (
            f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۴ از ۵):</b>\n\n"
            f"📍 منطقه انتخابی: <b>{district}</b>\n\n"
            f"لطفاً <b>بازه متراژ و بودجه</b> مد نظر خود را انتخاب نمایید:"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=_build_wizard_step4_markup(deal_type), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step4_markup(deal_type), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_bud_') or call.data.startswith('bale_wiz_bud_'))
    def handle_wizard_step4(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.setdefault(chat_id, {})
        key = call.data.replace('bale_wiz_bud_', 'wiz_bud_')

        budgets_config = {
            'wiz_bud_s1': {'min_area': 0, 'max_area': 80, 'min_price': 0, 'max_price': 6_000_000_000, 'desc': 'متراژ تا ۸۰ م | بودجه تا ۶ میلیارد'},
            'wiz_bud_s2': {'min_area': 80, 'max_area': 110, 'min_price': 6_000_000_000, 'max_price': 10_000_000_000, 'desc': 'متراژ ۸۰ تا ۱۱۰ م | ۶ تا ۱۰ میلیارد'},
            'wiz_bud_s3': {'min_area': 110, 'max_area': 150, 'min_price': 10_000_000_000, 'max_price': 16_000_000_000, 'desc': 'متراژ ۱۱۰ تا ۱۵۰ م | ۱۰ تا ۱۶ میلیارد'},
            'wiz_bud_s4': {'min_area': 150, 'max_area': None, 'min_price': 16_000_000_000, 'max_price': None, 'desc': 'متراژ ۱۵۰+ م | ۱۶+ میلیارد'},
            'wiz_bud_r1': {'min_area': 0, 'max_area': None, 'max_deposit': 500_000_000, 'max_rent': 15_000_000, 'desc': 'ودیعه تا ۵۰۰ م | اجاره تا ۱۵ م'},
            'wiz_bud_r2': {'min_area': 0, 'max_area': None, 'min_deposit': 500_000_000, 'max_deposit': 1_000_000_000, 'max_rent': 30_000_000, 'desc': 'ودیعه ۵۰۰ تا ۱ م | اجاره ۱۵ تا ۳۰ م'},
            'wiz_bud_r3': {'min_area': 0, 'max_area': None, 'min_deposit': 1_000_000_000, 'max_deposit': 2_000_000_000, 'max_rent': 50_000_000, 'desc': 'ودیعه ۱ تا ۲ م | اجاره ۳۰ تا ۵۰ م'},
            'wiz_bud_r4': {'min_area': 0, 'max_area': None, 'min_deposit': 1_500_000_000, 'max_deposit': 3_000_000_000, 'max_rent': 1, 'desc': 'رهن کامل (۱.۵ تا ۳ میلیارد)'},
            'wiz_bud_any': {'desc': 'بدون محدودیت بودجه و متراژ'}
        }
        b_info = budgets_config.get(key, {'desc': 'نامحدود'})
        session.update(b_info)
        session['budget_desc'] = b_info.get('desc', 'نامحدود')
        session['step'] = 5

        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        deal_title = '🏷️ خرید و فروش' if session.get('deal_type') == 'sale' else '🔑 رهن و اجاره'
        prop_title = session.get('prop_title', '🏢 آپارتمان')
        district = session.get('district', 'تهران')
        budget_desc = session.get('budget_desc', 'نامحدود')

        text = (
            "🎯 <b>ویزارد فیلترینگ و استخراج (گام ۵ از ۵ - تایید نهایی):</b>\n\n"
            "📋 <b>خلاصه شرایط استخراج اختصاصی شما:</b>\n"
            f"• 🏷️ نوع معامله: <b>{deal_title}</b>\n"
            f"• 🏢 نوع کاربری: <b>{prop_title}</b>\n"
            f"• 📍 منطقه/محله: <b>{district}</b>\n"
            f"• 💰 بازه بودجه و متراژ: <b>{budget_desc}</b>\n\n"
            "آیا مایلید کراولر بلادرنگ سقف، این فایل‌ها را مستقیماً از دیوار استخراج کرده و برای شما ارسال کند؟"
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=_build_wizard_step5_markup(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step5_markup(), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_back_') or call.data.startswith('bale_wiz_back_'))
    def handle_wizard_back(call):
        chat_id = call.message.chat.id
        step = call.data.replace('bale_wiz_back_', '').replace('wiz_back_', '')
        session = wizard_sessions.setdefault(chat_id, {})
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        if step == '1':
            handle_wizard_start(call)
        elif step == '2':
            deal_type = session.get('deal_type', 'sale')
            call.data = f"wiz_deal_{deal_type}"
            handle_wizard_step1(call)
        elif step == '3':
            prop_type = session.get('prop_type', 'apartment')
            call.data = f"wiz_type_{prop_type}"
            handle_wizard_step2(call)

    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_cancel', 'bale_wiz_cancel'])
    def handle_wizard_cancel(call):
        chat_id = call.message.chat.id
        wizard_sessions.pop(chat_id, None)
        try:
            bot.answer_callback_query(call.id, text="ویزارد لغو شد.")
        except Exception:
            pass
        try:
            bot.edit_message_text("❌ <b>فرآیند استخراج هدفمند لغو گردید.</b>\n\nجهت شروع مجدد، دستور /start را ارسال فرمایید.", chat_id, call.message.message_id, reply_markup=_build_start_keyboard(), parse_mode='HTML')
        except Exception:
            bot.send_message(chat_id, "❌ <b>فرآیند استخراج هدفمند لغو گردید.</b>", reply_markup=_build_start_keyboard(), parse_mode='HTML')

    # Wizard Execution: Live scraping, filtering, scoring and sending
    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_exec', 'bale_wiz_exec'])
    def handle_wizard_execute(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.get(chat_id)
        if not session:
            try:
                bot.answer_callback_query(call.id, text="⚠️ نشست منقضی شده است.")
            except Exception:
                pass
            bot.send_message(chat_id, "⚠️ نشست فیلترینگ منقضی شده است. لطفاً مجدداً دکمه «🎯 فیلتر و استخراج جدید» را بزنید.", reply_markup=_build_start_keyboard())
            return

        try:
            bot.answer_callback_query(call.id, text="🚀 در حال استخراج و تحلیل...")
        except Exception:
            pass

        deal_type = session.get('deal_type', 'sale')
        district = session.get('district', '')
        district_clean = district if district and district != 'منطقه ۵' else None

        searching_msg = bot.send_message(
            chat_id,
            f"⏳ <b>در حال استخراج و تحلیل فایل‌های متناظر از دیوار و شیپور...</b>\n\n"
            f"📍 منطقه: <b>{district or 'تهران'}</b> | معامله: <b>{'خرید و فروش' if deal_type == 'sale' else 'رهن و اجاره'}</b>\n"
            f"ربات در حال اتصال به سرورهای مبدأ با فینگرپرینت امن است. لطفاً چند لحظه شکیبا باشید...",
            parse_mode='HTML'
        )

        app = get_flask_app()
        with app.app_context():
            from database.models import Property, Owner, db
            from crawler.crawler_manager import crawler_manager
            from crawler.owner_filter import OwnerFilter
            from data.tehran_districts import get_divar_slug_for_district
            from .notifier import send_property_bale_media

            # ۱. جستجو در دیتابیس با فیلترهای سخت‌گیرانه اصالت
            query = Property.query.filter(Property.status.notin_(['archived', 'sold']))

            # فیلتر قطعی حذف هرگونه آگهی املاکی یا واسطه
            for forbidden in ['املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس']:
                query = query.filter(
                    Property.title.notilike(f'%{forbidden}%'),
                    Property.description.notilike(f'%{forbidden}%')
                )

            # فیلتر سخت‌گیرانه حذف هرگونه آگهی همخونه، هم‌اتاقی و پانسیون
            for sh_kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS:
                query = query.filter(
                    Property.title.notilike(f'%{sh_kw}%'),
                    Property.description.notilike(f'%{sh_kw}%')
                )

            if deal_type and deal_type != 'all':
                query = query.filter(Property.deal_type == deal_type)
            prop_type = session.get('prop_type')
            if prop_type and prop_type != 'all':
                query = query.filter(Property.property_type == prop_type)
            if district_clean:
                query = query.filter(Property.district.contains(district_clean))

            if session.get('min_price'): query = query.filter(Property.total_price >= session['min_price'])
            if session.get('max_price'): query = query.filter(Property.total_price <= session['max_price'])
            if session.get('min_deposit'): query = query.filter(Property.deposit >= session['min_deposit'])
            if session.get('max_deposit'): query = query.filter(Property.deposit <= session['max_deposit'])
            if session.get('min_rent'): query = query.filter(Property.monthly_rent >= session['min_rent'])
            if session.get('max_rent'): query = query.filter(Property.monthly_rent <= session['max_rent'])
            if session.get('min_area'): query = query.filter(Property.area >= session['min_area'])
            if session.get('max_area'): query = query.filter(Property.area <= session['max_area'])

            matches = query.order_by(Property.created_at.desc()).limit(50).all()

            # ۲. اگر تعداد فایل‌های موجود کمتر از ۵ تا بود، استخراج عمیق زنده دیوار
            if len(matches) < 5:
                if deal_type == 'sale':
                    if prop_type == 'villa':
                        cat_key = 'buy-villa'
                    elif prop_type == 'commercial':
                        cat_key = 'commercial-sell'
                    else:
                        cat_key = 'buy-apartment'
                else:
                    if prop_type == 'commercial':
                        cat_key = 'commercial-rent'
                    else:
                        cat_key = 'rent-apartment'

                divar_slug = get_divar_slug_for_district(district_clean) if district_clean else None
                districts_param = [divar_slug] if divar_slug else ([district_clean] if district_clean else None)

                try:
                    def _save_crawled_item(item):
                        try:
                            if not item.is_personal_owner:
                                return
                            existing = Property.query.filter_by(source_id=item.source_id).first()
                            if existing:
                                return
                            owner = None
                            if item.owner_info and item.owner_info.phone:
                                owner = Owner.query.filter_by(phone_number=item.owner_info.phone).first()
                                if not owner:
                                    owner = Owner(full_name=item.owner_info.name, phone_number=item.owner_info.phone)
                                    db.session.add(owner)
                                    db.session.flush()
                            prop = Property(
                                source=item.source,
                                source_id=item.source_id,
                                source_url=item.source_url,
                                title=item.title,
                                deal_type=item.deal_type,
                                property_type=item.property_type,
                                city=item.city,
                                district=item.district,
                                address=item.address,
                                total_price=item.total_price,
                                meter_price=item.meter_price,
                                deposit=item.deposit,
                                monthly_rent=item.monthly_rent,
                                area=item.area,
                                rooms=item.rooms,
                                floor=item.floor,
                                build_year=item.build_year or 1401,
                                has_elevator=item.has_elevator,
                                has_parking=item.has_parking,
                                has_warehouse=item.has_warehouse,
                                has_balcony=item.has_balcony,
                                description=item.description,
                                status=item.status,
                                score=item.score,
                                is_personal_owner=True,
                                owner_id=owner.id if owner else None
                            )
                            prop.features = item.features
                            prop.images = item.images
                            db.session.add(prop)
                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                    crawler_manager.divar_crawler.fetch_listings(
                        category_key=cat_key,
                        limit=35,
                        query=district_clean,
                        districts=districts_param,
                        min_price=session.get('min_price'),
                        max_price=session.get('max_price'),
                        min_deposit=session.get('min_deposit'),
                        max_deposit=session.get('max_deposit'),
                        min_rent=session.get('min_rent'),
                        max_rent=session.get('max_rent'),
                        min_area=session.get('min_area'),
                        max_area=session.get('max_area'),
                        property_type=prop_type if prop_type != 'all' else None,
                        max_pages=15,
                        on_item_found=_save_crawled_item
                    )
                    matches = query.order_by(Property.created_at.desc()).limit(50).all()
                except Exception as err:
                    logger.warning(f"Bale Wizard live crawl error: {err}")

            # ۳. موتور امتیازدهی و رتبه‌بندی بر اساس بیشترین تطابق
            from services.scoring_service import PropertyScorer
            scoring_criteria = {
                'deal_type': deal_type,
                'district': district_clean,
                'min_price': session.get('min_price'),
                'max_price': session.get('max_price'),
                'min_deposit': session.get('min_deposit'),
                'max_deposit': session.get('max_deposit'),
                'min_rent': session.get('min_rent'),
                'max_rent': session.get('max_rent'),
                'min_area': session.get('min_area'),
                'max_area': session.get('max_area')
            }
            ranked_matches = PropertyScorer.sort_properties(matches, scoring_criteria)
            top_matches = ranked_matches[:8]

            # ۴. ارسال نتایج برتر به چت بله
            if not top_matches:
                bot.send_message(
                    chat_id,
                    f"⚠️ <b>هیچ آگهی متناظری یافت نشد</b>\n\n"
                    f"در حال حاضر در منطقه <b>{district or 'تهران'}</b> فایلی منطبق با شروط انتخابی شما در دیوار موجود نیست.\n"
                    f"می‌توانید با دکمه زیر شروط منعطف‌تری تعیین نمایید:",
                    reply_markup=_build_start_keyboard(),
                    parse_mode='HTML'
                )
            else:
                bot.send_message(
                    chat_id,
                    f"🎯 <b>تعداد {len(top_matches)} فایل برتر (رتبه‌بندی‌شده از بیشترین به کمترین تطابق) در منطقه {district or 'تهران'}:</b>\n" + ("—" * 28),
                    parse_mode='HTML'
                )
                for p in top_matches:
                    try:
                        send_property_bale_media(p, chat_id=chat_id, bot=bot)
                    except Exception as pe:
                        logger.error(f"Error sending property to Bale user: {pe}")

                bot.send_message(
                    chat_id,
                    "✨ <b>استخراج و جستجوی فایل‌ها تکمیل شد.</b>\n\n"
                    "💡 جهت دریافت سریع اطلاعات هر فایل در آینده، کافیست <b>کد ۵ رقمی</b> آن (مانند <code>10001</code>) را در همین چت بفرستید.",
                    reply_markup=_build_start_keyboard(),
                    parse_mode='HTML'
                )

        wizard_sessions.pop(chat_id, None)

    # ==========================================
    # 7. Text Messages Handler (Numeric Search, Custom District & NLP CRM)
    # ==========================================
    @bot.message_handler(content_types=['text'])
    def handle_fallback_text(message):
        chat_id = message.chat.id
        raw_text = (message.text or '').strip()
        if not raw_text or raw_text.startswith('/'):
            return

        # ۱. ورود دستی نام محله در مرحله ۳ ویزارد
        session = wizard_sessions.get(chat_id)
        if session and session.get('awaiting_custom_district'):
            custom_district = raw_text
            session['district'] = custom_district
            session['awaiting_custom_district'] = False
            session['step'] = 4
            deal_type = session.get('deal_type', 'sale')
            text = (
                f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۴ از ۵):</b>\n\n"
                f"📍 منطقه ثبت‌شده: <b>{custom_district}</b>\n\n"
                f"لطفاً <b>بازه متراژ و بودجه</b> مد نظر خود را انتخاب فرمایید:"
            )
            bot.send_message(chat_id, text, reply_markup=_build_wizard_step4_markup(deal_type), parse_mode='HTML')
            return

        # ۲. جستجو با کد عددی فایل (مانند 10001 یا کد ۱۰۰۰۱)
        if _is_property_code_query(raw_text):
            fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            cleaned = raw_text.translate(fa_to_en)
            for kw in ['کد', 'فایل', 'code', 'file', '#', ':', '،', ',', '-', 'شماره']:
                cleaned = cleaned.replace(kw, '')
            clean_digits = ''.join(filter(str.isdigit, cleaned))
            
            if 1 <= len(clean_digits) <= 6:
                app = get_flask_app()
                with app.app_context():
                    from database.models import Property
                    from .notifier import send_property_bale_media
                    prop = Property.get_by_code(clean_digits)
                    if prop:
                        bot.send_message(message.chat.id, f"📸 فایل کد {prop.file_code} یافت شد:")
                        send_property_bale_media(prop, message.chat.id, bot=bot)
                    else:
                        bot.reply_to(
                            message,
                            f"❌ متأسفانه ملکی با کد «{clean_digits}» در سامانه سقف یافت نشد.\n\n"
                            "💡 لطفاً کد ۵ رقمی مندرج روی کارت ملک را بررسی فرمایید.",
                            parse_mode='HTML'
                        )
                return

        # ۳. تحلیل معنایی پیام در CRM هوشمند چندکاناله (OmniChannel Intake)
        try:
            app = get_flask_app()
            with app.app_context():
                from services.omnichannel_engine import OmniChannelEngine
                res = OmniChannelEngine.ingest_interaction(
                    channel='bale',
                    sender_id=str(message.chat.id),
                    text=raw_text,
                    metadata={
                        'chat_id': message.chat.id,
                        'user_name': message.from_user.first_name or '',
                        'username': message.from_user.username or ''
                    }
                )

                role = res.get('role')
                if role == 'owner':
                    fcode = res.get('property_id') or 'جدید'
                    bot.reply_to(
                        message,
                        f"⚜️ <b>مالک گرامی، اطلاعات ملک شما با موفقیت در سیستم ثبت گردید.</b>\n"
                        f"📋 کد پیگیری فایل: <code>{fcode}</code>\n\n"
                        f"کارشناسان دپارتمان سقف پس از بررسی و تایید، فایل شما را به متقاضیان فعال منطقه معرفی خواهند کرد.",
                        parse_mode='HTML'
                    )
                    return
                elif role == 'lead':
                    matches = res.get('matches', [])
                    if matches:
                        from .notifier import send_property_bale_media
                        bot.reply_to(message, f"🎯 <b>درخواست شما ثبت شد! تعداد {len(matches)} فایل منطبق با نیاز شما:</b>", parse_mode='HTML')
                        for p in matches:
                            send_property_bale_media(p, message.chat.id, bot=bot)
                        return
                    else:
                        bot.reply_to(message, "✅ درخواست ملکی شما در پایپ‌لاین متقاضیان سقف ثبت گردید. به محض ثبت فایل متناسب با بودجه شما، سریعاً اطلاع‌رسانی خواهد شد.", parse_mode='HTML')
                        return
        except Exception as e:
            logger.debug(f"OmniChannel intake fallback in Bale: {e}")

        # ۴. راهنمای عمومی در صورت ارسال متن نامفهوم
        text = (
            "⚜️ <b>راهنمای ربات هوشمند املاک سقف در پیام‌رسان بله</b> ⚜️\n\n"
            "• جهت مشاهده آخرین فایل‌ها دستور /start را ارسال فرمایید.\n"
            "• جهت فیلترینگ و استخراج زنده دستور /filter یا دکمه «🎯 فیلتر و استخراج جدید» را انتخاب کنید.\n"
            "• برای دریافت سریع مشخصات و تصاویر، <b>کد فایل</b> (مانند <code>10001</code>) را ارسال کنید.\n"
            "• جهت ورود یا فعال‌سازی دسترسی مدیریت: <code>/admin_login SaghfSuperAdmin#2026!</code>"
        )
        try:
            bot.reply_to(message, text, reply_markup=_build_start_keyboard(message.from_user.id), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error sending fallback text in Bale: {e}")

def start_bale_polling(app=None):
    """
    راه‌اندازی فرآیند Polling پیوسته ربات بله
    """
    if app:
        set_flask_app(app)
    bot = get_bale_bot()
    token = Config.BALE_BOT_TOKEN
    if not token:
        logger.error("BALE_BOT_TOKEN is missing. Cannot start Bale polling.")
        print("❌ خطای عدم تنظیم BALE_BOT_TOKEN: توکن ربات بله تعریف نشده است.", flush=True)
        return

    logger.info("🤖 Starting Bale Bot polling...")
    print(f"🚀 ربات بله سقف با موفقیت متصل شد و آماده دریافت پیام‌ها در پیام‌رسان بله است...", flush=True)
    telebot.apihelper.API_URL = "https://tapi.bale.ai/bot{0}/{1}"
    bot.infinity_polling(timeout=15, long_polling_timeout=15, skip_pending=True)
