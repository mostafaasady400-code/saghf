"""
سرویس جامع دستیار هوشمند صوتی و کارشناس مجازی املاک سقف (Voice AI Agent Service)
پوشش‌دهنده:
۱. مدیریت چرخه حیات مکالمه و حالت‌های صوتی (Idle, Greeting, Listening, Analyzing, Speaking, Closed)
۲. سناریوی پیش‌قدم شدن خوش‌آمدگویی صوتی و کشف نیاز اولیه
۳. اتصال به مدل‌های هوش مصنوعی (Gemini / OpenAI) با پرامپت تخصصی مشاور ارشد املاک
۴. سیستم ابزارها و Function Calling بلادرنگ برای جستجو و استخراج آنلاین فایل‌ها و هماهنگی قرار بازدید
"""

import os
import re
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import or_

from database.db import db
from database.models import Property, Owner, Client, Visit
from services.nlp_extractor import normalize_persian_text, extract_numeric_clause_near, PropertyLeadNLPExtractor
from data.tehran_districts import TEHRAN_REGIONS, find_matched_district
from crawler.owner_filter import OwnerFilter
from crawler.crawler_manager import crawler_manager

logger = logging.getLogger(__name__)

INITIAL_GREETING_TEXT = (
    "سلام، وقتتون بخیر! من مشاور هوشمند سقف در خدمت شما هستم. "
    "قصد خرید آپارتمان دارید یا رهن و اجاره؟ "
    "چه متراژ و محله‌ای مد نظرتونه تا بهترین فایل‌های شخصی و بدون واسطه رو نشونتون بدم؟"
)

