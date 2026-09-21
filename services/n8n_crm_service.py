"""
=============================================================================
پایپلاین دوگانه CRM و اتوماسیون n8n پلتفرم سقف (Saghf n8n CRM Engine)
تفکیک هوشمند به دو دیتابیس CRM مجزا:
  ۱. پایگاه داده CRM مالکین و املاک (Properties & Owners CRM)
  ۲. پایگاه داده CRM مشتریان و متقاضیان (Buyers & Tenants CRM)
همراه با اتوماسیون فالوآپ ۲۴ ساعته و آلارم‌های دو رنگ ادمین در تلگرام
=============================================================================
"""

import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from database.db import db
from database.models import (
    Property, Owner, CustomerLead, OutreachLog, Visit,
    Interaction, Agent, CallRecord
)
from services.regional_matching import RegionalPropertyMatcher
from services.omnichannel.dispatcher import omnichannel_dispatcher
from config import Config

logger = logging.getLogger(__name__)

# جدول نگاشت درگاه‌ها به نام‌های فارسی
CHANNEL_NAMES_FA = {
    'voip': 'تماس تلفنی / سانترال VoIP',
    'sms': 'پیامک کوتاه (SMS Gateway)',
    'instagram': 'دایرکت اینستاگرام',
    'whatsapp': 'واتساپ (WhatsApp API)',
    'telegram': 'تلگرام (Telegram Bot)',
    'bale': 'پیام‌رسان بله (Bale API)',
    'eitaa': 'پیام‌رسان ایتا (Eitaa API)',
    'rubika': 'پیام‌رسان روبیکا (Rubika API)'
}

