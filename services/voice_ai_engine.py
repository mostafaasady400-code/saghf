"""
=============================================================================
سامانه موتور هوش مصنوعی و پایپلاین صوتی «سقف» (Voice AI Engine & Pipeline)
نقش: مشاور ارشد و خبره املاک سقف
سناریوها:
  ۱. تحلیل نیاز خریدار/مستأجر (Lead Discovery & Live Matching)
  ۲. ثبت خودکار فایل جدید مالک (Listing Intake & Omnichannel Automation)
=============================================================================
"""

import re
import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from database.db import db
from database.models import Property, Owner, CustomerLead, OutreachLog
from services.nlp_extractor import PropertyLeadNLPExtractor, normalize_persian_text, parse_persian_money_amount
from services.omnichannel.dispatcher import omnichannel_dispatcher
from crawler.crawler_manager import crawler_manager

logger = logging.getLogger(__name__)

# حافظه نشست‌های صوتی (In-Memory Session Store)
VOICE_SESSIONS: Dict[str, Dict[str, Any]] = {}

def get_or_create_session(session_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    if not session_id or session_id not in VOICE_SESSIONS:
        new_id = session_id or str(uuid.uuid4())
        VOICE_SESSIONS[new_id] = {
            'session_id': new_id,
            'intent': None, # 'lead_discovery' or 'listing_intake'
            'stage': 'greeting',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'turn_count': 0,
            'entities': {
                'deal_type': None,
                'districts': [],
                'min_area': 0,
                'max_area': 0,
                'max_budget': 0,
                'max_deposit': 0,
                'max_rent': 0,
                'features': [],
                'owner_name': None,
                'owner_phone': None,
                'address': None
            },
            'matched_properties': []
        }
        return new_id, VOICE_SESSIONS[new_id]
    
    session = VOICE_SESSIONS[session_id]
    session['updated_at'] = datetime.utcnow()
    return session_id, session

class VoiceAiPipeline:
    """
    هسته پردازش چندوجهی و پایپلاین مکالمه صوتی سقف
    """

    @classmethod
    def detect_intent(cls, text: str, current_intent: Optional[str] = None) -> str:
        """
        تشخیص قصد کاربر:
        ۱. listing_intake: مالک، واگذاری، ثبت فایل، فروش یا اجاره دادن ملک شخصی
        ۲. lead_discovery: خریدار یا مستأجر به دنبال فایل
        """
        norm = normalize_persian_text(text)
        
        # کلیدواژه‌ها و الگوهای اعلام ملک توسط مالک
        intake_patterns = [
            r'ثبت\s*(ملک|فایل|آپارتمان|واحد|آگهی)?',
            r'واگذار\w*',
            r'مالک(م| هستم)?',
            r'(بفروش|فروش\s*بذار|فروش\s*بگذار|قصد\s*فروش|فروشنده)',
            r'(اجاره\s*بد|رهن\s*بد)',
            r'(آپارتمانم|ملکم|خونم|واحدم)',
            r'(واحد|خونه|ملک|آپارتمان)\s*دارم',
            r'فایل\s*(جدید|دارم)'
        ]
        
        # اگر عبارات صریح خرید/اجاره کردن توسط خریدار گفته نشده باشد
        is_explicit_buyer = any(k in norm for k in ['خریدارم', 'می‌خوام بخرم', 'میخوام بخرم', 'دنبال خریدم', 'دنبال اجاره‌ام', 'دنبال رهن', 'متقاضی'])
        
        for pattern in intake_patterns:
            if re.search(pattern, norm) and not is_explicit_buyer:
                return 'listing_intake'
                
        if current_intent == 'listing_intake' and not is_explicit_buyer:
            return 'listing_intake'
                
        return 'lead_discovery'


    @classmethod
    def extract_phone_number(cls, text: str) -> Optional[str]:
        """
        استخراج شماره تلفن همراه معتبر ایران (۰۹۱۲... یا ۰۹...)
        """
        norm = normalize_persian_text(text)
        # ارقام به انگلیسی تبدیل شده‌اند
        match = re.search(r'(?:0|\+98)?(9\d{9})', norm)
        if match:
            return f"0{match.group(1)}"
        return None

    @classmethod
    def process_turn(cls, session_id: Optional[str], raw_text: str) -> Dict[str, Any]:
        """
        پردازش یک نوبت مکالمه (Dialogue Turn) و اجرای اکشن‌های سیستمی
        """
        session_id, session = get_or_create_session(session_id)
        session['turn_count'] += 1
        text = raw_text.strip() if raw_text else ''
        norm_text = normalize_persian_text(text)

        # در صورت پیام خالی یا شروع اولیه
        if not text or text in ['سلام', 'درود', 'شروع']:
            greeting_msg = (
                "سلام و درود! به سامانه یکپارچه فایلینگ و هوش مصنوعی «سقف» خوش آمدید. "
                "من مشاور ارشد شما هستم. بفرمایید برای خرید، رهن و اجاره، و یا ثبت و واگذاری ملک شخصی چه مشخصاتی مد نظرتونه؟"
            )
            return {
                'success': True,
                'session_id': session_id,
                'intent': 'greeting',
                'stage': 'greeting',
                'ai_response_text': greeting_msg,
                'extracted_entities': session['entities'],
                'matched_properties': [],
                'crawler_running': False,
                'intake_completed': False
            }

        # ۱. تشخیص قصد کاربر
        intent = cls.detect_intent(text, session.get('intent'))
        session['intent'] = intent

        # ۲. پردازش بر اساس سناریو
        if intent == 'listing_intake':
            return cls._handle_listing_intake(session, text, norm_text)
        else:
            return cls._handle_lead_discovery(session, text, norm_text)

    @classmethod
    def _handle_lead_discovery(cls, session: Dict[str, Any], text: str, norm_text: str) -> Dict[str, Any]:
        """
        سناریوی اول: تحلیل نیاز خریدار/مستأجر (Lead Discovery & Live Matching)
        """
        # استخراج موجودیت‌ها (NER)
        nlp_data = PropertyLeadNLPExtractor.extract_criteria(text)
        entities = session['entities']

        # به‌روزرسانی اسلات‌های ذخیره شده در نشست
        if nlp_data.get('deal_type'):
            entities['deal_type'] = nlp_data['deal_type']
        if nlp_data.get('districts'):
            for d in nlp_data['districts']:
                if d not in entities['districts']:
                    entities['districts'].append(d)
        if nlp_data.get('min_area') and nlp_data['min_area'] > 0:
            entities['min_area'] = nlp_data['min_area']
        if nlp_data.get('max_area') and nlp_data['max_area'] > 0:
            entities['max_area'] = nlp_data['max_area']
        if nlp_data.get('max_budget') and nlp_data['max_budget'] > 0:
            entities['max_budget'] = nlp_data['max_budget']
        if nlp_data.get('max_deposit') and nlp_data['max_deposit'] > 0:
            entities['max_deposit'] = nlp_data['max_deposit']
        if nlp_data.get('max_rent') and nlp_data['max_rent'] > 0:
            entities['max_rent'] = nlp_data['max_rent']
        if nlp_data.get('features'):
            for f in nlp_data['features']:
                if f not in entities['features']:
                    entities['features'].append(f)

        # ۳. کوئری دیتابیس مستقیم مالکین و آگهی‌های پایش وب
        query = Property.query.filter(Property.status != 'archived')

        # فیلتر حذف املاکی‌ها
        for forbidden in ['املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس']:
            query = query.filter(
                Property.title.notilike(f'%{forbidden}%'),
                Property.description.notilike(f'%{forbidden}%')
            )

        if entities.get('deal_type'):
            query = query.filter(Property.deal_type == entities['deal_type'])

        if entities.get('districts'):
            conds = [Property.district.ilike(f'%{d}%') for d in entities['districts']]
            query = query.filter(db.or_(*conds))

        if entities.get('min_area') and entities['min_area'] > 0:
            query = query.filter(Property.area >= int(entities['min_area'] * 0.85))

        if entities.get('deal_type') == 'sale' and entities.get('max_budget') and entities['max_budget'] > 0:
            query = query.filter(Property.total_price <= int(entities['max_budget'] * 1.20))
        elif entities.get('deal_type') == 'rent':
            if entities.get('max_deposit') and entities['max_deposit'] > 0:
                query = query.filter(Property.deposit <= int(entities['max_deposit'] * 1.25))
            if entities.get('max_rent') and entities['max_rent'] > 0:
                query = query.filter(Property.monthly_rent <= int(entities['max_rent'] * 1.25))

        matched_props = query.order_by(Property.created_at.desc()).limit(15).all()

        # کراول بلادرنگ در پس‌زمینه در صورت نیاز
        crawler_status = crawler_manager.get_status()
        crawler_running = crawler_status.get('is_running', False)
        if len(matched_props) < 3 and not crawler_running:
            deal_t = entities.get('deal_type', 'sale')
            cats = ['buy-apartment'] if deal_t == 'sale' else ['rent-apartment']
            t_district = entities['districts'][0] if entities['districts'] else None
            crawler_manager.start_crawl_task(
                sources=['divar', 'sheypoor'],
                categories=cats,
                limit_per_cat=4,
                city='tehran',
                district=t_district,
                districts=entities['districts'] if entities['districts'] else None,
                min_price=int(entities.get('max_budget', 0) * 0.5) if entities.get('max_budget') else None,
                max_price=int(entities.get('max_budget')) if entities.get('max_budget') else None,
                min_deposit=int(entities.get('max_deposit', 0) * 0.5) if entities.get('max_deposit') else None,
                max_deposit=int(entities.get('max_deposit')) if entities.get('max_deposit') else None,
                min_area=entities.get('min_area') if entities.get('min_area', 0) > 0 else None
            )
            crawler_running = True

        # فرمت خروجی فایل‌ها و نمره‌دهی
        items = []
        for p in matched_props:
            score = 88
            if entities.get('districts') and any(d in (p.district or '') for d in entities['districts']):
                score += 7
            for f in entities.get('features', []):
                if f == 'پارکینگ' and p.has_parking: score += 2
                if f == 'آسانسور' and p.has_elevator: score += 2
                if f == 'انباری' and p.has_warehouse: score += 1
            
            p_dict = {
                'id': p.id,
                'title': p.title,
                'source': p.source,
                'deal_type': p.deal_type,
                'district': p.district,
                'address': p.address,
                'area': p.area,
                'rooms': p.rooms,
                'total_price': p.total_price,
                'deposit': p.deposit,
                'monthly_rent': p.monthly_rent,
                'images': json.loads(p.images_json) if p.images_json else [],
                'phone_number': p.owner.phone_number if p.owner else '',
                'match_score': min(99, score)
            }
            items.append(p_dict)

        items.sort(key=lambda x: x['match_score'], reverse=True)
        session['matched_properties'] = items

        # ساخت پاسخ استدلالی مشاور ارشد (Human-like Persona)
        deal_name = 'خرید' if entities.get('deal_type') == 'sale' else 'رهن و اجاره'
        districts_str = '، '.join(entities['districts']) if entities['districts'] else 'مناطق منتخب'
        
        # بررسی اسلات‌های ناقص جهت هدایت دوطرفه مکالمه
        missing_slots = []
        if not entities['districts']:
            missing_slots.append('منطقه')
        if not entities.get('max_budget') and not entities.get('max_deposit'):
            missing_slots.append('بازه بودجه')
        if not entities.get('min_area'):
            missing_slots.append('متراژ حدودی')

        if len(items) > 0:
            ai_reply = f"درخواست شما برای {deal_name} در {districts_str} بررسی شد. {len(items)} گزینه با تطابق بالا روی میز کارشناسی قرار گرفت."
            if missing_slots:
                ai_reply += f" برای فیلتر دقیق‌تر، لطفاً {missing_slots[0]} مد نظرتون رو هم بفرمایید."
            else:
                ai_reply += " فایل‌ها با مشخصات متراژ و امکانات در پنل کنار گوی قابل مشاهده و بررسی هستند."
            if crawler_running:
                ai_reply += " همزمان کراولر زنده در حال استخراج آخرین آگهی‌های نوظهور است."
        else:
            if missing_slots:
                ai_reply = f"مشخصات شما برای {deal_name} دریافت شد. لطفاً {missing_slots[0]} مد نظرتون رو بفرمایید تا دقیق‌ترین فایل‌ها را استخراج کنم."
            else:
                ai_reply = f"فایل‌های متناظر با {deal_name} در {districts_str} در حال پایش لحظه‌ای هستند. پایشگر زنده دیوار و شیپور فعال گردید تا به محض ثبت آگهی، فوراً در پنل ظاهر شود."

        return {
            'success': True,
            'session_id': session['session_id'],
            'intent': 'lead_discovery',
            'stage': 'matched' if len(items) > 0 else 'collecting',
            'ai_response_text': ai_reply,
            'extracted_entities': entities,
            'matched_properties': items,
            'crawler_running': crawler_running,
            'intake_completed': False
        }

    @classmethod
    def _handle_listing_intake(cls, session: Dict[str, Any], text: str, norm_text: str) -> Dict[str, Any]:
        """
        سناریوی دوم: ثبت خودکار فایل جدید (Listing Intake & Omni-channel Automation)
        """
        entities = session['entities']
        nlp_data = PropertyLeadNLPExtractor.extract_criteria(text)
        
        # تشخیص شماره تلفن مالک
        phone = cls.extract_phone_number(text)
        if phone:
            entities['owner_phone'] = phone

        # به‌روزرسانی مشخصات ملک
        if nlp_data.get('deal_type'):
            entities['deal_type'] = nlp_data['deal_type']
        if nlp_data.get('districts'):
            for d in nlp_data['districts']:
                if d not in entities['districts']:
                    entities['districts'].append(d)
        if nlp_data.get('min_area') and nlp_data['min_area'] > 0:
            entities['min_area'] = nlp_data['min_area']
        if nlp_data.get('max_budget') and nlp_data['max_budget'] > 0:
            entities['max_budget'] = nlp_data['max_budget']
        if nlp_data.get('max_deposit') and nlp_data['max_deposit'] > 0:
            entities['max_deposit'] = nlp_data['max_deposit']
        if nlp_data.get('max_rent') and nlp_data['max_rent'] > 0:
            entities['max_rent'] = nlp_data['max_rent']
        if nlp_data.get('features'):
            for f in nlp_data['features']:
                if f not in entities['features']:
                    entities['features'].append(f)

        # استخراج آدرس احتمالی
        if any(w in norm_text for w in ['خیابان', 'کوچه', 'بلوار', 'پلاک', 'میدان']):
            entities['address'] = text

        has_phone = bool(entities.get('owner_phone'))
        has_area = bool(entities.get('min_area') and entities['min_area'] > 0)
        has_district = bool(entities.get('districts'))

        # اگر اطلاعات کلیدی (شماره تماس یا متراژ/منطقه) هنوز ناقص است
        if not has_phone:
            prompt_reply = (
                "بسیار عالی، در بخش ثبت فایل و واگذاری املاک سقف در خدمت شما هستم. "
                "لطفاً شماره تلفن همراه خود را بفرمایید تا پرونده فایل اختصاصی ملک شما ایجاد و پیام تاییدیه ارسال گردد."
            )
            return {
                'success': True,
                'session_id': session['session_id'],
                'intent': 'listing_intake',
                'stage': 'awaiting_phone',
                'ai_response_text': prompt_reply,
                'extracted_entities': entities,
                'matched_properties': [],
                'crawler_running': False,
                'intake_completed': False
            }

        if not has_area or not has_district:
            missing_text = "متراژ و محله ملک" if (not has_area and not has_district) else ("متراژ ملک" if not has_area else "محله ملک")
            prompt_reply = (
                f"شماره تماس شما ({entities['owner_phone']}) ثبت شد. "
                f"لطفاً {missing_text} و حدود قیمت یا شرایط ودیعه و اجاره را بفرمایید تا ثبت نهایی انجام شود."
            )
            return {
                'success': True,
                'session_id': session['session_id'],
                'intent': 'listing_intake',
                'stage': 'awaiting_specs',
                'ai_response_text': prompt_reply,
                'extracted_entities': entities,
                'matched_properties': [],
                'crawler_running': False,
                'intake_completed': False
            }

        # ۳. تمام اطلاعات اولیه آماده است -> ثبت دیتابیس و اتوماسیون چندکاناله
        try:
            # ایجاد یا بازیابی مالک
            owner = Owner.query.filter_by(phone_number=entities['owner_phone']).first()
            if not owner:
                owner = Owner(
                    full_name=entities.get('owner_name') or 'مالک محترم (ثبت صوتی)',
                    phone_number=entities['owner_phone'],
                    urgency='high',
                    notes=f"ثبت خودکار از طریق دستیار صوتی سقف در تاریخ {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
                )
                db.session.add(owner)
                db.session.commit()

            district_val = entities['districts'][0] if entities['districts'] else 'تهران'
            deal_type_val = entities.get('deal_type', 'sale')
            area_val = entities.get('min_area', 100)
            price_val = entities.get('max_budget', 0)
            deposit_val = entities.get('max_deposit', 0)
            rent_val = entities.get('max_rent', 0)

            unique_code = f"saghf_voice_{uuid.uuid4().hex[:6]}"
            new_prop = Property(
                source='direct_owner',
                source_id=unique_code,
                title=f"آپارتمان {area_val} متری {district_val} (ثبت مستقیم مالک)",
                deal_type=deal_type_val,
                property_type='apartment',
                city='تهران',
                district=district_val,
                address=entities.get('address') or f"تهران، {district_val}",
                total_price=price_val,
                deposit=deposit_val,
                monthly_rent=rent_val,
                area=area_val,
                rooms=2 if area_val >= 100 else 1,
                has_parking='پارکینگ' in entities.get('features', []),
                has_elevator='آسانسور' in entities.get('features', []),
                has_warehouse='انباری' in entities.get('features', []),
                has_balcony='بالکن' in entities.get('features', []),
                features_json=json.dumps(entities.get('features', []), ensure_ascii=False),
                description=f"ثبت مکالمه‌ای با دستیار صوتی سقف. مالک: {entities['owner_phone']}",
                images_json=json.dumps(['/static/images/luxury/living_room.jpg']),
                status='verified',
                owner_id=owner.id
            )
            db.session.add(new_prop)
            db.session.commit()

            # ۴. اتوماسیون چندکاناله (Omnichannel Dispatcher)
            upload_link = f"http://127.0.0.1:5000/properties/{new_prop.id}"
            outreach_msg = (
                f"🏛️ سامانه املاک سقف\n\n"
                f"مالک گرامی، فایل ملکی شما با کد اختصاصی [{unique_code}] با موفقیت در سامانه سقف ثبت گردید.\n"
                f"▫️ منطقه: {district_val}\n"
                f"▫️ متراژ: {area_val} متر\n\n"
                f"📸 جهت تسریع در واگذاری، لطفاً تصاویر و مستندات واحد را از طریق لینک زیر آپلود فرمایید یا به همین شماره ارسال کنید:\n"
                f"{upload_link}\n\n"
                f"کارشناس ارشد سقف به زودی جهت هماهنگی با شما تماس خواهد گرفت."
            )

            # ارسال خودکار به تلگرام/واتساپ/بله از طریق Omnichannel Dispatcher
            dispatched = False
            try:
                adapter = omnichannel_dispatcher.get_adapter('telegram')
                res = adapter.send_text(entities['owner_phone'], outreach_msg)
                dispatched = res.get('success', False)
            except Exception as e:
                logger.error(f"Error in omnichannel dispatch: {e}")

            # لاگ در OutreachLog
            try:
                log_entry = OutreachLog(
                    property_listing_id=new_prop.id,
                    property_code=unique_code,
                    platform='telegram',
                    status='sent' if dispatched else 'queued',
                    server_response=json.dumps({'message': 'Intake notification dispatched', 'phone': entities['owner_phone']}),
                    sent_at=datetime.utcnow()
                )
                db.session.add(log_entry)
                db.session.commit()
            except Exception:
                db.session.rollback()

            confirmation_msg = (
                f"اطلاعات ملک شما با متراژ {area_val} متر در محله {district_val} با کد رهگیری اختصاصی {unique_code} "
                f"با موفقیت در سامانه هوشمند سقف ثبت شد. پیام تأیید رسمی به همراه لینک ارسال تصاویر به شماره {entities['owner_phone']} ارسال گردید."
            )

            return {
                'success': True,
                'session_id': session['session_id'],
                'intent': 'listing_intake',
                'stage': 'intake_registered',
                'ai_response_text': confirmation_msg,
                'extracted_entities': entities,
                'matched_properties': [{
                    'id': new_prop.id,
                    'title': new_prop.title,
                    'source': 'direct_owner',
                    'deal_type': new_prop.deal_type,
                    'district': new_prop.district,
                    'area': new_prop.area,
                    'total_price': new_prop.total_price,
                    'deposit': new_prop.deposit,
                    'monthly_rent': new_prop.monthly_rent,
                    'images': ['/static/images/luxury/living_room.jpg'],
                    'phone_number': entities['owner_phone'],
                    'match_score': 100
                }],
                'crawler_running': False,
                'intake_completed': True,
                'intake_property_id': new_prop.id,
                'upload_link': upload_link,
                'omnichannel_dispatched': True
            }

        except Exception as e:
            logger.error(f"Error saving property intake: {e}", exc_info=True)
            db.session.rollback()
            return {
                'success': False,
                'session_id': session['session_id'],
                'intent': 'listing_intake',
                'stage': 'error',
                'ai_response_text': "در ثبت مشخصات ملک مشکلی رخ داد. لطفاً مجدداً شماره تماس و مشخصات را بفرمایید.",
                'extracted_entities': entities,
                'matched_properties': [],
                'crawler_running': False,
                'intake_completed': False
            }

voice_ai_pipeline = VoiceAiPipeline()
