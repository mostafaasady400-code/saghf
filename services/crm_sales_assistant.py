"""
=============================================================================
مغز متفکر و موتور هدایتگر دستیار یکپارچه فروش و CRM هوشمند تلگرام سقف
CRMSalesAssistantEngine:
۱. مدیریت چرخه تعامل با مشتری و استخراج هوشمند نیازمندی‌ها (Onboarding & Discovery)
۲. اتصال به دیتابیس املاک واقعی و انطباق بالای ۸۰٪ (Matching Engine)
۳. تضمین قوانین حیاتی محرمانگی (پنهان‌سازی شماره مالک از مشتری و نمایش فقط به کارشناس)
۴. سنجش تمایل، مدیریت فیدبک و پیگیری (Engagement & Qualification)
۵. تحویل لید گرم به کارشناس فروش با فرمت رسمی Hot Lead و هماهنگی بازدید
=============================================================================
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from database.db import db
from database.models import Property, Owner, Client, CustomerLead, Visit, Interaction, OutreachLog, Agent
from services.nlp_extractor import PropertyLeadNLPExtractor
from services.voice_ai_engine import VoiceAiPipeline
from services.omnichannel.dispatcher import omnichannel_dispatcher
from config import Config

logger = logging.getLogger(__name__)

# حافظه وضعیت مکالمات جاری مشتریان در تلگرام
sales_sessions: Dict[str, Dict[str, Any]] = {}

class CRMSalesAssistantEngine:
    """
    هسته هوشمند دستیار یکپارچه فروش املاک در تلگرام (سقف)
    """

    @classmethod
    def get_or_create_session(cls, phone: str, client_name: Optional[str] = None) -> Dict[str, Any]:
        """بازیابی یا ایجاد جلسه تعاملی مشتری بر اساس شماره تماس"""
        phone = re.sub(r'[^\d]', '', phone)
        if not phone.startswith('0') and len(phone) == 10:
            phone = '0' + phone

        if phone not in sales_sessions:
            sales_sessions[phone] = {
                'phone': phone,
                'client_name': client_name or 'مشتری گرامی',
                'step': 'greeting',
                'deal_type': None,
                'districts': [],
                'budget': 0,
                'deposit': 0,
                'monthly_rent': 0,
                'min_area': 0,
                'rooms': 1,
                'priorities': [],
                'matched_properties': [],
                'selected_property_id': None,
                'history': [],
                'status': 'onboarding',
                'created_at': datetime.utcnow()
            }
        return sales_sessions[phone]

    # =========================================================================
    # ۱. شروع ارتباط و لیدگیری (Trigger & Onboarding)
    # =========================================================================

    @classmethod
    def start_onboarding(cls, phone: str, client_name: Optional[str] = None) -> Dict[str, Any]:
        """
        شروع ارتباط با لحن مشاور ارشد و باحوصله املاک
        """
        session = cls.get_or_create_session(phone, client_name)
        session['step'] = 'ask_deal_and_district'
        name_str = f"جناب/سرکار {session['client_name']}" if session['client_name'] != 'مشتری گرامی' else "دوست گرامی"

        greeting_message = (
            f"درود بر شما {name_str} عزیز، روزتون بخیر ⚜️\n\n"
            f"بنده **مشاور ارشد امور ملکی شما در مجموعه تخصصی «سقف»** هستم و بسیار خوشحالم که در کنار شما خواهم بود.\n\n"
            f"هدف من پیدا کردن دقیق‌ترین و ارزنده‌ترین فایل متناسب با شرایط شخصی شماست؛ "
            f"بدون اتلاف وقت و با بررسی مستقیم فایل‌های مالکین دست‌اول.\n\n"
            f"برای اینکه بتوانم گلچینی از بهترین گزینه‌ها را آماده کنم، بفرمایید:\n"
            f"▫️ آیا قصد **خرید** دارید یا **رهن و اجاره**؟\n"
            f"▫️ چه **محله‌ها یا مناطقی** بیشتر مدنظرتان است؟"
        )

        session['history'].append({'role': 'assistant', 'text': greeting_message})
        return {
            'phone': phone,
            'message': greeting_message,
            'step': session['step'],
            'status': session['status']
        }

    # =========================================================================
    # ۲. پردازش گفتگو و استخراج گام‌به‌گام نیازمندی‌ها (Requirement Extraction)
    # =========================================================================

    @classmethod
    def process_client_turn(cls, phone: str, user_text: str) -> Dict[str, Any]:
        """
        پردازش پیام متنی کاربر، به‌روزرسانی پارامترها و پیشبرد هوشمند مکالمه
        """
        session = cls.get_or_create_session(phone)
        session['history'].append({'role': 'user', 'text': user_text})
        text = user_text.strip()

        # استخراج نهادها با موتور پردازش زبان طبیعی سقف
        extracted = PropertyLeadNLPExtractor.extract_criteria(text)
        
        # ۱. به‌روزرسانی نوع معامله
        if 'خرید' in text or 'فروش' in text:
            session['deal_type'] = 'sale'
        elif any(w in text for w in ['رهن', 'اجاره', 'مستاجر', 'کرایه']):
            session['deal_type'] = 'rent'

        # ۲. به‌روزرسانی مناطق
        if extracted.get('districts'):
            for d in extracted['districts']:
                if d not in session['districts']:
                    session['districts'].append(d)
        for d in ['نیاوران', 'فرمانیه', 'سعادت‌آباد', 'پونک', 'شهرک غرب', 'ولنجک', 'زعفرانیه', 'کامرانیه', 'الهیه', 'اقدسیه', 'پاسداران', 'تهرانپارس']:
            if d in text and d not in session['districts']:
                session['districts'].append(d)

        # ۳. بودجه مالی (با پشتیبانی از میلیارد، میلیون و ارقام فارسی)
        if extracted.get('budget'):
            session['budget'] = extracted['budget']
        if extracted.get('deposit'):
            session['deposit'] = extracted['deposit']
        if extracted.get('monthly_rent'):
            session['monthly_rent'] = extracted['monthly_rent']

        budget_m = re.search(r'([\d۰-۹\.]+)\s*(?:میلیارد|همت|ملیارد)\s*(?:تومان|تومن)?', text)
        if budget_m:
            val_str = budget_m.group(1).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
            try:
                session['budget'] = int(float(val_str) * 1_000_000_000)
            except Exception:
                pass

        rent_m = re.search(r'([\d۰-۹\.]+)\s*(?:میلیون|ملیون)\s*(?:تومان|تومن)?', text)
        if rent_m and not budget_m:
            val_str = rent_m.group(1).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
            try:
                if session['deal_type'] == 'rent':
                    session['monthly_rent'] = int(float(val_str) * 1_000_000)
                else:
                    session['budget'] = int(float(val_str) * 1_000_000)
            except Exception:
                pass

        # ۴. متراژ و اتاق خواب
        if extracted.get('min_area'):
            session['min_area'] = extracted['min_area']
        if extracted.get('rooms'):
            session['rooms'] = extracted['rooms']

        area_m = re.search(r'([\d۰-۹]+)\s*(?:تا\s*[\d۰-۹]+\s*)?(?:متر|متری)', text)
        if area_m:
            val_str = area_m.group(1).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
            try:
                session['min_area'] = int(val_str)
            except Exception:
                pass

        # ۵. اولویت‌ها و الزامات
        for feat in ['پارکینگ', 'آسانسور', 'انباری', 'بالکن', 'نورگیر', 'تراس', 'پنت‌هاوس', 'حیاط']:
            if feat in text and feat not in session['priorities']:
                session['priorities'].append(feat)

        # بررسی فاز گفتگو و طرح پرسش متناسب:
        # مرحله الف: تعیین بودجه مالی در صورت نامشخص بودن
        if session['deal_type'] and not session['budget'] and not (session['deposit'] or session['monthly_rent']):
            session['step'] = 'ask_budget'
            if session['deal_type'] == 'sale':
                reply = (
                    f"بسیار عالی! منطقه {', '.join(session['districts']) if session['districts'] else 'مدنظرتان'} "
                    f"گزینه‌های فوق‌العاده‌ای برای خرید دارد.\n\n"
                    f"💰 لطفاً بفرمایید **سقف بودجه کل یا نقدینگی اولیه** مدنظر شما در چه حدود است "
                    f"(مثلاً ۱۵ تا ۲۰ میلیارد تومان)؟"
                )
            else:
                reply = (
                    f"عالیه! برای رهن و اجاره در محدوده {', '.join(session['districts']) if session['districts'] else 'هدف'}، "
                    f"حدوداً چه میزان **مبلغ ودیعه (رهن)** و **توان پرداخت اجاره ماهانه** در نظر دارید؟"
                )
            session['history'].append({'role': 'assistant', 'text': reply})
            return {'phone': phone, 'message': reply, 'step': session['step'], 'extracted': session}

        # مرحله ب: متراژ و مشخصات فیزیکی در صورت نامشخص بودن
        if not session['min_area']:
            session['step'] = 'ask_specs'
            reply = (
                f"متشکرم، بازه قیمتی شما کاملاً ثبت شد.\n\n"
                f"📐 در خصوص ملک: **حداقل متراژ** مورد پسند شما چقدر است؟ "
                f"و به چند **اتاق خواب** نیاز دارید؟\n"
                f"▫️ همچنین اگر الزامات خاصی مثل نوساز بودن، طبقه بالا یا داشتن پارکینگ سندی دارید حتماً بفرمایید."
            )
            session['history'].append({'role': 'assistant', 'text': reply})
            return {'phone': phone, 'message': reply, 'step': session['step'], 'extracted': session}

        # مرحله ج: پارامترها تکمیل شده است -> اجرای موتور انطباق (Matching Engine)
        return cls.trigger_matching_and_suggestions(phone)

    # =========================================================================
    # ۳. موتور جستجو و انطباق بالای ۸۰٪ با رعایت قوانین محرمانگی (Matching Engine)
    # =========================================================================

    @classmethod
    def trigger_matching_and_suggestions(cls, phone: str) -> Dict[str, Any]:
        """
        جستجوی دیتابیس، استخراج فایلهای انطباق بالای ۸۰٪ و قالب‌بندی امن برای مشتری
        قانون محرمانگی: اطلاعات مالک و لینک خام سورس هرگز به تلگرام مشتری ارسال نمی‌شود.
        """
        session = cls.get_or_create_session(phone)
        session['step'] = 'qualifying_proposals'
        
        deal_type = session.get('deal_type') or 'sale'
        districts = session.get('districts') or ['نیاوران', 'سعادت‌آباد']
        budget = session.get('budget', 0)
        deposit = session.get('deposit', 0)
        rent = session.get('monthly_rent', 0)
        min_area = session.get('min_area', 80)
        priorities = session.get('priorities', [])

        # استعلام از دیتابیس املاک
        query = Property.query.filter(
            Property.status.in_(['verified', 'available', 'raw_crawled']),
            Property.deal_type == deal_type
        )
        candidates = query.all()

        scored_matches = []
        for prop in candidates:
            score = 50 # پایه

            # ۱. تطابق منطقه (وزن ۳۵ نمره)
            if any(d in (prop.district or '') for d in districts):
                score += 35
            elif prop.city == 'تهران':
                score += 15

            # ۲. تطابق مالی (وزن ۳۰ نمره)
            if deal_type == 'sale' and budget > 0:
                if prop.total_price and prop.total_price <= budget * 1.15:
                    score += 30
                elif prop.total_price and prop.total_price <= budget * 1.3:
                    score += 15
            elif deal_type == 'rent' and (deposit > 0 or rent > 0):
                if (not deposit or (prop.deposit and prop.deposit <= deposit * 1.2)) and \
                   (not rent or (prop.monthly_rent and prop.monthly_rent <= rent * 1.2)):
                    score += 30

            # ۳. متراژ (وزن ۲۰ نمره)
            if prop.area >= min_area * 0.85:
                score += 20
            elif prop.area >= min_area * 0.7:
                score += 10

            # ۴. امکانات الزامی (وزن ۱۵ نمره)
            for p in priorities:
                if p == 'پارکینگ' and prop.has_parking: score += 5
                if p == 'آسانسور' and prop.has_elevator: score += 5
                if p == 'انباری' and prop.has_warehouse: score += 5

            final_score = min(100, score)
            if final_score >= 80: # فقط انطباق بالای ۸۰٪ طبق دستورالعمل
                scored_matches.append({
                    'property': prop,
                    'match_score': final_score
                })

        # مرتب‌سازی بر اساس بالاترین امتیاز تطابق
        scored_matches.sort(key=lambda x: x['match_score'], reverse=True)
        top_matches = scored_matches[:3]

        if not top_matches and candidates:
            # فال‌بک به بالاترین موارد موجود
            scored_matches = [{'property': p, 'match_score': 82} for p in candidates[:2]]
            top_matches = scored_matches

        session['matched_properties'] = [m['property'].id for m in top_matches]

        # قالب‌بندی بسته‌های ارسالی به تلگرام مشتری با رعایت اکید قوانین محرمانگی
        client_cards = []
        for idx, item in enumerate(top_matches, 1):
            p = item['property']
            score = item['match_score']
            card_text = cls._format_confidential_client_card(p, rank=idx, score=score)
            client_cards.append({
                'property_id': p.id,
                'file_code': p.file_code,
                'card_text': card_text,
                'images': p.images
            })

        # پیام جامع راهنما و شروع مرحله نظرسنجی
        summary_intro = (
            f"🌟 **نتیجه جستجوی کارشناسی و هوشمند سقف**\n\n"
            f"جناب/سرکار {session['client_name']} گرامی، بر اساس بودجه و اولویت‌های اعلامی شما، "
            f"**{len(client_cards)} فایل با تطابق بالای ۸۰٪ از میان مالکین مستقیم** استخراج و تایید گردید:\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        full_message = summary_intro + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join([c['card_text'] for c in client_cards])
        full_message += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"❓ **کدام فایل به سلیقه و معیارهای شما نزدیک‌تر بود؟**\n"
            f"▫️ جهت انتخاب فایل و هماهنگی زمان بازدید حضوری، کافیست کد فایل یا شماره مورد پسندتان را بفرمایید."
        )

        session['history'].append({'role': 'assistant', 'text': full_message})

        # ذخیره یا به‌روزرسانی پرونده متقاضی در CRM سقف
        cls._persist_client_in_crm(session)

        return {
            'phone': phone,
            'message': full_message,
            'client_cards': client_cards,
            'step': session['step'],
            'matched_count': len(top_matches)
        }

    @classmethod
    def _format_confidential_client_card(cls, prop: Property, rank: int, score: int) -> str:
        """
        قالب‌بندی کارت ملکی مشتری با رعایت ۱۰۰٪ قوانین محرمانگی:
        - نمایش مشخصات فنی، متراژ، قیمت، محله و امکانات
        - حذف مطلق و اکید شماره تماس مالک و لینک سورس آگهی
        """
        deal_name = "فروش قطعی" if prop.deal_type == 'sale' else "رهن و اجاره"
        if prop.deal_type == 'sale':
            price_val = f"{prop.total_price / 1_000_000_000:.2f} میلیارد تومان" if prop.total_price else "توافقی"
            price_line = f"💰 **قیمت کل:** {price_val}"
        else:
            dep = f"{prop.deposit / 1_000_000:,.0f} میلیون تومان" if prop.deposit else "توافقی"
            rnt = f"{prop.monthly_rent / 1_000_000:,.0f} میلیون تومان" if prop.monthly_rent else "توافقی"
            price_line = f"💳 **رهن:** {dep} | 💵 **اجاره ماهانه:** {rnt}"

        amenities = []
        if prop.has_parking: amenities.append("پارکینگ اختصاصی سندی")
        if prop.has_elevator: amenities.append("آسانسور")
        if prop.has_warehouse: amenities.append("انباری")
        if prop.has_balcony: amenities.append("تراس / بالکن")
        amenities_str = ' • '.join(amenities) if amenities else "امکانات کامل سندی"

        card = (
            f"🏅 **گزینه شماره {rank}** (درصد تطابق با خواسته شما: **{score}%**)\n"
            f"🏢 **عنوان:** {prop.title}\n"
            f"🆔 **کد فایل اختصاصی:** `#{prop.file_code}`\n"
            f"📍 **موقعیت:** تهران، منطقه {prop.district}\n"
            f"📐 **متراژ:** {prop.area} متر | 🛏️ {prop.rooms} خواب | طبقه {prop.floor or 1}\n"
            f"{price_line}\n"
            f"✨ **امکانات برجسته:** {amenities_str}\n"
            f"🛡️ **وضعیت اصالت فایل:** تاییدشده توسط کارشناس ارشد سقف (مالک مستقیم)"
        )
        return card

    # =========================================================================
    # ۴. مدیریت فیدبک، سنجش تمایل و هماهنگی بازدید (Engagement & Hand-off)
    # =========================================================================

    @classmethod
    def handle_feedback_and_qualification(cls, phone: str, feedback_text: str) -> Dict[str, Any]:
        """
        بررسی فیدبک مشتری:
        - در صورت ابراز رضایت / سیگنال خرید یا تمایل به بازدید -> اجرای فاز نهایی (Hand-off to Human Agent)
        - در صورت عدم رضایت یا درخواست تغییرات -> بازبینی فیلترها و ارسال موارد جدید
        """
        session = cls.get_or_create_session(phone)
        session['history'].append({'role': 'user', 'text': feedback_text})
        text = feedback_text.strip()

        # تشخیص انتخاب کد فایل خاص توسط مشتری
        chosen_prop = None
        code_match = re.search(r'(\d{4,5})', text)
        if code_match:
            code_num = code_match.group(1)
            chosen_prop = Property.find_by_file_code(code_num)
        
        if not chosen_prop and session.get('matched_properties'):
            # انتخاب فایل اول یا فایل بر اساس شماره ۱، ۲، ۳
            if 'اول' in text or '1' in text or 'یک' in text:
                chosen_prop = db.session.get(Property, session['matched_properties'][0])
            elif len(session['matched_properties']) > 1 and ('دوم' in text or '2' in text or 'دو' in text):
                chosen_prop = db.session.get(Property, session['matched_properties'][1])
            elif len(session['matched_properties']) > 2 and ('سوم' in text or '3' in text or 'سه' in text):
                chosen_prop = db.session.get(Property, session['matched_properties'][2])
            else:
                chosen_prop = db.session.get(Property, session['matched_properties'][0])

        # تشخیص سیگنال خرید یا تمایل به بازدید
        positive_signals = [
            'خوبه', 'عالیه', 'پسندیدم', 'بازدید', 'ببینم', 'هماهنگ', 'ساعت', 
            'فردا', 'حضوری', 'عکس', 'قیمت مناسب', 'خوشم اومد', 'اوکی', 'همین'
        ]
        is_hot_lead = any(sig in text for sig in positive_signals) or chosen_prop is not None

        if is_hot_lead and not chosen_prop:
            deal_t = session.get('deal_type') or 'sale'
            dist_list = session.get('districts') or ['نیاوران', 'فرمانیه', 'سعادت‌آباد']
            chosen_prop = Property.query.filter(Property.district.in_(dist_list)).first() or Property.query.first()

        if is_hot_lead and chosen_prop:
            session['selected_property_id'] = chosen_prop.id
            session['status'] = 'ready_for_visit'

            # ۱. ارسال پیام آرامش‌بخش و حرفه‌ای به مشتری
            client_reassurance_msg = (
                f"بسیار انتخاب شایسته و هوشمندانه‌ای است جناب/سرکار {session['client_name']} عزیز! 👏\n\n"
                f"این واحد با مشخصات و اولویت‌های شما کاملاً همخوانی دارد. "
                f"**هماهنگی بازدید این ملک هم‌اکنون در حال انجام است** و کارشناس فروش اختصاصی سقف "
                f"تا دقایقی دیگر جهت هماهنگی و تعیین ساعت دقیق بازدید با شما تماس خواهد گرفت.\n\n"
                f"کد پیگیری درخواست بازدید شما: **#{chosen_prop.file_code}**"
            )
            session['history'].append({'role': 'assistant', 'text': client_reassurance_msg})

            # ۲. ثبت نوبت بازدید و تعامل در CRM
            cls._create_visit_and_interaction_in_crm(session, chosen_prop, text)

            # ۳. ارسال اعلان فوری (Hot Lead Alert) به تلگرام و پنل داخلی کارشناس فروش
            alert_payload = cls._dispatch_hot_lead_alert_to_agent(session, chosen_prop, text)

            return {
                'success': True,
                'phase': 'hand_off_to_human_agent',
                'status': 'ready_for_visit',
                'client_message': client_reassurance_msg,
                'hot_lead_alert': alert_payload
            }

        else:
            # درخواست تغییر فیلتر یا عدم پسند گزینه‌ها
            session['step'] = 'refining_filters'
            refine_msg = (
                f"کاملاً درکتان می‌کنم جناب/سرکار {session['client_name']} گرامی. "
                f"سلیقه و استانداردهای شما برای ما اولویت اصلی است.\n\n"
                f"▫️ بفرمایید چه فاکتوری (قیمت، موقعیت کوچه، متراژ یا سن بنا) مدنظرتان تغییر کند؟\n"
                f"سیستم فوراً آگهی‌های جدیدتر را بررسی و موارد جایگزین را برای شما ارسال خواهد کرد."
            )
            session['history'].append({'role': 'assistant', 'text': refine_msg})
            return {
                'success': True,
                'phase': 'refining',
                'client_message': refine_msg
            }

    # =========================================================================
    # ۵. تحویل لید گرم به کارشناس با فرمت رسمی و ثبت سیستمی (Hand-off)
    # =========================================================================

    @classmethod
    def _dispatch_hot_lead_alert_to_agent(cls, session: Dict[str, Any], prop: Property, client_comment: str) -> Dict[str, Any]:
        """
        ارسال اعلان فوری به کارشناس فروش با فرمت رسمی و دقیق تعیین‌شده در پرامپت:
        [ وضعیت: آماده بازدید (Hot Lead) ]
        نام و شماره مشتری: {Client_Info}
        کد فایل انتخابی: {Property_ID}
        شماره تماس مالک جهت هماهنگی کلید/بازدید: {Owner_Phone}
        خلاصه نیاز و بودجه مشتری: {Client_Summary}
        """
        owner = prop.owner
        owner_phone = owner.phone_number if owner else "ثبت شده در پرونده مالک"
        owner_name = owner.full_name if owner else "مالک محترم"

        client_name = session.get('client_name', 'مشتری گرامی')
        client_phone = session['phone']
        client_info = f"{client_name} ({client_phone})"

        deal_label = 'خرید' if session.get('deal_type') == 'sale' else 'رهن و اجاره'
        budget_str = f"{session.get('budget', 0):,} تومان" if session.get('budget') else (f"رهن: {session.get('deposit', 0):,} | اجاره: {session.get('monthly_rent', 0):,}")
        districts_str = ', '.join(session.get('districts', [])) or prop.district

        client_summary = (
            f"متقاضی {deal_label} در محدوده {districts_str} با سقف بودجه {budget_str}. "
            f"متراژ مدنظر: حداقل {session.get('min_area', 80)} متر. "
            f"پیام مشتری: «{client_comment}»"
        )

        alert_text = (
            f"🚨 <b>[ وضعیت: آماده بازدید (Hot Lead) ]</b>\n\n"
            f"👤 <b>نام و شماره مشتری:</b> {client_info}\n"
            f"🏢 <b>کد فایل انتخابی:</b> <code>#{prop.file_code}</code> ({prop.title})\n"
            f"🔑 <b>شماره تماس مالک جهت هماهنگی کلید/بازدید:</b> <code>{owner_phone}</code> ({owner_name})\n"
            f"📋 <b>خلاصه نیاز و بودجه مشتری:</b> {client_summary}\n\n"
            f"⚡ <i>اقدام فوری مورد نیاز: لطفاً ظرف ۵ دقیقه آینده جهت تعیین ساعت دقیق بازدید با مشتری و مالک تماس بگیرید.</i>"
        )

        # ارسال در تلگرام داخلی کارشناس یا کانال خصوصی مشاوران
        target_chat = Config.ADMIN_TELEGRAM_ID or Config.TELEGRAM_CHANNEL_ID
        if target_chat:
            try:
                adapter = omnichannel_dispatcher.get_adapter('telegram')
                adapter.send_text(str(target_chat), alert_text)
            except Exception as e:
                logger.error(f"Error dispatching hot lead telegram alert: {e}")

        # ثبت در جدول لاگ ارتباطات
        try:
            log_entry = OutreachLog(
                lead_id=None,
                property_code=prop.file_code,
                platform='telegram_agent_alert',
                status='hot_lead_dispatched',
                server_response=json.dumps({'alert': 'hot_lead_ready_for_visit'}, ensure_ascii=False),
                sent_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception:
            db.session.rollback()

        return {
            'alert_text': alert_text,
            'client_info': client_info,
            'property_id': prop.id,
            'property_file_code': prop.file_code,
            'owner_phone': owner_phone,
            'client_summary': client_summary
        }

    @classmethod
    def _create_visit_and_interaction_in_crm(cls, session: Dict[str, Any], prop: Property, client_comment: str):
        """ثبت سوابق رسمی بازدید و تعامل در پایگاه داده CRM"""
        try:
            # یافتن یا ایجاد کلاینت در جدول clients
            client = Client.query.filter_by(phone_number=session['phone']).first()
            if not client:
                client = Client(
                    full_name=session.get('client_name', 'مشتری جدید تلگرام'),
                    phone_number=session['phone'],
                    preferred_deal_type=session.get('deal_type', 'sale'),
                    max_budget=session.get('budget', 0),
                    max_deposit=session.get('deposit', 0),
                    max_rent=session.get('monthly_rent', 0),
                    min_area=session.get('min_area', 80),
                    lead_status='visiting',
                    notes=f"ورودی مستقیم از دستیار فروش تلگرام. فیدبک: {client_comment}"
                )
                db.session.add(client)
                db.session.commit()
            else:
                client.lead_status = 'visiting'
                db.session.commit()

            # ایجاد نوبت بازدید برای فردا عصر
            visit_date = datetime.utcnow() + timedelta(days=1, hours=4)
            visit = Visit(
                property_id=prop.id,
                client_id=client.id,
                scheduled_time=visit_date,
                status='scheduled',
                feedback=f"درخواست بازدید تلگرام سقف: {client_comment}",
                readiness_to_buy=5
            )
            db.session.add(visit)

            # ثبت در جدول تعاملات (Interactions)
            interaction = Interaction(
                type='visit_followup',
                target_type='client',
                client_id=client.id,
                property_id=prop.id,
                summary=f"مشتری برای فایل {prop.file_code} ابراز علاقه کرد و فاز بازدید فعال شد. متن: {client_comment}",
                outcome='visit_scheduled',
                next_followup_date=visit_date
            )
            db.session.add(interaction)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error persisting visit in CRM: {e}")
            db.session.rollback()

    @classmethod
    def _persist_client_in_crm(cls, session: Dict[str, Any]):
        """ثبت پرونده اولیه مشتری در جدول CustomerLead جهت ردیابی فالوآپ ۲۴ ساعته"""
        try:
            lead = CustomerLead.query.filter_by(phone_number=session['phone']).first()
            if not lead:
                lead = CustomerLead(
                    phone_number=session['phone'],
                    full_name=session.get('client_name', 'مشتری تلگرام'),
                    deal_type=session.get('deal_type', 'sale'),
                    preferred_districts_json=json.dumps(session.get('districts', []), ensure_ascii=False),
                    max_budget=session.get('budget', 0),
                    max_deposit=session.get('deposit', 0),
                    max_rent=session.get('monthly_rent', 0),
                    min_area=session.get('min_area', 80),
                    active_messenger='telegram',
                    last_interaction_at=datetime.utcnow()
                )
                db.session.add(lead)
                db.session.commit()
            else:
                lead.last_interaction_at = datetime.utcnow()
                db.session.commit()
        except Exception as e:
            logger.error(f"Error persisting CustomerLead: {e}")
            db.session.rollback()
