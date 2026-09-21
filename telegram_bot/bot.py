import logging
import html
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update
)
from config import Config

logger = logging.getLogger(__name__)

# Initialize bot instance lazily or as singleton
_bot_instance = None
_flask_app_instance = None

def set_flask_app(app):
    """Sets the Flask app instance for app_context wrapping in background handlers."""
    global _flask_app_instance
    _flask_app_instance = app

def get_flask_app():
    """Gets or creates the Flask app instance for app_context wrapping."""
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

def get_bot():
    """
    Returns the singleton TeleBot instance initialized strictly with TELEGRAM_BOT_TOKEN from config.
    """
    global _bot_instance
    if _bot_instance is None:
        token = Config.TELEGRAM_BOT_TOKEN or ""
        if not token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN is not configured in environment variables.")
        # Create non-threaded bot instance optimized for Flask webhook and polling handling
        _bot_instance = telebot.TeleBot(token=token, threaded=False)
        _register_handlers(_bot_instance)
    return _bot_instance

wizard_sessions = {}

def _build_start_keyboard():
    """
    Creates luxury gold/black style inline keyboard for /start command.
    """
    markup = InlineKeyboardMarkup(row_width=2)
    btn_wizard = InlineKeyboardButton("🎯 فیلتر و استخراج جدید", callback_data="wiz_start")
    btn_sale = InlineKeyboardButton("🏷️ آخرین فایل‌های فروش", callback_data="btn_latest_sale")
    btn_rent = InlineKeyboardButton("🔑 آخرین فایل‌های اجاره", callback_data="btn_latest_rent")
    btn_code_search = InlineKeyboardButton("🔢 دریافت آلبوم با کد فایل", callback_data="btn_code_info")
    btn_crm = InlineKeyboardButton("💬 مشاوره با کارشناس ارشد", callback_data="btn_crm_consult")
    btn_search = InlineKeyboardButton("🔍 استعلام و فیلتر پیشرفته", callback_data="btn_search_info")
    
    # Web app link (defaults to localhost or configured web URL)
    web_url = Config.TELEGRAM_WEBHOOK_URL.replace('/api/telegram/webhook', '') if Config.TELEGRAM_WEBHOOK_URL else 'http://127.0.0.1:5000'
    if not web_url.startswith(('http://', 'https://')):
        web_url = f"http://{web_url}"
    btn_web = InlineKeyboardButton("🌐 مشاهده سامانه تحت وب سقف", url=web_url)

    markup.add(btn_wizard)
    markup.add(btn_sale, btn_rent)
    markup.add(btn_code_search, btn_crm)
    markup.add(btn_search)
    markup.add(btn_web)
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
    """
    تشخیص دقیق اینکه آیا پیام کاربر یک درخواست استعلام کد ملک است یا خیر.
    جلوگیری از پاسخ اشتباه به جملات عادی حاوی عدد.
    """
    if not text or text.startswith('/'):
        return False
    raw = text.strip()
    fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
    cleaned = raw.translate(fa_to_en)
    for kw in ['کد', 'فایل', 'code', 'file', '#', ':', '،', ',', '-', 'شماره']:
        cleaned = cleaned.replace(kw, '')
    cleaned = cleaned.strip()
    return cleaned.isdigit() and (1 <= len(cleaned) <= 6)

def is_admin_telegram_user(user_id) -> bool:
    """
    Checks if the Telegram user ID matches ADMIN_TELEGRAM_ID in config.
    """
    admin_id_str = str(Config.ADMIN_TELEGRAM_ID or "").strip()
    if not admin_id_str:
        return False
    return str(user_id).strip() == admin_id_str

def send_admin_system_alert(text: str) -> bool:
    """
    Sends critical system notifications directly to the configured ADMIN_TELEGRAM_ID.
    """
    admin_id_str = str(Config.ADMIN_TELEGRAM_ID or "").strip()
    if not admin_id_str:
        return False
    bot = get_bot()
    if not bot:
        return False
    try:
        bot.send_message(int(admin_id_str), f"🔔 <b>هشدار سیستمی سقف (Super Admin):</b>\n\n{text}", parse_mode='HTML')
        return True
    except Exception as e:
        logger.error(f"Failed to send admin system alert: {e}")
        return False

