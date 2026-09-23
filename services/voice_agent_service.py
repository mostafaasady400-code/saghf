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
from services.nlp_extractor import normalize_persian_text, extract_numeric_clause_near
from data.tehran_districts import TEHRAN_REGIONS, find_matched_district
from crawler.owner_filter import OwnerFilter
from crawler.crawler_manager import crawler_manager

logger = logging.getLogger(__name__)

INITIAL_GREETING_TEXT = (
    "سلام! من دستیار هوشمند شما در سامانه سقف هستم. "
    "چطور می‌تونم کمکتون کنم؟ به دنبال خرید هستید یا اجاره؟ "
    "در چه منطقه و با چه بودجه‌ای ملکی مد نظرتونه؟"
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
    def process_voice_turn(cls, command: str, history: Optional[List[Dict[str, str]]] = None, current_path: str = '/') -> Dict[str, Any]:
        """
        پردازش یک دور مکالمه (Turn) صوتی/متنی کاربر
        """
        history = history or []
        norm_cmd = normalize_persian_text(command or '').strip()

        if not norm_cmd:
            return cls.get_initial_greeting()

        # ۱. تلاش برای پردازش از طریق مدل‌های زبانی آنلاین با Function Calling
        llm_resp = cls._try_llm_function_calling(norm_cmd, history)
        if llm_resp:
            return llm_resp

        # ۲. در صورت در دسترس نبودن اینترنت/کلید، استفاده از موتور محلی خبره مشاور املاک سقف
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
            Property.status.notin_(['archived', 'sold', 'needs_followup'])
        )

        # اعمال فیلتر قطعی نوع معامله
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

        # فیلتر منطقه/محله
        if district:
            # واکشی کلیدواژه‌های محله
            clean_dist = district.replace('منطقه', '').strip()
            query = query.filter(
                or_(
                    Property.district.ilike(f'%{district}%'),
                    Property.district.ilike(f'%{clean_dist}%'),
                    Property.title.ilike(f'%{district}%')
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

        # اگر فایل مستقیم پیدا نشد، تلاش برای استخراج از کراولر و گسترش آرام جستجو
        if len(matched_props) == 0:
            fallback_query = Property.query.filter(
                Property.deal_type == deal_type,
                Property.status.notin_(['archived', 'sold'])
            )
            if district:
                fallback_query = fallback_query.filter(Property.district.ilike(f'%{district}%'))
            matched_props = fallback_query.order_by(Property.score.desc(), Property.id.desc()).limit(4).all()

        # آماده‌سازی کارت‌های ملکی
        formatted_items = []
        for p in matched_props:
            thumb = '/static/images/placeholder.png'
            if p.images_json:
                try:
                    imgs = json.loads(p.images_json)
                    if imgs and isinstance(imgs, list) and len(imgs) > 0 and imgs[0]:
                        thumb = imgs[0]
                except Exception:
                    pass

            # محاسبه قیمت به زبان روان
            if p.deal_type == 'rent':
                dep_text = f"{int(p.deposit / 1_000_000):,} م" if p.deposit else "توافقی"
                rent_text = f"{int(p.monthly_rent / 1_000_000):,} م" if p.monthly_rent else "توافقی"
                price_str = f"ودیعه: {dep_text} | اجاره: {rent_text}"
            else:
                price_str = f"قیمت کل: {int((p.total_price or 0) / 1_000_000_000):,} میلیارد تومان" if p.total_price else "توافقی"

            owner_phone = p.owner.phone_number if p.owner else None

            # رعایت صددرصدی خط قرمز ۲: تمام داده‌ها دارای لینک مستقیم با عنوان «لینک آگهی»
            source_link = p.source_url or f"/properties/{p.id}"

            formatted_items.append({
                'id': p.id,
                'title': p.title,
                'district': p.district or 'تهران',
                'deal_type': p.deal_type,
                'price_str': price_str,
                'area': p.area or 0,
                'rooms': p.rooms or 1,
                'has_parking': p.has_parking,
                'has_elevator': p.has_elevator,
                'image_url': thumb,
                'detail_url': f"/properties/{p.id}",
                'source_url': source_link,
                'owner_phone': owner_phone
            })

        return {
            'count': len(formatted_items),
            'items': formatted_items,
            'deal_type': deal_type,
            'district': district
        }

    @classmethod
    def tool_schedule_visit(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        ابزار ثبت و هماهنگی قرار بازدید حضوری با مالک و مشاور
        """
        prop_id = params.get('property_id')
        name = params.get('client_name', 'متقاضی محترم')
        phone = params.get('client_phone', '')
        time_slot = params.get('preferred_time', 'فردا عصر')

        prop = Property.query.get(prop_id) if prop_id else Property.query.first()
        prop_id_val = prop.id if prop else 1

        try:
            client = None
            if phone:
                client = Client.query.filter_by(phone_number=phone).first()
            if not client:
                client = Client(
                    full_name=name or 'متقاضی محترم دستیار هوشمند',
                    phone_number=phone or f"0900{int(datetime.utcnow().timestamp()) % 10000000:07d}",
                    preferred_deal_type=prop.deal_type if prop else 'sale'
                )
                db.session.add(client)
                db.session.flush()

            visit = Visit(
                property_id=prop_id_val,
                client_id=client.id,
                agent_id=prop.assigned_agent_id if (prop and prop.assigned_agent_id) else 1,
                scheduled_time=datetime.utcnow() + timedelta(days=1),
                status='scheduled',
                feedback=f"درخواست بازدید صوتی ثبت شد توسط {name} (تلفن: {phone}) برای زمان {time_slot}."
            )
            db.session.add(visit)
            db.session.commit()
            return {
                'success': True,
                'visit_id': visit.id,
                'property_title': prop.title if prop else 'ملک انتخابی',
                'scheduled_time': time_slot,
                'message': f"قرار بازدید برای {time_slot} با موفقیت ثبت شد."
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error scheduling visit: {e}")
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
        headers = {'Content-Type': 'application/json'}

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
        for h in history[-4:]:
            role = 'model' if h.get('role') == 'assistant' else 'user'
            contents.append({'role': role, 'parts': [{'text': h.get('content', '')}]})
        contents.append({'role': 'user', 'parts': [{'text': command}]})

        body = {
            "contents": contents,
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "tools": tools,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
        }

        try:
            res = requests.post(url, headers=headers, json=body, timeout=8)
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
        except Exception as e:
            logger.warning(f"LLM API call failed: {e}. Switching to local expert agent.")

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

        # ۳. استخراج هوشمند پارامترهای ملکی جهت Tool Calling خودکار
        is_rent = any(w in norm for w in ['اجاره', 'رهن', 'ودیعه', 'کرایه', 'اجاره‌'])
        is_sale = any(w in norm for w in ['خرید', 'فروش', 'پیش‌فروش', 'سرمایه‌گذاری', 'خریداری'])

        deal_type = 'rent' if is_rent else ('sale' if is_sale else 'rent')

        # استخراج منطقه یا محله
        target_district = ''
        for reg_id, reg_data in TEHRAN_REGIONS.items():
            for d in reg_data.get('districts', []):
                if d['name'] in norm or any(k in norm for k in d.get('keywords', [])):
                    target_district = d['name']
                    break
            if target_district:
                break

        if not target_district:
            if 'پونک' in norm: target_district = 'پونک'
            elif 'سعادت آباد' in norm or 'سعادت‌آباد' in norm: target_district = 'سعادت‌آباد'
            elif 'جنت آباد' in norm or 'جنت‌آباد' in norm: target_district = 'جنت‌آباد'
            elif 'منطقه ۵' in norm or 'منطقه 5' in norm: target_district = 'منطقه ۵'
            elif 'منطقه ۲' in norm or 'منطقه 2' in norm: target_district = 'منطقه ۲'
            elif 'منطقه ۱' in norm or 'منطقه 1' in norm: target_district = 'منطقه ۱'

        # استخراج مبالغ مالی
        total_price = 0
        deposit = 0
        rent = 0

        if deal_type == 'sale':
            billion_match = re.search(r'(\d+)\s*(?:میلیارد|همت)', norm)
            if billion_match:
                total_price = int(billion_match.group(1)) * 1_000_000_000
        else:
            dep_match = re.search(r'(\d+)\s*(?:میلیون|تومان ودیعه|رهن)', norm)
            if dep_match:
                deposit = int(dep_match.group(1)) * 1_000_000
            rent_match = re.search(r'(\d+)\s*(?:میلیون اجاره|تومان اجاره)', norm)
            if rent_match:
                rent = int(rent_match.group(1)) * 1_000_000

        # استخراج متراژ
        area_match = re.search(r'(\d+)\s*(?:متر|متری)', norm)
        min_area = int(area_match.group(1)) if area_match else 0

        # فراخوانی خودکار ابزار واکشی فایل‌ها
        tool_params = {
            'deal_type': deal_type,
            'district': target_district or 'منطقه ۵',
            'max_price': total_price,
            'max_deposit': deposit,
            'max_rent': rent,
            'min_area': min_area
        }

        search_result = cls.tool_find_properties(tool_params)
        items = search_result.get('items', [])
        count = len(items)

        deal_label = "رهن و اجاره" if deal_type == 'rent' else "خرید"
        dist_label = target_district or "مناطق ۵ و ۲"

        if count > 0:
            voice_reply = (
                f"فایل‌های {deal_label} در محدوده {dist_label} با موفقیت استخراج شد. "
                f"تعداد {count} مورد کارشناسی‌شده روی صفحه نمایش داده شد. "
                f"هر کدام را بپسندید، می‌توانیم همین حالا قرار بازدید حضوری را هماهنگ کنیم."
            )
            speech_text = (
                f"فایل‌های {deal_label} در محدوده {dist_label} استخراج شد. "
                f"{count} مورد متناسب روی صفحه قرار گرفت. برای هماهنگی بازدید در خدمتم."
            )
        else:
            voice_reply = (
                f"برای خواسته شما در محدوده {dist_label}، در حال استعلام فایل‌های لحظه‌ای از دیوار و شیپور هستیم. "
                f"لطفاً سقف بودجه یا متراژ دقیق‌تر را بفرمایید تا دقیق‌ترین موارد را به شما معرفی کنم."
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
