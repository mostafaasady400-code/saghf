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

def _build_start_keyboard():
    """
    Creates luxury gold/black style inline keyboard for /start command.
    """
    markup = InlineKeyboardMarkup(row_width=2)
    btn_sale = InlineKeyboardButton("🏷️ آخرین فایل‌های فروش", callback_data="btn_latest_sale")
    btn_rent = InlineKeyboardButton("🔑 آخرین فایل‌های اجاره", callback_data="btn_latest_rent")
    btn_code_search = InlineKeyboardButton("🔢 دریافت آلبوم با کد فایل", callback_data="btn_code_info")
    btn_search = InlineKeyboardButton("🔍 استعلام و فیلتر پیشرفته", callback_data="btn_search_info")
    
    # Web app link (defaults to localhost or configured web URL)
    web_url = Config.TELEGRAM_WEBHOOK_URL.replace('/api/telegram/webhook', '') if Config.TELEGRAM_WEBHOOK_URL else 'http://127.0.0.1:5000'
    if not web_url.startswith(('http://', 'https://')):
        web_url = f"http://{web_url}"
    btn_web = InlineKeyboardButton("🌐 مشاهده سامانه تحت وب سقف", url=web_url)

    markup.add(btn_sale, btn_rent)
    markup.add(btn_code_search, btn_search)
    markup.add(btn_web)
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

    @bot.message_handler(content_types=['text'])
    def handle_fallback_text(message):
        text = (
            "⚜️ <b>راهنمای ربات هوشمند املاک سقف</b> ⚜️\n\n"
            "• جهت مشاهده آخرین فایل‌ها دستور /start را ارسال فرمایید.\n"
            "• برای دریافت سریع آلبوم تصاویر و مشخصات فنی، <b>کد فایل</b> (مانند <code>10001</code>) را ارسال کنید.\n"
            "• جهت استعلام مستقیم، دستور <code>/code 10001</code> را وارد کنید."
        )
        try:
            bot.reply_to(message, text, reply_markup=_build_start_keyboard(), parse_mode='HTML')
        except Exception as e:
            logger.error(f"Error sending fallback text: {e}")

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
