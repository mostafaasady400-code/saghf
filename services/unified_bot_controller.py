"""
=============================================================================
کنترلر مرکزی و موتور پردازش یکپارچه ربات سقف (@Saghf_bot)
پشتیبانی ۱۰۰٪ متقارن و همزمان از دو پلتفرم:
1. تلگرام (Telegram)
2. بله (Bale)
کلیه قابلیت‌ها شامل:
- استقبال و آنبوردینگ با پرسونای مشاور ارشد
- ویزارد ۵ مرحله‌ای استخراج و فیلتر
- استعلام آلبوم و مشخصات با کد فایل عددی
- موتور هوشمند فروش CRM با رعایت دقیق محرمانگی فایل‌ها
- ارسال فوری هشدارهای Hot Lead به کارشناس
- دستورات مدیریتی ارشد (/admin, /stats, /crawl)
=============================================================================
"""

import html
import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple, Union

from config import Config
from database.db import db
from database.models import Property, Client, CustomerLead
from services.crm_sales_assistant import CRMSalesAssistantEngine
from crawler.crawler_manager import crawler_manager

logger = logging.getLogger(__name__)

# حافظه نشست‌های ویزارد فیلترینگ برای هر کاربر: key = f"{platform}:{chat_id}"
wizard_sessions: Dict[str, Dict[str, Any]] = {}


class BotMarkupBuilder:
    """
    تولیدکننده ساختار دکمه‌های شیشه‌ای متناسب با پلتفرم مقصد (Telegram یا Bale)
    """
    def __init__(self, platform: str):
        self.platform = platform  # 'telegram' or 'bale'
        self.rows: List[List[Dict[str, str]]] = []

    def add_row(self, *buttons: Tuple[str, str, Optional[str]]):
        """
        هر دکمه به صورت تاپل: (text, callback_data, optional_url)
        """
        row = []
        for btn in buttons:
            text = btn[0]
            callback_data = btn[1] if len(btn) > 1 else None
            url = btn[2] if len(btn) > 2 else None

            btn_dict = {'text': text}
            if url:
                btn_dict['url'] = url
            elif callback_data:
                btn_dict['callback_data'] = callback_data
            row.append(btn_dict)
        self.rows.append(row)
        return self

    def build(self) -> Any:
        """خروجی بر اساس نوع پیام‌رسان"""
        if self.platform == 'telegram':
            import telebot
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup()
            for row in self.rows:
                tg_row = []
                for b in row:
                    if 'url' in b:
                        tg_row.append(InlineKeyboardButton(text=b['text'], url=b['url']))
                    else:
                        tg_row.append(InlineKeyboardButton(text=b['text'], callback_data=b.get('callback_data', '')))
                markup.row(*tg_row)
            return markup
        else:
            # فرمت رسمی پیام‌رسان بله (Bale)
            return {'inline_keyboard': self.rows}