def _register_handlers(bot: telebot.TeleBot):
    """
    Registers command and callback query handlers on the bot.
    """

    @bot.message_handler(commands=['start', 'help'])
    def handle_start(message):
        # 1. Check if deep link contains property code (e.g. /start code_10001 or /start 10001)
        text_parts = message.text.split() if message.text else []
        if len(text_parts) > 1:
            param = text_parts[1].strip()
            code_candidate = param.replace('code_', '')
            fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            clean_digits = ''.join(filter(str.isdigit, code_candidate.translate(fa_to_en)))
            if clean_digits:
                app = get_flask_app()
                with app.app_context():
                    from database.models import Property
                    prop = Property.get_by_code(clean_digits)
                    if prop:
                        from .notifier import send_property_media_group
                        bot.send_message(message.chat.id, f"📸 در حال ارسال آلبوم تصاویر فایل کد {prop.file_code} ({html.escape(prop.title)})...")
                        send_property_media_group(prop, message.chat.id)
                        return
                    else:
                        bot.send_message(message.chat.id, f"❌ فایل با کد «{clean_digits}» در سامانه سقف یافت نشد یا آرشیو شده است.")

        user_name = message.from_user.first_name or "همراه گرامی"
        welcome_text = (
            f"⚜️ <b>سلام {html.escape(user_name)}، به سامانه فایلینگ املاک سقف خوش آمدید!</b> ⚜️\n\n"
            "این ربات به صورت مستقیم به موتور فایلینگ و استخراج زنده سقف متصل است.\n\n"
            "💡 <b>پرزنت سریع با کد فایل:</b>\n"
            "کافیست <b>کد ۵ رقمی هر ملک</b> (مثلاً <code>10001</code>) را به همین چت ارسال نمایید تا <b>آلبوم کامل تصاویر و مشخصات فنی</b> بلافاصله برای شما ارسال شود.\n\n"
            "جهت مشاهده فایل‌های دسته‌بندی‌شده، گزینه‌های زیر را انتخاب نمایید:"
        )
        try:
            bot.reply_to(message, welcome_text, reply_markup=_build_start_keyboard(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling /start message: {e}")

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
                prop = Property.get_by_code(clean_digits)
                if prop:
                    from .notifier import send_property_media_group
                    try:
                        bot.send_message(message.chat.id, f"📸 در حال ارسال آلبوم تصاویر فایل کد {prop.file_code}...")
                    except Exception:
                        pass
                    send_property_media_group(prop, message.chat.id)
                else:
                    bot.reply_to(message, f"❌ ملکی با کد «{clean_digits}» در سامانه سقف یافت نشد.")
        except Exception as e:
            logger.error(f"Error handling code command: {e}")

    # ==========================================
    # Super Admin Commands: /admin, /stats, /crawl
    # ==========================================
    @bot.message_handler(commands=['admin'])
    def handle_admin_command(message):
        user_id = message.from_user.id
        if not is_admin_telegram_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"این بخش صرفاً برای حساب <b>مدیر ارشد (Super Admin)</b> سامانه مجاز است.\n"
                f"شناسه عددی شما (<code>{user_id}</code>) در لیست مدیران مجاز سامانه سقف ثبت نشده است.",
                parse_mode='HTML'
            )
            return

        text = (
            "👑 <b>کنسول مدیریت ارشد سقف (Super Admin)</b> 👑\n\n"
            "درود بر مدیر ارشد سامانه. فرامین اختصاصی شما:\n\n"
            "📊 <code>/stats</code> — گزارش آمار لحظه‌ای دیتابیس، فایل‌ها و متقاضیان\n"
            "🕷️ <code>/crawl</code> — راه‌اندازی فوری تسک کراولینگ دیوار و شیپور\n\n"
            "🌐 جهت ورود به پنل تحت وب مدیریت:\n"
            "http://127.0.0.1:5000/admin/dashboard"
        )
        bot.reply_to(message, text, parse_mode='HTML')

    @bot.message_handler(commands=['stats'])
    def handle_stats_command(message):
        user_id = message.from_user.id
        if not is_admin_telegram_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"مشاهده آمار سیستمی صرفاً برای حساب <b>مدیر ارشد (Super Admin)</b> مجاز است.\n"
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
                    "📊 <b>گزارش آمار جامع سامانه املاک سقف:</b>\n\n"
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
                bot.reply_to(message, report, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error serving admin /stats: {e}")
            bot.reply_to(message, f"❌ خطا در استخراج آمار: {e}")

    @bot.message_handler(commands=['crawl'])
    def handle_crawl_command(message):
        user_id = message.from_user.id
        if not is_admin_telegram_user(user_id):
            bot.reply_to(
                message,
                f"⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                f"اجرای تسک‌های کراولر صرفاً برای حساب <b>مدیر ارشد (Super Admin)</b> مجاز است.\n"
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
                        f"{msg}\n"
                        f"فایل‌های جدید پس از پردازش در سامانه و کانال قرار خواهند گرفت.",
                        parse_mode='HTML'
                    )
                else:
                    bot.reply_to(message, f"⚠️ <b>خطا در شروع کراولینگ:</b>\n{msg}", parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error triggering admin /crawl: {e}")
            bot.reply_to(message, f"❌ خطای اجرایی: {e}")

    @bot.message_handler(func=lambda msg: _is_property_code_query(msg.text))
    def handle_numeric_code_search(message):
        try:
            raw_text = message.text.strip()
            fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
            cleaned = raw_text.translate(fa_to_en)
            for kw in ['کد', 'فایل', 'code', 'file', '#', ':', '،', ',', '-', 'شماره']:
                cleaned = cleaned.replace(kw, '')
            clean_digits = ''.join(filter(str.isdigit, cleaned))
            
            if not (1 <= len(clean_digits) <= 6):
                return

            app = get_flask_app()
            with app.app_context():
                from database.models import Property
                prop = Property.get_by_code(clean_digits)
                if prop:
                    from .notifier import send_property_media_group
                    try:
                        bot.send_message(message.chat.id, f"📸 در حال ارسال آلبوم کامل تصاویر فایل کد {prop.file_code} ({html.escape(prop.title)})...")
                    except Exception:
                        pass
                    send_property_media_group(prop, message.chat.id)
                else:
                    bot.reply_to(
                        message,
                        f"❌ متأسفانه ملکی با کد «{clean_digits}» در سامانه سقف یافت نشد.\n\n"
                        "💡 لطفاً کد ۵ رقمی مندرج روی کارت ملک در وب‌اپ را بررسی فرمایید.",
                        parse_mode='HTML'
                    )
        except Exception as e:
            logger.error(f"Error handling numeric code search: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == 'btn_code_info')
    def handle_code_info_callback(call):
        try:
            bot.answer_callback_query(call.id)
            text = (
                "🔢 <b>راهنمای استعلام و پرزنت تصاویر با کد فایل:</b>\n\n"
                "هر فایل در وب‌اپ سقف دارای یک <b>کد ۵ رقمی اختصاصی</b> (مانند <code>10001</code>) است.\n\n"
                "📌 هر زمان که در حال صحبت تلفنی یا پرزنت به مشتری بودید، کافیست <b>کد فایل را در همین چت بفرستید</b> "
                "تا تمام عکس‌های ملک به همراه مشخصات کامل و لینک مستقیم، به صورت یک آلبوم باکیفیت برای شما یا مشتری فوروارد شود."
            )
            bot.send_message(call.message.chat.id, text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling code info callback: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('act_') or call.data == 'btn_crm_consult')
    def handle_unified_actions_callback(call):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        app = get_flask_app()
        with app.app_context():
            from services.unified_bot_controller import UnifiedBotController
            user_name = call.from_user.first_name if call.from_user else None
            res = UnifiedBotController.handle_callback_query('telegram', call.message.chat.id, call.data, user_name)
            
            if res.get('type') == 'text':
                bot.send_message(call.message.chat.id, res['message'], reply_markup=res.get('reply_markup'), parse_mode='HTML')
            elif res.get('type') == 'property_package':
                prop = res.get('property')
                from .notifier import send_property_media_group
                send_property_media_group(prop, call.message.chat.id)

    @bot.callback_query_handler(func=lambda call: call.data in ['btn_latest_sale', 'btn_latest_rent'])
    def handle_latest_properties_callback(call):
        deal_type = 'sale' if call.data == 'btn_latest_sale' else 'rent'
        deal_title = 'فروش' if deal_type == 'sale' else 'رهن و اجاره'
        
        try:
            bot.answer_callback_query(call.id, text=f"در حال دریافت ۵ فایل آخر {deal_title}...")
        except Exception:
            pass

        try:
            # Query the database inside application context
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
                    
                    # Rule 2 in AGENTS.md: Always ensure link to ad with text 'لینک آگهی'
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
            logger.error(f"Error serving properties callback: {e}")
            try:
                bot.send_message(call.message.chat.id, "خطا در واکشی فایل‌ها. لطفاً دوباره تلاش نمایید.")
            except Exception:
                pass

    @bot.callback_query_handler(func=lambda call: call.data == 'btn_search_info')
    def handle_search_info(call):
        try:
            bot.answer_callback_query(call.id)
            info_text = (
                "🔍 <b>استعلام و فیلتر فایل‌های اختصاصی سقف:</b>\n\n"
                "برای جستجوی پیشرفته بر اساس منطقه (ولنجک، نیاوران، سعادت‌آباد و...)، متراژ، قیمت "
                "و بودجه دلخواه خود، می‌توانید مستقیماً از طریق داشبورد وب سامانه اقدام کنید.\n\n"
                "🏢 کلیه فایل‌ها دارای راستی‌آزمایی ۷ روزه و استعلام بلادرنگ می‌باشند."
            )
            bot.send_message(call.message.chat.id, info_text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error handling search callback: {e}")

    # =========================================================================
    # In-Bot Filter & Scrape Wizard (Conversation State Machine)
    # =========================================================================

    @bot.message_handler(commands=['filter', 'wizard'])
    def handle_filter_command(message):
        chat_id = message.chat.id
        wizard_sessions[chat_id] = {'step': 1}
        text = (
            "🎯 <b>ویزارد فیلترینگ و استخراج هدفمند املاک سقف (گام ۱ از ۵):</b>\n\n"
            "به دستیار استخراج مستقیم سقف خوش آمدید. بدون نیاز به مراجعه به وب‌اپ، فیلترهای مد نظر خود را تعیین فرمایید تا کراولر در لحظه از دیوار استخراج نماید.\n\n"
            "لطفاً <b>نوع معامله</b> را مشخص فرمایید:"
        )
        bot.send_message(chat_id, text, reply_markup=_build_wizard_step1_markup(), parse_mode='HTML')

    @bot.callback_query_handler(func=lambda call: call.data == 'wiz_start')
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

    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_deal_sale', 'wiz_deal_rent'])
    def handle_wizard_step1(call):
        chat_id = call.message.chat.id
        deal_type = 'sale' if call.data == 'wiz_deal_sale' else 'rent'
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

    @bot.callback_query_handler(func=lambda call: call.data in ['wiz_type_apartment', 'wiz_type_villa', 'wiz_type_commercial'])
    def handle_wizard_step2(call):
        chat_id = call.message.chat.id
        prop_map = {
            'wiz_type_apartment': ('apartment', '🏢 آپارتمان مسکونی'),
            'wiz_type_villa': ('villa', '🏡 ویلایی / کلنگی'),
            'wiz_type_commercial': ('commercial', '🏬 اداری / تجاری')
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

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_dist_'))
    def handle_wizard_step3(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.setdefault(chat_id, {})
        
        if call.data == 'wiz_dist_custom':
            session['awaiting_custom_district'] = True
            try:
                bot.answer_callback_query(call.id)
            except Exception:
                pass
            text = (
                "✍️ <b>ورود دستی نام محله / منطقه:</b>\n\n"
                "لطفاً نام محله مورد نظر خود را در همین چت تایپ و ارسال کنید.\n"
                "مثال‌ها: <code>فردوس</code>، <code>کاشانی</code>، <code>شاهین جنوبی</code>، <code>سازمان برنامه</code>، <code>سعادت آباد</code> و..."
            )
            bot.send_message(chat_id, text, parse_mode='HTML')
            return

        district = call.data.replace('wiz_dist_', '').strip()
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

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_bud_'))
    def handle_wizard_step4(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.setdefault(chat_id, {})
        key = call.data

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

    @bot.callback_query_handler(func=lambda call: call.data.startswith('wiz_back_'))
    def handle_wizard_back(call):
        chat_id = call.message.chat.id
        step = call.data.replace('wiz_back_', '')
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

    @bot.callback_query_handler(func=lambda call: call.data == 'wiz_cancel')
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

    @bot.callback_query_handler(func=lambda call: call.data == 'wiz_exec')
    def handle_wizard_execute(call):
        chat_id = call.message.chat.id
        session = wizard_sessions.get(chat_id)
        if not session:
            try:
                bot.answer_callback_query(call.id, text="⚠️ نشست منقضی شده است.")
            except Exception:
                pass
            bot.send_message(chat_id, "⚠️ نشست فیلترینگ منقضی شده است. لطفاً مجدداً از منو دکمه «🎯 فیلتر و استخراج جدید» را بزنید.", reply_markup=_build_start_keyboard())
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
            from database.models import Property
            from crawler.crawler_manager import crawler_manager
            from .notifier import send_property_alert

            # ۱. جستجو در دیتابیس
            query = Property.query.filter(Property.status.notin_(['archived', 'sold']))
            if deal_type and deal_type != 'all':
                query = query.filter(Property.deal_type == deal_type)
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

            matches = query.order_by(Property.created_at.desc()).limit(5).all()

            # ۲. اگر تعداد فایل‌های موجود در دیتابیس کمتر از ۳ تا بود، فوراً یک کراول زنده اجرا کن
            if len(matches) < 3:
                cat_key = 'buy-apartment' if deal_type == 'sale' else 'rent-apartment'
                try:
                    crawler_manager.divar_crawler.fetch_listings(
                        category_key=cat_key,
                        limit=4,
                        query=district_clean,
                        districts=[district_clean] if district_clean else None,
                        min_price=session.get('min_price'),
                        max_price=session.get('max_price'),
                        min_deposit=session.get('min_deposit'),
                        max_deposit=session.get('max_deposit'),
                        min_rent=session.get('min_rent'),
                        max_rent=session.get('max_rent'),
                        min_area=session.get('min_area'),
                        max_area=session.get('max_area')
                    )
                    matches = query.order_by(Property.created_at.desc()).limit(5).all()
                except Exception as err:
                    logger.warning(f"Wizard live crawl error: {err}")

            # ۳. ارسال نتایج به صورت تک‌به‌تک همراه با عکس، کد، قیمت و لینک مستقیم
            if not matches:
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
                    f"🎯 <b>تعداد {len(matches)} فایل منطبق با شرایط انتخابی شما در منطقه {district or 'تهران'}:</b>\n" + ("—" * 28),
                    parse_mode='HTML'
                )
                for p in matches:
                    try:
                        send_property_alert(p, target_chat_id=chat_id)
                    except Exception as pe:
                        logger.error(f"Error sending property to user: {pe}")

                bot.send_message(
                    chat_id,
                    "✨ <b>استخراج و جستجوی فایل‌ها تکمیل شد.</b>\n\n"
                    "💡 جهت دریافت آلبوم کامل هر ملک در چت، کافیست <b>کد ۵ رقمی</b> آن (مانند <code>10001</code>) را در همین چت بفرستید.",
                    reply_markup=_build_start_keyboard(),
                    parse_mode='HTML'
                )

        wizard_sessions.pop(chat_id, None)

    @bot.message_handler(content_types=['text'])
    def handle_fallback_text(message):
        chat_id = message.chat.id
        session = wizard_sessions.get(chat_id)
        if session and session.get('awaiting_custom_district'):
            custom_district = message.text.strip()
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

        app = get_flask_app()
        with app.app_context():
            from services.unified_bot_controller import UnifiedBotController
            user_name = message.from_user.first_name if message.from_user else None
            user_phone = getattr(getattr(message, 'contact', None), 'phone_number', None)
            res = UnifiedBotController.handle_natural_text('telegram', chat_id, message.text, user_phone, user_name)

            if res.get('type') == 'crm_matches':
                intro = res.get('intro_message')
                if intro:
                    try:
                        bot.send_message(chat_id, intro, parse_mode='HTML')
                    except Exception:
                        pass

                for card in res.get('cards', []):
                    prop = card.get('property')
                    markup = card.get('reply_markup')
                    card_text = card.get('card_text')
                    images = []
                    if prop and prop.images:
                        try:
                            import json
                            images = json.loads(prop.images) if isinstance(prop.images, str) else prop.images
                        except Exception:
                            images = []
                    if images and isinstance(images, list) and len(images) > 0:
                        try:
                            bot.send_photo(chat_id, images[0], caption=card_text, reply_markup=markup, parse_mode='HTML')
                        except Exception:
                            bot.send_message(chat_id, card_text, reply_markup=markup, parse_mode='HTML')
                    else:
                        bot.send_message(chat_id, card_text, reply_markup=markup, parse_mode='HTML')

                bot.send_message(chat_id, "💡 جهت هماهنگی بازدید هر فایل، دکمه «✨ هماهنگی بازدید حضوری» را لمس فرمایید.", reply_markup=_build_start_keyboard(), parse_mode='HTML')
                return

            if res.get('type') == 'text':
                try:
                    bot.reply_to(message, res['message'], reply_markup=res.get('reply_markup') or _build_start_keyboard(), parse_mode='HTML')
                except Exception as e:
                    logger.error(f"Error sending CRM reply: {e}")
                return

def _format_compact_property(p):
    """
    Formats a single property compactly for Telegram chat.
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

    # Amenities icons
    amenities = []
    if p.has_parking: amenities.append("پارکینگ")
    if p.has_elevator: amenities.append("آسانسور")
    if p.has_warehouse: amenities.append("انباری")
    if p.has_balcony: amenities.append("بالکن")
    if amenities:
        lines.append(f"✨ امکانات: {' • '.join(amenities)}")

    # Add direct link anchor tag matching AGENTS.md requirement
    ad_link = html.escape(p.source_url or f"http://127.0.0.1:5000/properties/{p.id}")
    lines.append(f'\n🌐 <a href="{ad_link}">لینک آگهی</a>')

    return "\n".join(lines)

def process_update(update_dict: dict):
    """
    Processes an incoming update dict received from Flask webhook endpoint.
    """
    bot = get_bot()
    if not bot or not Config.TELEGRAM_BOT_TOKEN:
        logger.warning("Bot is not configured; ignoring webhook update.")
        return False
    try:
        update = Update.de_json(update_dict)
        bot.process_new_updates([update])
        return True
    except Exception as e:
        logger.error(f"Error processing Telegram webhook update: {e}")
        return False

def setup_webhook(webhook_url: str):
    """
    Configures Telegram webhook to point to the server endpoint.
    """
    bot = get_bot()
    if not Config.TELEGRAM_BOT_TOKEN:
        return {'success': False, 'message': 'توکن بات تلگرام تنظیم نشده است.'}
    try:
        bot.remove_webhook()
        res = bot.set_webhook(url=webhook_url)
        logger.info(f"Telegram webhook configured to: {webhook_url} -> {res}")
        return {'success': bool(res), 'webhook_url': webhook_url, 'result': res}
    except Exception as e:
        logger.error(f"Error setting Telegram webhook: {e}")
        return {'success': False, 'error': str(e)}

def remove_webhook():
    """
    Removes Telegram webhook to allow long-polling or teardown.
    """
    bot = get_bot()
    if not Config.TELEGRAM_BOT_TOKEN:
        return {'success': False, 'message': 'توکن بات تلگرام تنظیم نشده است.'}
    try:
        res = bot.remove_webhook()
        return {'success': bool(res)}
    except Exception as e:
        logger.error(f"Error removing Telegram webhook: {e}")
        return {'success': False, 'error': str(e)}

def get_webhook_info():
    """
    Fetches the current Telegram webhook status.
    """
    bot = get_bot()
    if not Config.TELEGRAM_BOT_TOKEN:
        return {'configured': False, 'message': 'توکن تنظیم نشده است.'}
    try:
        info = bot.get_webhook_info()
        return {
            'configured': True,
            'url': info.url,
            'has_custom_certificate': info.has_custom_certificate,
            'pending_update_count': info.pending_update_count,
            'last_error_date': info.last_error_date,
            'last_error_message': info.last_error_message,
            'max_connections': info.max_connections,
            'ip_address': info.ip_address
        }
    except Exception as e:
        return {'configured': True, 'error': str(e)}

def start_polling(flask_app=None):
    """
    Starts Telegram bot long polling for real-time interaction.
    Automatically removes any active webhook first to avoid conflicts.
    """
    if flask_app:
        set_flask_app(flask_app)
    bot = get_bot()
    if not Config.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing. Cannot start polling.")
        print("❌ خطای عدم تنظیم TELEGRAM_BOT_TOKEN: امکان اجرای بات وجود ندارد.")
        return
    try:
        bot.remove_webhook()
        me = bot.get_me()
        logger.info(f"🚀 Telegram Bot Polling started for @{me.username} (ID: {me.id})")
        print(f"✅ ربات تلگرام سقف (@{me.username}) با موفقیت به سرورهای تلگرام متصل شد و آماده دریافت پیام است...", flush=True)
        bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True)
    except Exception as e:
        logger.error(f"Telegram polling terminated: {e}")
        print(f"⚠️ خطای توقف Polling ربات تلگرام: {e}", flush=True)