class PropertiesOwnersCRM:
    """
    پایگاه داده اول: CRM مالکین و املاک (Properties & Owners CRM)
    مدیریت پرونده‌های مالکین، مشخصات سندی، متادیتای ملک، مدارک و تصاویر
    """

    @classmethod
    def register_owner_property(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ثبت مشخصات ملک و مالک در دیتابیس CRM مالکین
        """
        phone = data.get('phone_number') or data.get('phone') or data.get('caller_phone') or data.get('caller_number') or data.get('from')
        channel = (data.get('channel') or data.get('platform_id') or 'voip').lower()
        sender_id = data.get('sender_id') or data.get('from') or phone

        if not phone:
            raise ValueError("شماره تماس مالک برای ثبت در CRM الزامی است.")

        # ۱. ثبت یا به‌روزرسانی پرونده مالک
        owner = Owner.query.filter_by(phone_number=phone).first()
        if not owner:
            owner = Owner(
                full_name=data.get('owner_name') or 'مالک محترم',
                phone_number=phone,
                secondary_phone=sender_id if sender_id != phone else None,
                urgency=data.get('urgency', 'high'),
                flexibility=data.get('flexibility', 'منعطف'),
                notes=f"ورودی خودکار از درگاه: {CHANNEL_NAMES_FA.get(channel, channel)} در تاریخ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
            )
            db.session.add(owner)
            db.session.commit()
        else:
            if data.get('owner_name') and owner.full_name == 'مالک محترم':
                owner.full_name = data['owner_name']
                db.session.commit()

        # ۲. ثبت یا استخراج متادیتای ملک
        district = data.get('district') or 'تهران'
        deal_type = data.get('deal_type') or 'sale'
        area = int(data.get('area') or data.get('min_area') or 100)
        price = int(data.get('total_price') or data.get('price') or data.get('max_budget') or 0)
        deposit = int(data.get('deposit') or data.get('max_deposit') or 0)
        rent = int(data.get('monthly_rent') or data.get('rent') or data.get('max_rent') or 0)
        deed_type = data.get('deed_status') or data.get('deed_type') or 'سند تک‌برگ شخصی'
        floor = int(data.get('floor') or 1)
        rooms = int(data.get('rooms') or (2 if area >= 90 else 1))
        features = data.get('features') or []

        # وضعیت مدیا (تصاویر / ویدیو)
        media_urls = data.get('media_urls') or data.get('images') or []
        media_status = 'received' if media_urls else 'pending'

        unique_file_code = f"saghf_{uuid.uuid4().hex[:6]}"
        property_title = f"آپارتمان {area} متری {district} ({deed_type})"

        new_prop = Property(
            source='direct_owner',
            source_id=unique_file_code,
            title=property_title,
            deal_type=deal_type,
            property_type=data.get('property_type', 'apartment'),
            city=data.get('city', 'تهران'),
            district=district,
            address=data.get('address') or f"تهران، منطقه {district}",
            total_price=price,
            deposit=deposit,
            monthly_rent=rent,
            area=area,
            rooms=rooms,
            floor=floor,
            has_parking='پارکینگ' in features,
            has_elevator='آسانسور' in features,
            has_warehouse='انباری' in features,
            has_balcony='بالکن' in features,
            features_json=json.dumps(features, ensure_ascii=False),
            description=f"ثبت خودکار اتوماسیون n8n از {CHANNEL_NAMES_FA.get(channel, channel)}. مشخصات سندی: {deed_type}. وضعیت مدارک: {media_status}.",
            images_json=json.dumps(media_urls if media_urls else ['/static/images/luxury/living_room.jpg']),
            status='verified',
            owner_id=owner.id
        )
        db.session.add(new_prop)
        db.session.commit()

        # ۳. ارسال خودکار پیام خوش‌آمد و لینک دریافت تصاویر/مدارک به پیام‌رسان مالک
        upload_link = f"http://127.0.0.1:5000/properties/{new_prop.id}"
        outreach_text = (
            f"🏛️ <b>سامانه مدیریت و فایلینگ املاک سقف</b>\n\n"
            f"مالک گرامی، فایل ملکی شما با مشخصات زیر با موفقیت در CRM املاک ثبت گردید:\n"
            f"▫️ کد پرونده: <b>{new_prop.file_code}</b> ({unique_file_code})\n"
            f"▫️ منطقه: <b>{district}</b> | متراژ: <b>{area} متر</b>\n"
            f"▫️ وضعیت سند: <b>{deed_type}</b>\n\n"
            f"📸 <b>درخواست بارگذاری تصاویر و مستندات:</b>\n"
            f"جهت ارزیابی کارشناسی و پرزنت VIP به خریداران منتخب، لطفاً تصاویر، ویدیو یا اسناد واحد را از طریق لینک اختصاصی زیر ارسال فرمایید یا در همین چت بفرستید:\n"
            f"👉 {upload_link}\n\n"
            f"مشاوران تخصصی سقف به زودی جهت هماهنگی با شما تماس خواهند گرفت."
        )

        dispatch_res = omnichannel_dispatcher.dispatch_direct_message(
            recipient=phone,
            message=outreach_text,
            platform=channel if channel in ['telegram', 'bale', 'eitaa', 'whatsapp', 'rubika'] else 'telegram'
        )

        # ۴. ارسال آلارم طلایی به پنل تلگرام ادمین
        TelegramAdminNotifier.send_gold_property_alarm(new_prop, owner, channel, deed_type, media_status)

        return {
            'success': True,
            'crm_type': 'properties_owners',
            'property_id': new_prop.id,
            'file_code': new_prop.file_code,
            'owner_id': owner.id,
            'owner_phone': phone,
            'channel': channel,
            'deed_type': deed_type,
            'media_status': media_status,
            'upload_link': upload_link,
            'omnichannel_dispatch': dispatch_res
        }


class BuyersTenantsCRM:
    """
    پایگاه داده دوم: CRM مشتریان و متقاضیان (Buyers & Tenants CRM)
    مدیریت پروفایل خریداران/مستأجران، بودجه، اولویت‌ها، پیشنهادات تطابق‌یافته و نرتورینگ
    """

    @classmethod
    def register_or_update_lead(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        ثبت یا به‌روزرسانی پرونده متقاضی در CRM مشتریان و اجرای موتور تطبیق
        """
        phone = data.get('phone_number') or data.get('phone') or data.get('caller_phone') or data.get('caller_number') or data.get('from')
        channel = (data.get('preferred_channel') or data.get('channel') or data.get('platform_id') or 'voip').lower()
        active_messenger = channel if channel in ['telegram', 'bale', 'eitaa', 'whatsapp', 'rubika'] else 'telegram'

        if not phone:
            raise ValueError("شماره تماس مشتری برای ثبت در CRM متقاضیان الزامی است.")

        lead = CustomerLead.query.filter_by(phone_number=phone).first()
        districts = data.get('districts') or data.get('target_districts') or ([data.get('district')] if data.get('district') else ['پونک', 'سعادت‌آباد'])
        deal_type = data.get('deal_type') or 'rent'
        budget = int(data.get('max_budget') or data.get('budget') or data.get('total_price') or data.get('price') or 0)
        deposit = int(data.get('max_deposit') or data.get('deposit') or 0)
        rent = int(data.get('max_rent') or data.get('monthly_rent') or data.get('rent') or 0)
        min_area = int(data.get('min_area') or data.get('area') or 80)
        features = data.get('features') or []

        if not lead:
            lead = CustomerLead(
                phone_number=phone,
                full_name=data.get('full_name') or f"مشتری {CHANNEL_NAMES_FA.get(channel, channel)}",
                deal_type=deal_type,
                preferred_districts_json=json.dumps(districts, ensure_ascii=False),
                min_budget=int(budget * 0.7) if budget else 0,
                max_budget=budget,
                max_deposit=deposit,
                max_rent=rent,
                min_area=min_area,
                preferred_features_json=json.dumps(features, ensure_ascii=False),
                active_messenger=active_messenger,
                last_interaction_at=datetime.utcnow()
            )
            db.session.add(lead)
            db.session.commit()
        else:
            # به‌روزرسانی پارامترهای جدید
            lead.deal_type = deal_type
            lead.preferred_districts_json = json.dumps(districts, ensure_ascii=False)
            if budget > 0: lead.max_budget = budget
            if deposit > 0: lead.max_deposit = deposit
            if rent > 0: lead.max_rent = rent
            if min_area > 0: lead.min_area = min_area
            if features: lead.preferred_features_json = json.dumps(features, ensure_ascii=False)
            lead.active_messenger = active_messenger
            lead.last_interaction_at = datetime.utcnow()
            db.session.commit()

        # ۲. اجرای موتور تطبیق منطقه‌ای و استخراج گزینه‌های کارشناسی
        matched_items = RegionalPropertyMatcher.match_lead(lead, limit=3)

        # ۳. ارسال کارت‌های ملکی منتخب به پیام‌رسان مشتری
        dispatch_results = []
        if matched_items:
            dispatch_results = omnichannel_dispatcher.dispatch_to_lead(
                lead=lead,
                property_items=matched_items,
                platform=active_messenger
            )

        # ۴. ارسال آلارم سبز به پنل تلگرام ادمین
        TelegramAdminNotifier.send_green_lead_alarm(lead, channel, matched_items)

        return {
            'success': True,
            'crm_type': 'buyers_tenants',
            'lead_id': lead.id,
            'phone_number': phone,
            'channel': channel,
            'deal_type': deal_type,
            'matched_count': len(matched_items),
            'matched_properties': matched_items,
            'dispatch_results': dispatch_results
        }


class SmartFollowupEngine:
    """
    موتور نرتورینگ و پیگیری زمان‌بندی‌شده ۲۴ ساعته (Follow-up Cron Job)
    ارزیابی بازخورد مشتری، بهینه‌سازی تگ‌ها و زمان‌بندی بازدید حضوری
    """

    @classmethod
    def run_daily_followup(cls) -> Dict[str, Any]:
        """
        اجرای کران‌جاب ۲۴ ساعته: بررسی لیدهایی که فایل برایشان ارسال شده ولی بازدید ثبت نکرده‌اند
        """
        now = datetime.utcnow()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_48h = now - timedelta(hours=48)

        # لیدهایی که بین ۲۴ تا ۴۸ ساعت پیش پکیج دریافت کرده‌اند
        recent_logs = OutreachLog.query.filter(
            OutreachLog.sent_at >= cutoff_48h,
            OutreachLog.sent_at <= cutoff_24h,
            OutreachLog.status == 'sent'
        ).all()

        followed_leads = set()
        followup_count = 0

        for log in recent_logs:
            lead_id = log.lead_id
            if lead_id in followed_leads:
                continue

            lead = CustomerLead.query.get(lead_id)
            if not lead:
                continue

            # بررسی اینکه آیا بازدید قبلاً ثبت شده یا خیر
            # (اگر مشتری قبلاً قرار بازدید گذاشته، نیاز به پیام پیگیری تکراری ندارد)
            has_visit = Visit.query.filter_by(client_id=lead.id).first()
            if has_visit:
                continue

            # ارسال پیام پیگیری هوشمند و مشاوره
            followup_msg = (
                f"سلام و درود جناب/سرکار {lead.full_name} عزیز ⚜️\n"
                f"امیدوارم روز خوبی داشته باشید. دیروز فایل‌های ملکی منطبق با سلیقه شما در منطقه {lead.preferred_districts[0] if lead.preferred_districts else 'منتخب'} تقدیم گردید.\n\n"
                f"❓ آیا فرصت کردید گزینه‌ها را بررسی بفرمایید؟ کدام مورد بیشتر به دلخواه شما نزدیک بود؟\n\n"
                f"▫️ در صورت تمایل به بازدید حضوری، عدد ۱ را ارسال فرمایید.\n"
                f"▫️ در صورت تمایل به تغییر بازه قیمت، متراژ یا محله، مشخصات جدید را برای ما بفرستید تا موارد تازه‌تر فورا گلچین شوند."
            )

            try:
                adapter = omnichannel_dispatcher.get_adapter(lead.active_messenger)
                res = adapter.send_text(lead.phone_number, followup_msg)
                if res.get('success'):
                    followed_leads.add(lead_id)
                    followup_count += 1
            except Exception as e:
                logger.error(f"Error in smart follow-up dispatch to {lead.phone_number}: {e}")

        return {
            'success': True,
            'processed_count': followup_count,
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S')
        }

    @classmethod
    def process_lead_feedback(cls, phone_number: str, feedback_text: str) -> Dict[str, Any]:
        """
        تحلیل پاسخ مشتری به پیام پیگیری:
        - اگر قصد بازدید داشت -> ثبت در جدول Visit و اعلام فوری به ادمین
        - اگر قیمت بالا بود یا منطقه نامناسب بود -> حذف تگ‌های نامناسب، اصلاح CRM و ارسال موارد جایگزین
        """
        lead = CustomerLead.query.filter_by(phone_number=phone_number).first()
        if not lead:
            return {'success': False, 'message': 'لید یافت نشد.'}

        text = feedback_text.strip()
        
        # ۱. قصد بازدید
        if any(w in text for w in ['۱', '1', 'بازدید', 'ببینم', 'قرار', 'هماهنگ']):
            # ایجاد رکورد بازدید پیشنهادی برای فردا عصر
            scheduled_date = datetime.utcnow() + timedelta(days=1, hours=4)
            visit = Visit(
                property_id=1, # یا آخرین ملک دیده شده
                client_id=lead.id,
                scheduled_time=scheduled_date,
                status='scheduled',
                feedback=f"درخواست بازدید خودکار از طریق پیام‌رسان {lead.active_messenger}: {text}",
                readiness_to_buy=4
            )
            db.session.add(visit)
            db.session.commit()

            # اطلاع فوری به ادمین در تلگرام
            admin_msg = (
                f"🎯 <b>درخواست بازدید فوری مشتری (از فالوآپ ۲۴ ساعته)</b>\n\n"
                f"👤 مشتری: <b>{lead.full_name}</b> ({lead.phone_number})\n"
                f"📱 پلتفرم: <b>{lead.active_messenger}</b>\n"
                f"💬 پیام مشتری: <i>«{text}»</i>\n"
                f"⏰ زمان پیشنهادی: فردا ساعت ۱۸:۰۰\n"
            )
            TelegramAdminNotifier.send_raw_admin_message(admin_msg)

            return {
                'success': True,
                'action': 'visit_scheduled',
                'message': 'درخواست بازدید ثبت و به مشاور اختصاصی ارجاع شد.'
            }

        # ۲. درخواست تغییر فیلترها (قیمت بالا یا متراژ دیگر)
        else:
            # فراخوانی موارد جایگزین جدیدتر
            replacement_items = RegionalPropertyMatcher.match_lead(lead, limit=2)
            if replacement_items:
                omnichannel_dispatcher.dispatch_to_lead(lead, replacement_items, lead.active_messenger)

            return {
                'success': True,
                'action': 'criteria_adjusted_replacements_sent',
                'replacement_count': len(replacement_items)
            }


class TelegramAdminNotifier:
    """
    لایه کنترل و مانیتورینگ ادمین در پوسته تلگرام (Telegram Admin Interface)
    ارسال آلارم‌های دو رنگ (سبز و طلایی) و دکمه‌های اقدام مستقیم
    """

    @classmethod
    def send_gold_property_alarm(cls, prop: Property, owner: Owner, channel: str, deed_type: str, media_status: str):
        """
        🟡 آلارم طلایی: ثبت ملک جدید توسط مالک
        """
        deal_fa = 'فروش' if prop.deal_type == 'sale' else 'رهن و اجاره'
        price_str = f"{prop.total_price / 1_000_000_000:.2f} میلیارد تومان" if prop.deal_type == 'sale' else f"رهن: {prop.deposit/1_000_000:.0f}م | اجاره: {prop.monthly_rent/1_000_000:.0f}م"

        text = (
            f"🟡 <b>[آلارم طلایی] ثبت ملک جدید در CRM مالکین</b>\n\n"
            f"🏢 عنوان: <b>{prop.title}</b>\n"
            f"▫️ کد فایل: <code>{prop.file_code}</code>\n"
            f"▫️ منطقه: <b>{prop.district}</b> | متراژ: <b>{prop.area} متر</b>\n"
            f"▫️ شرایط: <b>{deal_fa}</b> ({price_str})\n"
            f"▫️ سند: <b>{deed_type}</b>\n"
            f"▫️ وضعیت مدارک/تصاویر: <b>{'✅ دریافت شد' if media_status == 'received' else '⏳ در انتظار بارگذاری'}</b>\n\n"
            f"👤 مالک: <b>{owner.full_name}</b> (<code>{owner.phone_number}</code>)\n"
            f"📡 درگاه ورودی: <b>{CHANNEL_NAMES_FA.get(channel, channel)}</b>"
        )

        buttons = [
            [
                {'text': '📋 مشاهده پرونده در وب', 'url': f"http://127.0.0.1:5000/properties/{prop.id}"},
                {'text': '📱 باز کردن Mini App', 'web_app': {'url': 'http://127.0.0.1:5000/admin/telegram-mini-app'}}
            ],
            [
                {'text': f"💬 ورود به چت {channel}", 'url': cls._build_chat_url(channel, owner.phone_number)},
                {'text': '📞 تماس سریع VoIP', 'url': f"tel:{owner.phone_number}"}
            ]
        ]

        cls._send_telegram_notification(text, buttons)

    @classmethod
    def send_green_lead_alarm(cls, lead: CustomerLead, channel: str, matched_items: List[Dict[str, Any]]):
        """
        🟢 آلارم سبز: مشتری و متقاضی جدید با پیش‌نمایش تطابق
        """
        deal_fa = 'خرید' if lead.deal_type == 'sale' else 'رهن و اجاره'
        budget_str = f"حداکثر {lead.max_budget / 1_000_000_000:.1f} میلیارد" if lead.deal_type == 'sale' else f"ودیعه: {lead.max_deposit/1_000_000:.0f}م"

        matches_summary = ""
        for idx, item in enumerate(matched_items[:3], 1):
            matches_summary += f"\n  {idx}. {item.get('title', 'ملک')} (کد {item.get('ad_code')})"

        text = (
            f"🟢 <b>[آلارم سبز] متقاضی جدید در CRM مشتریان</b>\n\n"
            f"👤 نام: <b>{lead.full_name}</b>\n"
            f"📞 شماره تماس: <code>{lead.phone_number}</code>\n"
            f"▫️ نوع تقاضا: <b>{deal_fa}</b> | حداقل متراژ: <b>{lead.min_area} متر</b>\n"
            f"▫️ بودجه: <b>{budget_str}</b>\n"
            f"▫️ مناطق هدف: <b>{'، '.join(lead.preferred_districts)}</b>\n"
            f"📡 درگاه ارتباطی: <b>{CHANNEL_NAMES_FA.get(channel, channel)}</b>\n\n"
            f"⚡ <b>{len(matched_items)} فایل طلایی فوری منطبق شد:</b>"
            f"{matches_summary if matches_summary else ' در حال استخراج از کراولر...'}"
        )

        buttons = [
            [
                {'text': '👥 پرونده متقاضی در CRM', 'url': f"http://127.0.0.1:5000/clients/"},
                {'text': '📱 وب‌اپ تلگرام', 'web_app': {'url': 'http://127.0.0.1:5000/admin/telegram-mini-app'}}
            ],
            [
                {'text': f"💬 ارسال مستقیم در {lead.active_messenger}", 'url': cls._build_chat_url(lead.active_messenger, lead.phone_number)},
                {'text': '📞 تماس مستقیم', 'url': f"tel:{lead.phone_number}"}
            ]
        ]

        cls._send_telegram_notification(text, buttons)

    @classmethod
    def send_raw_admin_message(cls, text: str):
        cls._send_telegram_notification(text, [])

    @classmethod
    def _build_chat_url(cls, platform: str, phone: str) -> str:
        clean_phone = phone.replace('+', '').replace(' ', '')
        if clean_phone.startswith('0'):
            intl_phone = '98' + clean_phone[1:]
        else:
            intl_phone = clean_phone

        if platform == 'whatsapp':
            return f"https://wa.me/{intl_phone}"
        elif platform == 'bale':
            return f"bale://user?phone={clean_phone}"
        elif platform == 'eitaa':
            return f"https://eitaa.com/{clean_phone}"
        elif platform == 'rubika':
            return f"https://rubika.ir"
        else:
            return f"https://t.me/+{intl_phone}"

    @classmethod
    def _send_telegram_notification(cls, text: str, buttons: List[List[Dict[str, Any]]]):
        """
        ارسال به کانال یا ادمین تلگرام
        """
        try:
            from telegram_bot.bot import get_bot
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
            bot = get_bot()

            reply_markup = None
            if buttons:
                reply_markup = InlineKeyboardMarkup()
                for row in buttons:
                    row_btns = []
                    for b in row:
                        if 'web_app' in b:
                            row_btns.append(InlineKeyboardButton(text=b['text'], web_app=WebAppInfo(url=b['web_app']['url'])))
                        else:
                            row_btns.append(InlineKeyboardButton(text=b['text'], url=b.get('url', 'http://127.0.0.1:5000')))
                    reply_markup.row(*row_btns)

            target_chat_id = Config.ADMIN_TELEGRAM_ID or Config.TELEGRAM_CHANNEL_ID
            if target_chat_id:
                bot.send_message(
                    chat_id=target_chat_id,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
        except Exception as e:
            logger.error(f"Error sending Telegram admin notification: {e}")