class UnifiedBotController:
    """
    مغز متفکر ربات سقف برای مدیریت یکپارچه درخواست‌های بله و تلگرام
    """

    @classmethod
    def get_session_key(cls, platform: str, chat_id: Union[int, str]) -> str:
        return f"{platform}:{chat_id}"

    # =========================================================================
    # منوها و کیبوردهای عمومی
    # =========================================================================

    @classmethod
    def build_main_keyboard(cls, platform: str) -> Any:
        builder = BotMarkupBuilder(platform)
        builder.add_row(("🎯 فیلتر و استخراج هوشمند", "wiz_start", None))
        builder.add_row(
            ("🏷️ آخرین فایل‌های فروش", "btn_latest_sale", None),
            ("🔑 آخرین فایل‌های اجاره", "btn_latest_rent", None)
        )
        builder.add_row(
            ("🔢 دریافت آلبوم با کد فایل", "btn_code_info", None),
            ("💬 مشاوره با کارشناس ارشد", "btn_crm_consult", None)
        )
        web_url = Config.TELEGRAM_WEBHOOK_URL.replace('/api/telegram/webhook', '') if Config.TELEGRAM_WEBHOOK_URL else 'http://127.0.0.1:5000'
        if not web_url.startswith(('http://', 'https://')):
            web_url = f"http://{web_url}"
        builder.add_row(("🌐 مشاهده سامانه تحت وب سقف", None, web_url))
        return builder.build()

    @classmethod
    def build_wizard_step1_markup(cls, platform: str) -> Any:
        builder = BotMarkupBuilder(platform)
        builder.add_row(
            ("🏷️ خرید و فروش", "wiz_deal_sale", None),
            ("🔑 رهن و اجاره", "wiz_deal_rent", None)
        )
        builder.add_row(("❌ انصراف", "wiz_cancel", None))
        return builder.build()

    @classmethod
    def build_wizard_step2_markup(cls, platform: str) -> Any:
        builder = BotMarkupBuilder(platform)
        builder.add_row(
            ("🏢 آپارتمان مسکونی", "wiz_type_apartment", None),
            ("🏡 ویلایی / کلنگی", "wiz_type_villa", None)
        )
        builder.add_row(("🏬 اداری / تجاری", "wiz_type_commercial", None))
        builder.add_row(
            ("🔙 مرحله قبل", "wiz_back_1", None),
            ("❌ انصراف", "wiz_cancel", None)
        )
        return builder.build()

    @classmethod
    def build_wizard_step3_markup(cls, platform: str) -> Any:
        builder = BotMarkupBuilder(platform)
        builder.add_row(
            ("📍 پونک", "wiz_dist_پونک", None),
            ("📍 جنت‌آباد", "wiz_dist_جنت‌آباد", None)
        )
        builder.add_row(
            ("📍 صادقیه / ستارخان", "wiz_dist_صادقیه", None),
            ("📍 شهران", "wiz_dist_شهران", None)
        )
        builder.add_row(
            ("📍 سعادت‌آباد", "wiz_dist_سعادت‌آباد", None),
            ("📍 کل منطقه ۵", "wiz_dist_منطقه ۵", None)
        )
        builder.add_row(("✍️ تایپ نام محله دلخواه", "wiz_dist_custom", None))
        builder.add_row(
            ("🔙 مرحله قبل", "wiz_back_2", None),
            ("❌ انصراف", "wiz_cancel", None)
        )
        return builder.build()

    @classmethod
    def build_wizard_step4_markup(cls, platform: str, deal_type: str) -> Any:
        builder = BotMarkupBuilder(platform)
        if deal_type == 'sale':
            builder.add_row(("📐 متراژ تا ۸۰ م | تا ۶ میلیارد", "wiz_bud_s1", None))
            builder.add_row(("📐 متراژ ۸۰ تا ۱۱۰ م | ۶ تا ۱۰ میلیارد", "wiz_bud_s2", None))
            builder.add_row(("📐 متراژ ۱۱۰ تا ۱۵۰ م | ۱۰ تا ۱۶ میلیارد", "wiz_bud_s3", None))
            builder.add_row(("📐 متراژ ۱۵۰+ م | ۱۶+ میلیارد", "wiz_bud_s4", None))
            builder.add_row(("🌐 بدون محدودیت بودجه و متراژ", "wiz_bud_any", None))
        else:
            builder.add_row(("💳 ودیعه تا ۵۰۰ م | اجاره تا ۱۵ م", "wiz_bud_r1", None))
            builder.add_row(("💳 ودیعه ۵۰۰ تا ۱ م | اجاره ۱۵ تا ۳۰ م", "wiz_bud_r2", None))
            builder.add_row(("💳 ودیعه ۱ تا ۲ م | اجاره ۳۰ تا ۵۰ م", "wiz_bud_r3", None))
            builder.add_row(("💳 رهن کامل (۱.۵ تا ۳ میلیارد)", "wiz_bud_r4", None))
            builder.add_row(("🌐 بدون محدودیت بودجه و متراژ", "wiz_bud_any", None))
        builder.add_row(
            ("🔙 مرحله قبل", "wiz_back_3", None),
            ("❌ انصراف", "wiz_cancel", None)
        )
        return builder.build()

    @classmethod
    def build_wizard_step5_markup(cls, platform: str) -> Any:
        builder = BotMarkupBuilder(platform)
        builder.add_row(("🚀 شروع استخراج و جستجو", "wiz_exec", None))
        builder.add_row(
            ("🔄 تنظیم مجدد", "wiz_start", None),
            ("❌ انصراف", "wiz_cancel", None)
        )
        return builder.build()

    @classmethod
    def build_property_action_markup(cls, platform: str, prop_id: int) -> Any:
        """
        دکمه‌های اقدام و تعامل مشتری روی کارت ملک (با رعایت کامل محرمانگی)
        """
        builder = BotMarkupBuilder(platform)
        builder.add_row(("✨ هماهنگی بازدید حضوری", f"act_visit_{prop_id}", None))
        builder.add_row(
            ("📉 بودجه بالاست", f"act_budget_{prop_id}", None),
            ("📍 لوکیشن مناسب نیست", f"act_loc_{prop_id}", None)
        )
        builder.add_row(("📸 دریافت آلبوم تصاویر این ملک", f"act_photos_{prop_id}", None))
        return builder.build()

    # =========================================================================
    # تشخیص‌های هوشمند متن ورودی
    # =========================================================================

    @classmethod
    def extract_property_code(cls, text: str) -> Optional[str]:
        """
        استخراج کد ملک در صورت تایپ عباراتی مثل:
        10001, کد 10001, #10001, file 10001
        """
        if not text or text.startswith('/'):
            return None
        raw = text.strip()
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        cleaned = raw.translate(fa_to_en)
        for kw in ['کد', 'فایل', 'code', 'file', '#', ':', '،', ',', '-', 'شماره']:
            cleaned = cleaned.replace(kw, '')
        clean_digits = ''.join(filter(str.isdigit, cleaned.strip()))
        if clean_digits and (1 <= len(clean_digits) <= 6):
            return clean_digits
        return None

    @classmethod
    def is_admin_user(cls, platform: str, user_id: Union[int, str]) -> bool:
        """بررسی مجاز بودن کاربر ادمین بر اساس متغیرهای محیطی"""
        u_str = str(user_id).strip()
        if platform == 'telegram':
            admin_id = str(Config.ADMIN_TELEGRAM_ID or "").strip()
            return bool(admin_id and u_str == admin_id)
        else:
            admin_id = str(getattr(Config, 'ADMIN_BALE_ID', '') or Config.ADMIN_TELEGRAM_ID or "").strip()
            return bool(admin_id and u_str == admin_id)

    # =========================================================================
    # متدهای اجرایی تعاملی
    # =========================================================================

    @classmethod
    def handle_start(cls, platform: str, chat_id: Union[int, str], user_name: str, deep_link_param: Optional[str] = None) -> Dict[str, Any]:
        """
        پاسخ به دستور /start یا شروع مکالمه در بله و تلگرام
        """
        # ۱. بررسی دیپ لینک کد فایل (مانند /start code_10001 یا /start 10001)
        if deep_link_param:
            code_candidate = deep_link_param.replace('code_', '').strip()
            clean_digits = cls.extract_property_code(code_candidate)
            if clean_digits:
                prop = Property.get_by_code(clean_digits)
                if prop:
                    return {
                        'type': 'property_package',
                        'property': prop,
                        'message': f"📸 در حال ارسال آلبوم تصاویر و مشخصات فنی فایل کد {prop.file_code} ({html.escape(prop.title)})...",
                        'reply_markup': cls.build_property_action_markup(platform, prop.id)
                    }
                else:
                    return {
                        'type': 'text',
                        'message': f"❌ فایل ملکی با کد «{clean_digits}» در سامانه سقف یافت نشد یا آرشیو گردیده است.",
                        'reply_markup': cls.build_main_keyboard(platform)
                    }

        welcome_text = (
            f"⚜️ <b>سلام {html.escape(user_name or 'همراه گرامی')}، به سامانه هوشمند فایلینگ املاک سقف خوش آمدید!</b> ⚜️\n\n"
            "این ربات به صورت بلادرنگ به موتور استخراج، فایلینگ و هوش مصنوعی سقف متصل است.\n\n"
            "💡 <b>پرزنت سریع با کد فایل:</b>\n"
            "کافیست <b>کد ۵ رقمی هر ملک</b> (مثلاً <code>10001</code>) را در همین چت ارسال فرمایید تا "
            "<b>آلبوم کامل تصاویر و مشخصات فنی بدون واسطه</b> بلافاصله تقدیم حضورتان شود.\n\n"
            "جهت جستجوی هوشمند، مشاوره خرید/اجاره یا فیلتر فایل‌ها گزینه‌های زیر را لمس نمایید:"
        )
        return {
            'type': 'text',
            'message': welcome_text,
            'reply_markup': cls.build_main_keyboard(platform)
        }

    @classmethod
    def handle_code_search(cls, platform: str, chat_id: Union[int, str], file_code: str) -> Dict[str, Any]:
        """ارسال مشخصات و تصاویر ملک با کد اختصاصی"""
        prop = Property.get_by_code(file_code)
        if not prop:
            return {
                'type': 'text',
                'message': (
                    f"❌ متأسفانه ملکی با کد «{file_code}» در سامانه سقف یافت نشد.\n\n"
                    "💡 لطفاً کد ۵ رقمی مندرج روی کارت ملک در وب‌اپ را بررسی فرمایید."
                ),
                'reply_markup': cls.build_main_keyboard(platform)
            }

        # کارت محرمانه با دکمه‌های تعاملی
        card_text = cls.format_client_property_card(prop, score=98)
        return {
            'type': 'property_package',
            'property': prop,
            'card_text': card_text,
            'reply_markup': cls.build_property_action_markup(platform, prop.id)
        }

    @classmethod
    def format_client_property_card(cls, prop: Property, score: int = 90) -> str:
        """
        قالب‌بندی کارت ملک ویژه مشتری در تلگرام و بله با رعایت اکید اصل محرمانگی:
        شماره مالک و لینک سورس هرگز درج نمی‌شود.
        """
        deal_label = '🏷️ فروش' if prop.deal_type == 'sale' else '🔑 رهن و اجاره'
        
        lines = [
            f"⚜️ <b>پیشنهاد ویژه سقف | فایل کد {prop.file_code}</b> (تطابق: {score}٪) ⚜️",
            f"📌 <b>{html.escape(prop.title or 'آپارتمان مسکونی')}</b>",
            f"📍 منطقه: <b>{html.escape(prop.district or 'تهران')}</b>",
            f"📐 متراژ: <b>{prop.area} متر</b> | 🛏️ <b>{prop.rooms} خواب</b> | طبقه: {prop.floor or 1}",
            f"🏷️ نوع قرارداد: <b>{deal_label}</b>"
        ]

        if prop.deal_type == 'sale':
            if prop.total_price and prop.total_price > 0:
                price_b = prop.total_price / 1_000_000_000
                p_str = f"{price_b:.2f} میلیارد تومان" if price_b >= 1 else f"{prop.total_price / 1_000_000:.0f} میلیون تومان"
                lines.append(f"💰 قیمت کل: <b>{p_str}</b>")
            else:
                lines.append("💰 قیمت: <b>توافقی</b>")
        else:
            dep = f"{prop.deposit / 1_000_000:.0f} م تومان" if prop.deposit else "توافقی"
            rnt = f"{prop.monthly_rent / 1_000_000:.0f} م تومان" if prop.monthly_rent else "توافقی"
            lines.append(f"💳 ودیعه: <b>{dep}</b> | اجاره: <b>{rnt}</b>")

        amenities = []
        if prop.has_parking: amenities.append("🚗 پارکینگ")
        if prop.has_elevator: amenities.append("🛗 آسانسور")
        if prop.has_warehouse: amenities.append("📦 انباری")
        if prop.has_balcony: amenities.append("🌿 بالکن")
        if amenities:
            lines.append(f"✨ امکانات: {' • '.join(amenities)}")

        lines.append("\n🔒 <i>این فایل دارای راستی‌آزمایی مستقیم دفتر سقف است. جهت هماهنگی بازدید دکمه زیر را لمس نمایید.</i>")
        return "\n".join(lines)

    # =========================================================================
    # پردازش متن‌های محاوره‌ای و گفتگوی طبیعی با CRM Sales Assistant
    # =========================================================================

    @classmethod
    def handle_natural_text(cls, platform: str, chat_id: Union[int, str], user_text: str, user_phone: Optional[str] = None, user_name: Optional[str] = None) -> Dict[str, Any]:
        """
        پردازش مکالمات زنده کاربر از طریق CRMSalesAssistantEngine
        """
        s_key = cls.get_session_key(platform, chat_id)
        wiz_session = wizard_sessions.get(s_key)

        # اگر کاربر در مرحله تایپ دستی محله در ویزارد بود:
        if wiz_session and wiz_session.get('awaiting_custom_district'):
            custom_district = user_text.strip()
            wiz_session['district'] = custom_district
            wiz_session['awaiting_custom_district'] = False
            wiz_session['step'] = 4
            deal_type = wiz_session.get('deal_type', 'sale')
            text = (
                f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۴ از ۵):</b>\n\n"
                f"📍 منطقه ثبت‌شده: <b>{custom_district}</b>\n\n"
                f"لطفاً <b>بازه متراژ و بودجه</b> مد نظر خود را انتخاب فرمایید:"
            )
            return {
                'type': 'text',
                'message': text,
                'reply_markup': cls.build_wizard_step4_markup(platform, deal_type)
            }

        # در غیر این صورت، هدایت به مغز مشاور ارشد املاک سقف (CRMSalesAssistantEngine)
        phone = user_phone or f"0912{str(chat_id)[-7:]}" if str(chat_id).isdigit() else "09120000000"
        result = CRMSalesAssistantEngine.process_client_turn(phone, user_text)

        # اگر فایل‌های تطابق یافته تولید شد:
        matched_props = result.get('matched_properties', [])
        if matched_props:
            cards = []
            for p_info in matched_props:
                prop = db.session.get(Property, p_info['property_id'])
                if prop:
                    cards.append({
                        'property': prop,
                        'card_text': p_info['card_text'],
                        'reply_markup': cls.build_property_action_markup(platform, prop.id)
                    })
            return {
                'type': 'crm_matches',
                'intro_message': result.get('message', ''),
                'cards': cards,
                'reply_markup': cls.build_main_keyboard(platform)
            }

        # در غیر این صورت پاسخ هدایت‌کننده مشاور ارشد ارسال می‌شود
        return {
            'type': 'text',
            'message': result.get('message', 'درود بر شما، در حال بررسی نیازمندی‌های شما هستم...'),
            'reply_markup': cls.build_main_keyboard(platform)
        }

    # =========================================================================
    # پردازش کلیک روی دکمه‌های شیشه‌ای (Callback Queries)
    # =========================================================================

    @classmethod
    def handle_callback_query(cls, platform: str, chat_id: Union[int, str], data: str, user_name: Optional[str] = None) -> Dict[str, Any]:
        """
        پردازش کلیه اکشن‌های دکمه‌ها در بله و تلگرام
        """
        s_key = cls.get_session_key(platform, chat_id)
        phone = f"0912{str(chat_id)[-7:]}" if str(chat_id).isdigit() else "09120000000"

        # ۱. مشاوره مستقیم با کارشناس ارشد
        if data == 'btn_crm_consult':
            res = CRMSalesAssistantEngine.start_onboarding(phone, user_name)
            return {
                'type': 'text',
                'message': res['message'],
                'reply_markup': cls.build_main_keyboard(platform)
            }

        # ۲. راهنمای کد فایل
        if data == 'btn_code_info':
            info_text = (
                "🔢 <b>راهنمای استعلام و پرزنت تصاویر با کد فایل:</b>\n\n"
                "هر فایل در سامانه سقف دارای یک <b>کد اختصاصی</b> (مانند <code>10001</code>) است.\n\n"
                "📌 هر زمان که با مشتری در حال گفتگو هستید یا فایلی در وب‌اپ سقف نظرتان را جلب کرد، "
                "کافیست <b>کد فایل را در همین چت ارسال نمایید</b> تا تمام تصاویر باکیفیت و مشخصات فنی آن "
                "بلافاصله برای شما ارسال شود."
            )
            return {'type': 'text', 'message': info_text, 'reply_markup': cls.build_main_keyboard(platform)}

        # ۳. آخرین فایل‌های فروش و اجاره
        if data in ['btn_latest_sale', 'btn_latest_rent']:
            deal_type = 'sale' if data == 'btn_latest_sale' else 'rent'
            deal_title = 'خرید و فروش' if deal_type == 'sale' else 'رهن و اجاره'
            props = (
                Property.query.filter_by(deal_type=deal_type)
                .filter(Property.status.notin_(['archived', 'sold']))
                .order_by(Property.created_at.desc())
                .limit(4)
                .all()
            )
            if not props:
                return {'type': 'text', 'message': f"⚠️ در حال حاضر فایلی در دسته {deal_title} یافت نشد."}

            cards = []
            for p in props:
                cards.append({
                    'property': p,
                    'card_text': cls.format_client_property_card(p, score=95),
                    'reply_markup': cls.build_property_action_markup(platform, p.id)
                })
            return {
                'type': 'crm_matches',
                'intro_message': f"📋 <b>آخرین فایل‌های {deal_title} در سامانه سقف:</b>",
                'cards': cards,
                'reply_markup': cls.build_main_keyboard(platform)
            }

        # ۴. اکشن‌های نظرسنجی و هماهنگی بازدید (Hot Lead)
        if data.startswith('act_visit_'):
            prop_id = int(data.replace('act_visit_', ''))
            prop = db.session.get(Property, prop_id)
            prop_code = prop.file_code if prop else str(prop_id)
            feedback_text = f"عالیه، من متقاضی هماهنگی بازدید حضوری برای فایل کد {prop_code} هستم"
            res = CRMSalesAssistantEngine.handle_feedback_and_qualification(phone, feedback_text)

            success_msg = (
                f"🌟 <b>درخواست بازدید حضوری برای فایل کد #{prop_code} با موفقیت ثبت شد!</b>\n\n"
                "یک هشدار فوری (Hot Lead) به کارشناس ارشد سقف مخابره گردید.\n"
                "کارشناس مربوطه طی کمتر از ۱۵ دقیقه جهت هماهنگی نهایی روز و ساعت بازدید با شما تماس حاصل خواهد نمود.\n\n"
                "از حسن اعتماد شما به مجموعه سقف سپاسگزاریم ⚜️"
            )
            return {'type': 'text', 'message': success_msg, 'reply_markup': cls.build_main_keyboard(platform)}

        if data.startswith('act_budget_'):
            prop_id = int(data.replace('act_budget_', ''))
            res = CRMSalesAssistantEngine.handle_feedback_and_qualification(phone, "قیمت و بودجه این فایل بالاست، فایل مناسب‌تر می‌خوام")
            reply_txt = res.get('client_message') or res.get('message') or "پیام شما دریافت گردید و فیلترهای بودجه تنظیم شد."
            return {
                'type': 'text',
                'message': reply_txt,
                'reply_markup': cls.build_main_keyboard(platform)
            }

        if data.startswith('act_loc_'):
            prop_id = int(data.replace('act_loc_', ''))
            res = CRMSalesAssistantEngine.handle_feedback_and_qualification(phone, "لوکیشن و محله این فایل مناسب من نیست")
            reply_txt = res.get('client_message') or res.get('message') or "پیام شما دریافت گردید و فیلترهای موقعیت تنظیم شد."
            return {
                'type': 'text',
                'message': reply_txt,
                'reply_markup': cls.build_main_keyboard(platform)
            }

        if data.startswith('act_photos_'):
            prop_id = int(data.replace('act_photos_', ''))
            prop = db.session.get(Property, prop_id)
            if prop:
                return {
                    'type': 'property_package',
                    'property': prop,
                    'card_text': cls.format_client_property_card(prop, score=92),
                    'reply_markup': cls.build_property_action_markup(platform, prop.id)
                }

        # ۵. جریان گام‌به‌گام ویزارد (Wizard Steps)
        if data == 'wiz_start':
            wizard_sessions[s_key] = {'step': 1}
            return {
                'type': 'edit_or_send',
                'message': (
                    "🎯 <b>ویزارد فیلترینگ و استخراج هوشمند املاک سقف (گام ۱ از ۵):</b>\n\n"
                    "لطفاً <b>نوع معامله</b> را انتخاب فرمایید:"
                ),
                'reply_markup': cls.build_wizard_step1_markup(platform)
            }

        if data in ['wiz_deal_sale', 'wiz_deal_rent']:
            deal = 'sale' if data == 'wiz_deal_sale' else 'rent'
            sess = wizard_sessions.setdefault(s_key, {})
            sess['deal_type'] = deal
            sess['step'] = 2
            deal_name = '🏷️ خرید و فروش' if deal == 'sale' else '🔑 رهن و اجاره'
            return {
                'type': 'edit_or_send',
                'message': (
                    f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۲ از ۵):</b>\n\n"
                    f"نوع معامله: <b>{deal_name}</b>\n\n"
                    f"لطفاً <b>نوع کاربری ملک</b> را تعیین فرمایید:"
                ),
                'reply_markup': cls.build_wizard_step2_markup(platform)
            }

        if data in ['wiz_type_apartment', 'wiz_type_villa', 'wiz_type_commercial']:
            ptype = 'apartment' if 'apartment' in data else ('villa' if 'villa' in data else 'commercial')
            pname = '🏢 آپارتمان مسکونی' if ptype == 'apartment' else ('🏡 ویلایی' if ptype == 'villa' else '🏬 تجاری/اداری')
            sess = wizard_sessions.setdefault(s_key, {})
            sess['prop_type'] = ptype
            sess['prop_title'] = pname
            sess['step'] = 3
            return {
                'type': 'edit_or_send',
                'message': (
                    f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۳ از ۵):</b>\n\n"
                    f"کاربری انتخابی: <b>{pname}</b>\n\n"
                    f"لطفاً <b>منطقه یا محله</b> مورد نظر خود را انتخاب کنید یا گزینه «✍️ تایپ نام محله» را بزنید:"
                ),
                'reply_markup': cls.build_wizard_step3_markup(platform)
            }

        if data.startswith('wiz_dist_'):
            sess = wizard_sessions.setdefault(s_key, {})
            if data == 'wiz_dist_custom':
                sess['awaiting_custom_district'] = True
                return {
                    'type': 'text',
                    'message': (
                        "✍️ <b>ورود دستی نام محله:</b>\n\n"
                        "لطفاً نام محله مورد نظر خود را در همین چت تایپ فرمایید (مثال: <code>فردوس</code>، <code>سازمان برنامه</code>، <code>نیاوران</code>):"
                    )
                }

            dist = data.replace('wiz_dist_', '').strip()
            sess['district'] = dist
            sess['step'] = 4
            deal = sess.get('deal_type', 'sale')
            return {
                'type': 'edit_or_send',
                'message': (
                    f"🎯 <b>ویزارد فیلترینگ و استخراج (گام ۴ از ۵):</b>\n\n"
                    f"📍 محله/منطقه انتخابی: <b>{dist}</b>\n\n"
                    f"لطفاً <b>بازه متراژ و بودجه</b> مد نظر را انتخاب فرمایید:"
                ),
                'reply_markup': cls.build_wizard_step4_markup(platform, deal)
            }

        if data.startswith('wiz_bud_'):
            sess = wizard_sessions.setdefault(s_key, {})
            bud_configs = {
                'wiz_bud_s1': {'min_area': 0, 'max_area': 80, 'max_price': 6_000_000_000, 'desc': 'متراژ تا ۸۰ م | بودجه تا ۶ م'},
                'wiz_bud_s2': {'min_area': 80, 'max_area': 110, 'max_price': 10_000_000_000, 'desc': 'متراژ ۸۰ تا ۱۱۰ م | ۶ تا ۱۰ م'},
                'wiz_bud_s3': {'min_area': 110, 'max_area': 150, 'max_price': 16_000_000_000, 'desc': 'متراژ ۱۱۰ تا ۱۵۰ م | ۱۰ تا ۱۶ م'},
                'wiz_bud_s4': {'min_area': 150, 'max_area': None, 'min_price': 16_000_000_000, 'desc': 'متراژ ۱۵۰+ م | ۱۶+ م'},
                'wiz_bud_r1': {'max_deposit': 500_000_000, 'max_rent': 15_000_000, 'desc': 'ودیعه تا ۵۰۰ م | اجاره تا ۱۵ م'},
                'wiz_bud_r2': {'max_deposit': 1_000_000_000, 'max_rent': 30_000_000, 'desc': 'ودیعه ۵۰۰ تا ۱ م | اجاره ۱۵ تا ۳۰ م'},
                'wiz_bud_r3': {'max_deposit': 2_000_000_000, 'max_rent': 50_000_000, 'desc': 'ودیعه ۱ تا ۲ م | اجاره ۳۰ تا ۵۰ م'},
                'wiz_bud_r4': {'min_deposit': 1_500_000_000, 'max_rent': 1, 'desc': 'رهن کامل (۱.۵ تا ۳ م)'},
                'wiz_bud_any': {'desc': 'بدون محدودیت'}
            }
            binfo = bud_configs.get(data, {'desc': 'نامحدود'})
            sess.update(binfo)
            sess['step'] = 5

            deal_str = '🏷️ خرید و فروش' if sess.get('deal_type') == 'sale' else '🔑 رهن و اجاره'
            return {
                'type': 'edit_or_send',
                'message': (
                    "🎯 <b>ویزارد فیلترینگ و استخراج (گام ۵ از ۵ - تأیید نهایی):</b>\n\n"
                    f"• 🏷️ نوع معامله: <b>{deal_str}</b>\n"
                    f"• 🏢 نوع کاربری: <b>{sess.get('prop_title', 'آپارتمان')}</b>\n"
                    f"• 📍 منطقه: <b>{sess.get('district', 'تهران')}</b>\n"
                    f"• 💰 بودجه و متراژ: <b>{sess.get('desc', 'نامحدود')}</b>\n\n"
                    "آیا برای آغاز جستجوی بلادرنگ دیتابیس و استخراج از دیوار آماده‌اید؟"
                ),
                'reply_markup': cls.build_wizard_step5_markup(platform)
            }

        if data == 'wiz_cancel':
            wizard_sessions.pop(s_key, None)
            return {
                'type': 'edit_or_send',
                'message': "❌ <b>فرآیند فیلترینگ و استخراج لغو شد.</b>\n\nجهت شروع مجدد، دستور /start را ارسال فرمایید.",
                'reply_markup': cls.build_main_keyboard(platform)
            }

        if data == 'wiz_exec':
            sess = wizard_sessions.pop(s_key, {})
            deal_type = sess.get('deal_type', 'sale')
            district = sess.get('district', 'تهران')
            district_clean = district if district and district != 'منطقه ۵' else None

            # جستجوی فایل‌های متناظر
            query = Property.query.filter(Property.status.notin_(['archived', 'sold']))
            if deal_type:
                query = query.filter(Property.deal_type == deal_type)
            if district_clean:
                query = query.filter(Property.district.contains(district_clean))
            if sess.get('max_price'):
                query = query.filter(Property.total_price <= sess['max_price'])

            matches = query.order_by(Property.created_at.desc()).limit(4).all()

            if not matches:
                # فال‌بک
                matches = Property.query.filter_by(deal_type=deal_type).limit(3).all()

            cards = []
            for p in matches:
                cards.append({
                    'property': p,
                    'card_text': cls.format_client_property_card(p, score=94),
                    'reply_markup': cls.build_property_action_markup(platform, p.id)
                })

            return {
                'type': 'crm_matches',
                'intro_message': f"🚀 <b>تعداد {len(matches)} فایل منطبق در منطقه {district} استخراج و آماده شد:</b>",
                'cards': cards,
                'reply_markup': cls.build_main_keyboard(platform)
            }

        return {'type': 'text', 'message': 'درخواست پردازش شد.', 'reply_markup': cls.build_main_keyboard(platform)}

    # =========================================================================
    # فرامین مدیریتی ارشد (/admin, /stats, /crawl)
    # =========================================================================

    @classmethod
    def handle_admin_commands(cls, platform: str, chat_id: Union[int, str], command: str) -> Optional[Dict[str, Any]]:
        """پردازش فرامین اختصاصی سوپرادمین"""
        if not cls.is_admin_user(platform, chat_id):
            return {
                'type': 'text',
                'message': (
                    "⛔ <b>دسترسی غیرمجاز!</b>\n\n"
                    "این دستورات صرفاً ویژه مدیر ارشد سامانه (Super Admin) می‌باشد."
                )
            }

        if command == '/admin':
            return {
                'type': 'text',
                'message': (
                    "👑 <b>کنسول مدیریت ارشد سقف (Super Admin Console)</b> 👑\n\n"
                    "درود بر مدیر ارشد سامانه سقف.\n\n"
                    "📊 <code>/stats</code> — دریافت آمار لحظه‌ای دیتابیس و متقاضیان\n"
                    "🕷️ <code>/crawl</code> — اجرای فوری تسک کراولینگ دیوار و شیپور\n\n"
                    "🌐 جهت ورود به پنل تحت وب:\n"
                    "http://127.0.0.1:5000/admin/dashboard"
                )
            }

        if command == '/stats':
            total_props = Property.query.count()
            sales = Property.query.filter_by(deal_type='sale').count()
            rents = Property.query.filter_by(deal_type='rent').count()
            divar_cnt = Property.query.filter_by(source='divar').count()
            sheypoor_cnt = Property.query.filter_by(source='sheypoor').count()
            clients_cnt = Client.query.count()
            c_status = crawler_manager.get_status()
            c_running = "در حال کراولینگ 🟢" if c_status.get('is_running') else "آماده‌به‌کار (Idle) ⚪"

            report = (
                "📊 <b>گزارش وضعیت جامع سقف (لحظه‌ای):</b>\n\n"
                f"🏛️ <b>کل فایل‌های دیتابیس:</b> {total_props} ملک\n"
                f"  ├ 🏷️ فروش: {sales}\n"
                f"  └ 🔑 رهن و اجاره: {rents}\n\n"
                f"🌐 <b>تفکیک منابع:</b> دیوار ({divar_cnt}) | شیپور ({sheypoor_cnt})\n"
                f"👥 <b>متقاضیان در CRM:</b> {clients_cnt} پرونده\n"
                f"🕷️ <b>وضعیت کراولر:</b> {c_running}\n"
            )
            return {'type': 'text', 'message': report}

        if command == '/crawl':
            success, msg = crawler_manager.start_crawl_task(
                sources=['divar', 'sheypoor'],
                categories=['buy-apartment', 'rent-apartment'],
                limit_per_cat=5
            )
            return {
                'type': 'text',
                'message': f"🕷️ <b>تسک کراولینگ فوری آغاز شد:</b>\n\n{msg}"
            }

        return None