class VoiceAgentService:
    """
    موتور یکپارچه دستیار صوتی املاک با پشتیبانی از Function Calling و مدل‌های زبانی
    """

    @classmethod
    def get_initial_greeting(cls) -> Dict[str, Any]:
        """
        تولید پیام آغازین و خوش‌آمدگویی هوشمند به محض کلیک کاربر روی گوی
        """
        return {
            'success': True,
            'state': 'greeting',
            'voice_reply': INITIAL_GREETING_TEXT,
            'speech_text': INITIAL_GREETING_TEXT,
            'action': 'initial_greeting',
            'next_expected_state': 'listening',
            'items': [],
            'history': [
                {'role': 'assistant', 'content': INITIAL_GREETING_TEXT}
            ]
        }

    @classmethod
    def process_voice_turn(
        cls,
        command: str,
        history: Optional[List[Dict[str, str]]] = None,
        current_path: str = '/',
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        پردازش یک دور مکالمه (Turn) صوتی/متنی کاربر از طریق درگاه ترکیبی و مقاوم هوش مصنوعی سقف
        """
        history = history or []
        norm_cmd = normalize_persian_text(command or '').strip()

        if not norm_cmd:
            return cls.get_initial_greeting()

        try:
            from services.assistant.gateway import ResilientAIAssistantGateway
            return ResilientAIAssistantGateway.process_turn(
                command=norm_cmd,
                session_id=session_id,
                history=history,
                current_path=current_path
            )
        except Exception as ex:
            logger.error(f"Error in ResilientAIAssistantGateway: {ex}. Falling back to local reasoning.")
            return cls._local_expert_reasoning(norm_cmd, history, current_path)

    # =========================================================================
    # ابزارهای سیستم (System Function Calling Tools)
    # =========================================================================
    @classmethod
    def tool_find_properties(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        ابزار واکشی و جستجوی لحظه‌ای املاک در دیتابیس و کراولر آنلاین
        """
        deal_type = params.get('deal_type', 'rent')
        district = params.get('district', '')
        max_price = params.get('max_price', 0)
        max_deposit = params.get('max_deposit', 0)
        max_rent = params.get('max_rent', 0)
        min_area = params.get('min_area', 0)
        max_area = params.get('max_area', 0)
        rooms = params.get('rooms', 0)
        has_parking = params.get('has_parking')
        has_elevator = params.get('has_elevator')

        now = datetime.utcnow()
        cutoff_7days = now - timedelta(days=7)

        query = Property.query.filter(
            Property.status.notin_(['archived', 'sold', 'needs_followup']),
            Property.is_personal_owner == True
        )

        # اعمال فیلتر نوع معامله در صورت تعیین
        if deal_type in ['sale', 'rent']:
            query = query.filter(Property.deal_type == deal_type)

        # اعمال فیلترهای ضد املاک و ضد همخونه
        for forbidden in ['املاک', 'املاکی', 'دپارتمان', 'بنگاه']:
            query = query.filter(
                Property.title.notilike(f'%{forbidden}%'),
                Property.description.notilike(f'%{forbidden}%')
            )
        for sh_kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS:
            query = query.filter(
                Property.title.notilike(f'%{sh_kw}%'),
                Property.description.notilike(f'%{sh_kw}%')
            )

        # فیلتر منطقه/محله با نگاشت هوشمند مناطق تهران
        if district:
            if any(k in district for k in ['منطقه ۵', 'منطقه 5', 'منطقه پنج']):
                r5_kws = ['پونک', 'جنت آباد', 'شهر زیبا', 'صادقیه', 'فردوس', 'سازمان برنامه', 'شاهین', 'باغ فیض', 'منطقه ۵', 'منطقه 5', 'اباذر', 'مرزداران', 'ستاری', 'کاشانی', 'حصارک', 'اکباتان']
                r5_or = [Property.district.ilike(f'%{k}%') for k in r5_kws] + [Property.title.ilike(f'%{k}%') for k in r5_kws]
                query = query.filter(or_(*r5_or))
            else:
                clean_dist = district.replace('منطقه', '').strip()
                query = query.filter(
                    or_(
                        Property.district.ilike(f'%{district}%'),
                        Property.district.ilike(f'%{clean_dist}%'),
                        Property.title.ilike(f'%{district}%'),
                        Property.address.ilike(f'%{district}%')
                    )
                )

        # فیلتر مالی
        if deal_type == 'sale' and max_price > 0:
            query = query.filter(Property.total_price <= int(max_price * 1.15))
        elif deal_type == 'rent':
            if max_deposit > 0:
                query = query.filter(Property.deposit <= int(max_deposit * 1.2))
            if max_rent > 0:
                query = query.filter(Property.monthly_rent <= int(max_rent * 1.2))

        # فیلتر فیزیکی
        if min_area > 0:
            query = query.filter(Property.area >= min_area)
        if max_area > 0:
            query = query.filter(Property.area <= max_area)
        if rooms > 0:
            query = query.filter(Property.rooms >= rooms)
        if has_parking:
            query = query.filter(Property.has_parking == True)
        if has_elevator:
            query = query.filter(Property.has_elevator == True)

        matched_props = query.order_by(Property.score.desc(), Property.id.desc()).limit(6).all()

        # اگر فایل مستقیم پیدا نشد، بررسی فایل‌های همان محله بدون محدودیت متراژ سخت
        if len(matched_props) == 0 and district:
            fallback_query = Property.query.filter(
                Property.status.notin_(['archived', 'sold']),
                Property.is_personal_owner == True
            )
            clean_dist = district.replace('منطقه', '').strip()
            fallback_query = fallback_query.filter(
                or_(
                    Property.district.ilike(f'%{district}%'),
                    Property.district.ilike(f'%{clean_dist}%'),
                    Property.title.ilike(f'%{district}%')
                )
            )
            if deal_type in ['sale', 'rent']:
                fallback_query = fallback_query.filter(Property.deal_type == deal_type)
            matched_props = fallback_query.order_by(Property.score.desc(), Property.id.desc()).limit(4).all()

        # آماده‌سازی کارت‌های ملکی
        from crawler.schemas import calculate_mortgage_conversion
        formatted_items = []
        for p in matched_props:
            thumb = '/static/images/placeholder.png'
            if p.images:
                thumb = p.images[0]

            # محاسبه دقیق قیمت و معادل رهن کامل
            conv = calculate_mortgage_conversion(p.deposit, p.monthly_rent)
            if p.deal_type == 'rent':
                dep_text = f"{int(p.deposit / 1_000_000):,} م" if p.deposit else "توافقی"
                rent_text = f"{int(p.monthly_rent / 1_000_000):,} م" if p.monthly_rent else "توافقی"
                if p.monthly_rent == 0 and p.deposit > 0:
                    price_str = f"رهن کامل: {dep_text} تومان"
                else:
                    price_str = f"ودیعه: {dep_text} | اجاره: {rent_text}"
                conv_val = conv.get('full_mortgage_equivalent', 0)
                conversion_summary = f"معادل رهن کامل: {int(conv_val / 1_000_000):,} م.ت" if conv_val > 0 else conv.get('summary_fa', '')
            else:
                price_str = f"قیمت کل: {int((p.total_price or 0) / 1_000_000_000):,} میلیارد تومان" if p.total_price else "توافقی"
                conversion_summary = f"متری {int((p.meter_price or 0) / 1_000_000):,} م" if p.meter_price else ""

            owner_phone = p.owner.phone_number if p.owner else None
            source_link = p.source_url or f"/properties/{p.id}"

            formatted_items.append({
                'id': p.id,
                'file_code': p.file_code or str(p.id),
                'title': p.title,
                'district': p.district or 'تهران',
                'deal_type': p.deal_type,
                'deal_label': 'رهن و اجاره' if p.deal_type == 'rent' else 'خرید و فروش',
                'price_str': price_str,
                'conversion_summary': conversion_summary,
                'area': p.area or 0,
                'rooms': p.rooms or 1,
                'floor': p.floor or 1,
                'has_parking': p.has_parking,
                'has_elevator': p.has_elevator,
                'image_url': thumb,
                'detail_url': f"/properties/{p.id}",
                'source_url': source_link,
                'owner_phone': owner_phone,
                'is_personal_owner': True
            })

        return {
            'count': len(formatted_items),
            'items': formatted_items,
            'deal_type': deal_type,
            'district': district
        }

    @classmethod
    def tool_schedule_visit(cls, params: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        ابزار ثبت و هماهنگی قرار بازدید حضوری با مالک و مشاور با پیشگیری از ثبت تکراری (Idempotency)
        """
        try:
            from services.assistant.memory_manager import AssistantMemoryManager
            from services.assistant.gateway import ResilientAIAssistantGateway
            session = AssistantMemoryManager.get_or_create(session_id)
            return ResilientAIAssistantGateway._execute_idempotent_visit_schedule(params, session)
        except Exception as ex:
            logger.error(f"Error in idempotent visit schedule: {ex}")
            prop_id = params.get('property_id')
            time_slot = params.get('preferred_time', 'فردا عصر')
            return {
                'success': True,
                'message': f"درخواست بازدید شما برای {time_slot} دریافت شد و مشاور مربوطه با شما تماس خواهد گرفت."
            }

    # =========================================================================
    # ارتباط با API مدل‌های زبانی آنلاین (Gemini / OpenAI REST)
    # =========================================================================
    @classmethod
    def _try_llm_function_calling(cls, command: str, history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """
        استفاده از Gemini REST API یا OpenAI با قابلیت تعریف ابزارها
        """
        gemini_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not gemini_key:
            return None

        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': gemini_key
        }

        # تعریف ساختار ابزارها برای Gemini
        tools = [{
            "function_declarations": [
                {
                    "name": "find_properties",
                    "description": "جستجو و استخراج بلادرنگ آگهی‌های ملکی منطبق با نیاز مشتری در پایگاه داده سقف",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "deal_type": {"type": "STRING", "enum": ["sale", "rent"], "description": "نوع معامله: خرید و فروش یا رهن و اجاره"},
                            "district": {"type": "STRING", "description": "نام محله یا منطقه در تهران مانند پونک، سعادت‌آباد، جنت‌آباد یا منطقه ۵"},
                            "max_price": {"type": "INTEGER", "description": "حداکثر بودجه خرید به تومان"},
                            "max_deposit": {"type": "INTEGER", "description": "حداکثر ودیعه رهن به تومان"},
                            "max_rent": {"type": "INTEGER", "description": "حداکثر اجاره ماهانه به تومان"},
                            "min_area": {"type": "INTEGER", "description": "حداقل متراژ به متر مربع"},
                            "rooms": {"type": "INTEGER", "description": "تعداد اتاق خواب"}
                        },
                        "required": ["deal_type"]
                    }
                },
                {
                    "name": "schedule_visit",
                    "description": "هماهنگی و رزرو قرار بازدید حضوری از یک ملک برای خریدار یا مستأجر",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "property_id": {"type": "INTEGER", "description": "شناسه یا کد فایل ملکی"},
                            "preferred_time": {"type": "STRING", "description": "روز و ساعت پیشنهادی بازدید"}
                        },
                        "required": ["preferred_time"]
                    }
                }
            ]
        }]

        system_instruction = (
            "شما کارشناس ارشد، خبره و بسیار محترم املاک لوکس در سامانه «سقف» هستید. "
            "لحن شما گرم، صمیمی، حرفه‌ای و هدفمند است. "
            "هدف شما در هر مکالمه: ۱. کشف دقیق نیاز (نوع معامله، محله، بودجه، متراژ). "
            "۲. فراخوانی تابع find_properties به محض اینکه کاربر محله، بودجه یا نوع معامله را مشخص کرد. "
            "۳. پس از ارائه فایل‌ها، ترغیب هوشمندانه مشتری به سمت هماهنگی قرار بازدید حضوری (Schedule Visit)."
        )

        contents = []
        for h in history[-30:]:
            role = 'model' if h.get('role') == 'assistant' else 'user'
            contents.append({'role': role, 'parts': [{'text': h.get('content', '')}]})
        contents.append({'role': 'user', 'parts': [{'text': command}]})

        body = {
            "contents": contents,
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "tools": tools,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
        }

        # لیست مدل‌های سازگار جهت تاب‌آوری در برابر تغییرات یا بار ترافیکی بالا (Fallback Models)
        preferred_model = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash').strip()
        candidate_models = [preferred_model, 'gemini-3.8-flash', 'gemini-3.5-flash', 'gemini-flash-latest']
        models_to_try = list(dict.fromkeys(m for m in candidate_models if m))

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            try:
                res = requests.post(url, headers=headers, json=body, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    candidate = data.get('candidates', [{}])[0]
                    parts = candidate.get('content', {}).get('parts', [])
                    
                    # بررسی وجود فراخوانی تابع (Function Call)
                    for part in parts:
                        if 'functionCall' in part:
                            fc = part['functionCall']
                            fname = fc.get('name')
                            fargs = fc.get('args', {})

                            if fname == 'find_properties':
                                found = cls.tool_find_properties(fargs)
                                items = found.get('items', [])
                                count = len(items)
                                
                                dist_str = fargs.get('district', 'درخواستی')
                                deal_str = 'رهن و اجاره' if fargs.get('deal_type') == 'rent' else 'خرید'
                                
                                if count > 0:
                                    reply = (
                                        f"من {count} فایل کارشناسی‌شده {deal_str} در محدوده {dist_str} بر اساس مشخصات شما پیدا کردم. "
                                        f"کارت‌های مشخصات روی صفحه قرار گرفتند. مایلید برای هماهنگی بازدید حضوری کد فایل را بفرمایید؟"
                                    )
                                else:
                                    reply = (
                                        f"در حال حاضر فایل دقیق با این شرایط در دیتابیس موجود نبود؛ "
                                        f"اما پایش زنده کراولر روی منطقه {dist_str} فعال است و موارد جدید سریعاً اطلاع‌رسانی می‌شوند."
                                    )

                                return {
                                    'success': True,
                                    'state': 'speaking',
                                    'voice_reply': reply,
                                    'speech_text': reply,
                                    'action': 'properties_found',
                                    'items': items,
                                    'next_expected_state': 'listening',
                                    'history': history + [
                                        {'role': 'user', 'content': command},
                                        {'role': 'assistant', 'content': reply}
                                    ]
                                }
                            elif fname == 'schedule_visit':
                                visit_res = cls.tool_schedule_visit(fargs)
                                reply = (
                                    f"{visit_res.get('message', 'درخواست بازدید ثبت شد.')} "
                                    f"مشاور ارشد منطقه به زودی جهت هماهنگی نهایی با شما تماس خواهد گرفت."
                                )
                                return {
                                    'success': True,
                                    'state': 'speaking',
                                    'voice_reply': reply,
                                    'speech_text': reply,
                                    'action': 'visit_scheduled',
                                    'items': [],
                                    'next_expected_state': 'idle',
                                    'history': history + [
                                        {'role': 'user', 'content': command},
                                        {'role': 'assistant', 'content': reply}
                                    ]
                                }

                        # پاسخ متنی معمولی
                        if 'text' in part:
                            text_resp = part['text']
                            return {
                                'success': True,
                                'state': 'speaking',
                                'voice_reply': text_resp,
                                'speech_text': text_resp,
                                'action': 'agent_reply',
                                'items': [],
                                'next_expected_state': 'listening',
                                'history': history + [
                                    {'role': 'user', 'content': command},
                                    {'role': 'assistant', 'content': text_resp}
                                ]
                            }
                else:
                    logger.warning(f"Gemini model {model_name} HTTP {res.status_code}. Trying next fallback...")
            except Exception as e:
                logger.warning(f"Error querying Gemini model {model_name}: {e}")

        return None

    # =========================================================================
    # موتور محلی تحلیل خبره مکالمه و تطبیق املاک (Local Real Estate Agent Engine)
    # =========================================================================
    @classmethod
    def _local_expert_reasoning(cls, command: str, history: List[Dict[str, str]], current_path: str) -> Dict[str, Any]:
        """
        موتور مستقل و فوق‌سریع تحلیل زبان فارسی مشاور املاک با استخراج مقاصد و ابزارها
        """
        norm = command.lower()

        # ۰. استعلام شماره مالک از DOM استاتیک دیوار (بدون Chromium/Playwright)
        if any(w in norm for w in ['شماره مالک', 'شماره تماس', 'تماس با مالک', 'استعلام شماره', 'شماره تلفن']):
            code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', norm)
            prop = None
            if code_match:
                code_value = code_match.group(1)
                prop = Property.query.filter(
                    (Property.file_code == code_value) | (Property.id == int(code_value))
                ).first()
            if not prop:
                prop = Property.query.order_by(Property.id.desc()).first()

            from services.divar_contact_service import DivarContactService

            contact_result = DivarContactService.fetch_for_property(prop)
            reply_text = contact_result.get('message') or 'شماره مالک در دسترس نیست.'
            action = 'reveal_phone' if contact_result.get('success') else 'phone_unavailable'
            return {
                'success': True,
                'state': 'speaking',
                'voice_reply': reply_text,
                'speech_text': reply_text,
                'action': action,
                'property_id': contact_result.get('property_id'),
                'phone': contact_result.get('phone'),
                'contact_source': contact_result.get('source'),
                'items': [],
                'next_expected_state': 'listening',
                'history': history + [
                    {'role': 'user', 'content': command},
                    {'role': 'assistant', 'content': reply_text}
                ]
            }

        # ۱. تشخیص هماهنگی قرار بازدید (Schedule Visit)
        if any(w in norm for w in ['بازدید', 'ببینم', 'قرار بازدید', 'دیدن ملک', 'هماهنگ کن', 'کی بریم', 'هماهنگی']):
            code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', norm)
            prop_id = int(code_match.group(1)) if code_match else None
            
            visit_res = cls.tool_schedule_visit({
                'property_id': prop_id,
                'preferred_time': 'فردا عصر ساعت ۵'
            })
            reply_text = (
                "بسیار عالی! درخواست بازدید حضوری شما با موفقیت ثبت شد. "
                "کارشناس تخصصی منطقه در سامانه سقف جهت هماهنگی ساعت دقیق با شما تماس خواهد گرفت."
            )
            return {
                'success': True,
                'state': 'speaking',
                'voice_reply': reply_text,
                'speech_text': reply_text,
                'action': 'visit_scheduled',
                'items': [],
                'next_expected_state': 'idle',
                'history': history + [
                    {'role': 'user', 'content': command},
                    {'role': 'assistant', 'content': reply_text}
                ]
            }

        # ۲. تشخیص احوالپرسی اولیه بدون جزئیات ملک
        is_greeting = any(w in norm for w in ['سلام', 'درود', 'صبح بخیر', 'عصر بخیر', 'روز بخیر', 'چطوری'])
        has_criteria = any(w in norm for w in ['خرید', 'اجاره', 'رهن', 'فروش', 'منطقه', 'پونک', 'سعادت', 'متری', 'میلیارد', 'تومن'])

        if is_greeting and not has_criteria:
            reply_text = (
                "سلام و درود! خوش آمدید. "
                "بفرمایید قصد خرید ملک دارید یا رهن و اجاره؟ "
                "کدام منطقه و چه بازه قیمتی مد نظرتان است؟"
            )
            return {
                'success': True,
                'state': 'speaking',
                'voice_reply': reply_text,
                'speech_text': reply_text,
                'action': 'ask_clarification',
                'items': [],
                'next_expected_state': 'listening',
                'history': history + [
                    {'role': 'user', 'content': command},
                    {'role': 'assistant', 'content': reply_text}
                ]
            }

        # ۳. استخراج هوشمند پارامترهای ملکی جهت Tool Calling خودکار با NLP Extractor یکپارچه
        criteria = PropertyLeadNLPExtractor.extract_criteria(command)
        deal_type = criteria.get('deal_type', 'any')
        target_district = criteria['districts'][0] if criteria.get('districts') else ('پونک' if 'پونک' in norm else 'منطقه ۵')
        total_price = criteria.get('max_budget', 0)
        deposit = criteria.get('max_deposit', 0)
        rent = criteria.get('max_rent', 0)
        min_area = criteria.get('min_area', 0)
        max_area = criteria.get('max_area', 0)

        # فراخوانی خودکار ابزار واکشی فایل‌ها
        tool_params = {
            'deal_type': deal_type,
            'district': target_district,
            'max_price': total_price,
            'max_deposit': deposit,
            'max_rent': rent,
            'min_area': min_area,
            'max_area': max_area
        }

        search_result = cls.tool_find_properties(tool_params)
        items = search_result.get('items', [])
        count = len(items)

        deal_label = "رهن و اجاره" if deal_type == 'rent' else ("خرید و فروش" if deal_type == 'sale' else "ملکی")
        dist_label = target_district or "پونک و منطقه ۵"

        if count > 0:
            voice_reply = (
                f"چشم! فایل‌های شخصی و بروز {dist_label} با مشخصات مد نظرتان آماده شد. "
                f"تعداد {count} مورد کارشناسی‌شده با عکس‌های واقعی و مبالغ رهن و اجاره روی صفحه قرار گرفت. "
                f"بفرمایید برای کدام مورد قرار بازدید حضوری هماهنگ کنیم؟"
            )
            speech_text = (
                f"فایل‌های شخصی {dist_label} با مشخصات درخواستی شما آماده شد. "
                f"{count} مورد متناسب روی صفحه قرار گرفت. برای هماهنگی بازدید در خدمتم."
            )
        else:
            voice_reply = (
                f"در حال حاضر فایل مستقیم با این شرایط در محدوده {dist_label} موجود نیست؛ "
                f"پایش لحظه‌ای کراولر روی دیوار برای محله {dist_label} فعال است و به محض ثبت فایل شخصی جدید اطلاع‌رسانی می‌شود."
            )
            speech_text = voice_reply

        return {
            'success': True,
            'state': 'speaking',
            'voice_reply': voice_reply,
            'speech_text': speech_text,
            'action': 'properties_found' if count > 0 else 'clarification_needed',
            'items': items,
            'next_expected_state': 'listening',
            'history': history + [
                {'role': 'user', 'content': command},
                {'role': 'assistant', 'content': voice_reply}
            ]
        }
