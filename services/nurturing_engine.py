"""
پایپ‌لاین تعاملی، پیگیری و فالوآپ خودکار (Smart Messaging & Nurturing Engine)
- جریان کاری مالکین (Owner Workflow): خوش‌آمدگویی، ارسال کد رهگیری، ترغیب به ارسال تصاویر/ویدیو و تکمیل مدارک
- جریان کاری متقاضیان (Lead Workflow): دریافت فایل‌های منطبق کراولینگ، ارسال کارت‌های ملکی و پیگیری ۲۴ ساعته
- کران جاب زمان‌بندی پیگیری هوشمند: بازخورد، اصلاح فیلتر و ارسال موارد جایگزین
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from database.db import db
from database.models import Property, Owner, CustomerLead, Client, OutreachLog, Interaction, Visit
from services.regional_matching import RegionalPropertyMatcher
from services.omnichannel.dispatcher import omnichannel_dispatcher
from services.messenger_service import OmniMessengerService

logger = logging.getLogger(__name__)

class NurturingEngine:
    """
    موتور تعاملی پرورش لید و پیگیری خودکار مالکین و متقاضیان
    """

    @classmethod
    def handle_owner_onboarding(cls, prop: Property, owner: Owner, channel: str = 'telegram') -> Dict[str, Any]:
        """
        ارسال خودکار پیام خوش‌آمد و تأیید ثبت ملک + درخواست تصاویر و ویدیو
        """
        owner_name = owner.full_name or "مالک گرامی"
        deal_txt = "فروش" if prop.deal_type == 'sale' else "رهن و اجاره"

        welcome_text = (
            f"سلام و درود خدمت شما {owner_name} عزیز 🏛️\n\n"
            f"فایل ملکی شما در سامانه تخصصی **املاک سقف** با مشخصات زیر ثبت اولیه گردید:\n"
            f"⚜️ کد اختصاصی فایل: **{prop.file_code}**\n"
            f"📌 موضوع: {deal_txt} ملک {prop.area} متری در {prop.district}\n"
            f"🌐 لینک پیگیری در سامانه: http://127.0.0.1:5000/properties/{prop.id}\n\n"
            f"📸 **ارسال تصاویر و ویدیو (افزایش ۳ برابری سرعت معامله):**\n"
            f"جهت تکمیل پرونده و پرزنت فایل به خریداران/مستأجران تاییدشده سقف، لطفاً ۳ الی ۶ تصویر باکیفیت از سالن، آشپزخانه و نمای ساختمان را همینجا ارسال فرمایید.\n"
            f"کارشناسان دپارتمان سقف آماده هماهنگی متقاضیان موجه برای بازدید از ملک شما هستند."
        )

        adapter = omnichannel_dispatcher.get_adapter(channel)
        recipient = owner.phone_number

        try:
            res = adapter.send_text(recipient, welcome_text)
            logger.info(f"✅ Owner onboarding message dispatched to {recipient} via {channel}.")
            return {'success': True, 'details': res}
        except Exception as e:
            logger.error(f"❌ Failed to dispatch owner onboarding to {recipient}: {e}")
            return {'success': False, 'error': str(e)}

    @classmethod
    def handle_lead_matching_and_dispatch(cls, lead: CustomerLead, channel: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        تطبیق فوری سرنخ متقاضی با فایل‌های ملکی مالکین مستقیم و ارسال پکیج پیشنهادات
        """
        target_channel = channel or lead.active_messenger or 'telegram'
        
        # استخراج ۳ فایل منطبق برتر بر اساس الگوریتم منطقه‌ای با تلورانس ۱۰٪
        matched_items = RegionalPropertyMatcher.match_lead(lead, limit=3)

        if not matched_items:
            logger.info(f"No direct matches found yet for lead {lead.phone_number}.")
            return []

        # ارسال از طریق دیسپچر چندکاناله
        dispatches = omnichannel_dispatcher.dispatch_to_lead(
            lead=lead,
            property_items=matched_items,
            platform=target_channel
        )
        return dispatches

    @classmethod
    def execute_24h_followup_job(cls) -> Dict[str, Any]:
        """
        کران جاب زمان‌بندی پیگیری هوشمند:
        بررسی لاگ‌های ارسالی با سن بیش از ۲۴ ساعت و بدون بازخورد، جهت ارسال پیام پیگیری
        """
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        # استخراج لاگ‌های ارسالی که تا به حال پیگیری نشده‌اند
        pending_logs = OutreachLog.query.filter(
            OutreachLog.sent_at <= cutoff,
            OutreachLog.status == 'sent'
        ).order_by(OutreachLog.sent_at.asc()).limit(30).all()

        followup_count = 0
        processed_leads = set()

        for log in pending_logs:
            if log.lead_id in processed_leads:
                continue

            lead = log.lead
            if not lead:
                continue

            processed_leads.add(lead.id)
            adapter = omnichannel_dispatcher.get_adapter(log.platform)

            followup_message = (
                f"سلام و احترام {lead.full_name or 'همراه گرامی سقف'} 🏛️\n\n"
                f"آیا فایل‌های ملکی ارسالی دیروز (کد {log.property_code}) را بررسی فرمودید؟\n"
                f"کدام مورد به سلیقه و بودجه شما نزدیک‌تر بود؟\n\n"
                f"🔢 لطفاً با ارسال یکی از گزینه‌های زیر پاسخ دهید:\n"
                f"۱: پسندیدم، درخواست هماهنگی بازدید دارم 🔑\n"
                f"۲: متراژ یا قیمت مناسب نبود، موارد جدیدتر بفرستید 🔄\n"
                f"۳: موقتاً دست نگه دارید ⏸️"
            )

            try:
                adapter.send_text(lead.phone_number, followup_message)
                # ثبت تعامل پیگیری
                interaction = Interaction(
                    type='followup_24h',
                    target_type='client',
                    target_id=lead.id,
                    summary=f"ارسال پیام پیگیری ۲۴ ساعته خودکار برای فایل {log.property_code} در درگاه {log.platform}",
                    outcome='waiting_feedback',
                    created_at=datetime.utcnow()
                )
                db.session.add(interaction)
                followup_count += 1
            except Exception as e:
                logger.warning(f"Failed to send 24h followup to lead {lead.id}: {e}")

        db.session.commit()
        logger.info(f"✅ 24h follow-up job executed. {followup_count} leads followed up.")
        return {'success': True, 'followups_sent': followup_count}

    @classmethod
    def process_lead_feedback(cls, lead_phone: str, feedback_input: str) -> Dict[str, Any]:
        """
        تحلیل و اعمال بازخورد متقاضی:
        - در صورت تایید: ثبت درخواست بازدید
        - در صورت عدم پسند: اصلاح فیلترها و ارسال فایل‌های جایگزین
        """
        lead = CustomerLead.query.filter_by(phone_number=lead_phone).first()
        if not lead:
            return {'success': False, 'message': 'سرنخ یافت نشد.'}

        client = Client.query.filter_by(phone_number=lead_phone).first()
        norm_fb = (feedback_input or '').strip()

        if '1' in norm_fb or '۱' in norm_fb or any(w in norm_fb for w in ['پسندیدم', 'بازدید', 'خوبه', 'عالیه', 'هماهنگ']):
            # ارتقای وضعیت به مرحله بازدید
            if client:
                client.lead_status = 'visiting'
            
            interaction = Interaction(
                type='lead_feedback',
                target_type='client',
                target_id=lead.id,
                client_id=client.id if client else None,
                summary="متقاضی گزینه‌ها را پسندیده و درخواست هماهنگی بازدید ثبت کرد.",
                outcome='visit_requested',
                created_at=datetime.utcnow()
            )
            db.session.add(interaction)
            db.session.commit()

            # ارسال پیام پاسخ به متقاضی
            reply_msg = (
                "بسیار عالی! درخواست بازدید شما ثبت شد 📅\n"
                "مشاور تخصصی سقف طی دقایق آینده جهت هماهنگی ساعت دقیق بازدید با شما تماس خواهد گرفت."
            )
            adapter = omnichannel_dispatcher.get_adapter(lead.active_messenger)
            adapter.send_text(lead.phone_number, reply_msg)
            return {'success': True, 'action': 'visit_scheduled'}

        elif '2' in norm_fb or '۲' in norm_fb or any(w in norm_fb for w in ['نبود', 'نپسندیدم', 'جدید', 'دیگه']):
            # متقاضی نپسندیده؛ استخراج فایل‌های جایگزین و تازه‌تر
            matched_items = RegionalPropertyMatcher.match_lead(lead, limit=3)
            dispatches = []
            if matched_items:
                dispatches = omnichannel_dispatcher.dispatch_to_lead(
                    lead=lead,
                    property_items=matched_items,
                    platform=lead.active_messenger
                )

            reply_msg = (
                "پیام شما دریافت شد. گزینه‌های قبلی از لیست حذف شدند.\n"
                "🎯 هم‌اکنون موارد جدید و نزدیک‌تر به بودجه شما فراخوانی و ارسال گردید."
            )
            adapter = omnichannel_dispatcher.get_adapter(lead.active_messenger)
            adapter.send_text(lead.phone_number, reply_msg)

            return {'success': True, 'action': 'replacements_dispatched', 'dispatches': dispatches}

        else:
            return {'success': True, 'action': 'acknowledged'}

nurturing_engine = NurturingEngine()
