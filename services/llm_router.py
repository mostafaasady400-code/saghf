"""
ماژول تحلیل زبانی هوشمند و کلاسیفایر نقش (LLM Router)
تفکیک دقیق پیام‌ها، ویس‌ها، پیامک‌ها و چت‌ها به دو گروه:
۱. نقش مالک ملک (Property Owner): قصد فروش، رهن یا اجاره دادن ملک
۲. نقش متقاضی / خریدار / مستأجر (Buyer / Tenant Lead): قصد خرید، رهن یا اجاره گرفتن ملک
تولید خروجی ساختاریافته JSON جهت تزریق خودکار به پایگاه‌های داده CRM تفکیک‌شده
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional

from data.tehran_districts import TEHRAN_REGIONS, find_matched_district
from services.nlp_extractor import normalize_persian_text, parse_persian_money_amount, extract_numeric_clause_near

logger = logging.getLogger(__name__)

class SemanticLLMRouter:
    """
    روتر و کلاسیفایر هوشمند معنایی با خروجی ساختاریافته JSON
    پشتیبانی از مدل‌های روز Gemini API و فال‌بک هوشمند و مقاوم قانون‌محور (Rule-Based Fallback)
    """

    OWNER_KEYWORDS = [
        'ملک دارم', 'خونه دارم', 'اپارتمان دارم', 'آپارتمان دارم', 'یک واحد دارم',
        'واگذار کنم', 'بفروشم', 'برای فروش گذاشتم', 'برای اجاره گذاشتم', 'می‌خوام بفروشم',
        'میخوام بفروشم', 'می‌خوام اجاره بدم', 'میخوام اجاره بدم', 'رهن بدم', 'اجاره بدم',
        'فروشنده ام', 'فروشنده هستم', 'مالکم', 'مالک هستم', 'صاحب ملکم', 'صاحبخانه',
        'ثبت فایل', 'ثبت اگهی', 'ثبت آگهی', 'فایلم رو ثبت کنید', 'فروش فوری ملک من'
    ]

    LEAD_KEYWORDS = [
        'دنبال ملکم', 'دنبال خونه ام', 'دنبال آپارتمانم', 'دنبال', 'می‌خوام بخرم', 'میخوام بخرم',
        'برای خرید', 'خرید آپارتمان', 'خرید ملک', 'خرید خانه', 'خرید واحد', 'قصد خرید',
        'می‌خوام اجاره کنم', 'میخوام اجاره کنم', 'برای اجاره', 'رهن و اجاره می‌خوام', 'خریدارم',
        'متقاضی ام', 'متقاضی هستم', 'متقاضی', 'بودجه من', 'بودجه دارم', 'بودجه', 'فایل برای معرفی دارید',
        'پیشنهاد بدید', 'فایلی دارید', 'موردی سراغ دارید', 'چی دارید', 'معرفی کنید'
    ]

    @classmethod
    def classify_and_extract(cls, text: str, sender_phone: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        پردازش جامع متن یا ترنسکریپت صوتی و استخراج موجودیت‌ها در ساختار JSON استاندارد
        """
        if not text or not text.strip():
            return {
                'role': 'unknown',
                'confidence': 0.0,
                'deal_type': 'rent',
                'summary': 'متن ورودی خالی است',
                'owner_payload': None,
                'lead_payload': None
            }

        norm_text = normalize_persian_text(text)

        # تلاش ۱: استفاده از Gemini API در صورت دسترسی به کلید API
        gemini_result = cls._try_gemini_extraction(norm_text, sender_phone, metadata)
        if gemini_result and gemini_result.get('role') in ['owner', 'lead']:
            return gemini_result

        # تلاش ۲: استفاده از کلاسیفایر هوشمند محلی (Heuristic & Rule-Based Fallback)
        logger.info("Using resilient local NLP classifier for semantic role routing.")
        return cls._local_rule_extraction(norm_text, sender_phone, metadata)

    @classmethod
    def _try_gemini_extraction(cls, text: str, sender_phone: str, metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        ارسال به Gemini API با استخراج مستقیم خروجی ساختاریافته JSON
        """
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            return None

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            system_instruction = (
                "شما هوش مصنوعی ارشد تحلیل مکالمات و متون در سامانه مشاور املاک 'سقف' هستید. "
                "وظیفه شما تفکیک هویت مخاطب به یکی از دو نقش زیر است:\n"
                "1. 'owner' (مالک یا صاحب‌ملک): فردی که قصد دارد ملک شخصی خود را بفروشد یا به رهن/اجاره واگذار نماید.\n"
                "2. 'lead' (متقاضی/مشتری): فردی که قصد خرید ملک یا رهن/اجاره کردن ملکی را دارد.\n\n"
                "شما باید خروجی را دقیقاً در قالب فرمت JSON زیر بدون هیچ متن اضافی برگردانید:\n"
                "{\n"
                '  "role": "owner" | "lead",\n'
                '  "confidence": 0.95,\n'
                '  "deal_type": "sale" | "rent",\n'
                '  "property_type": "apartment" | "villa" | "commercial" | "land" | "office",\n'
                '  "summary": "خلاصه درخواست مخاطب به زبان فارسی",\n'
                '  "owner_payload": {\n'
                '    "title": "عنوان آگهی پیشنهادی",\n'
                '    "district": "نام محله (مثلاً پونک، جنت‌آباد)",\n'
                '    "city": "تهران",\n'
                '    "area": 100,\n'
                '    "rooms": 2,\n'
                '    "floor": 3,\n'
                '    "total_price": 6500000000,\n'
                '    "deposit": 0,\n'
                '    "monthly_rent": 0,\n'
                '    "has_parking": true,\n'
                '    "has_elevator": true,\n'
                '    "has_warehouse": true,\n'
                '    "has_balcony": true,\n'
                '    "features": ["پارکینگ", "آسانسور"],\n'
                '    "document_status": "سند تک‌برگ",\n'
                '    "owner_name": "نام مالک در صورت ذکر شدن",\n'
                '    "notes": "نکات تکمیلی"\n'
                '  },\n'
                '  "lead_payload": {\n'
                '    "full_name": "نام متقاضی",\n'
                '    "preferred_districts": ["پونک", "جنت‌آباد"],\n'
                '    "region": "5",\n'
                '    "min_budget": 0,\n'
                '    "max_budget": 5000000000,\n'
                '    "max_deposit": 500000000,\n'
                '    "max_rent": 20000000,\n'
                '    "min_area": 80,\n'
                '    "max_area": 110,\n'
                '    "preferred_features": ["پارکینگ", "آسانسور"],\n'
                '    "active_messenger": "telegram" | "bale" | "whatsapp" | "eitaa" | "rubika"\n'
                '  }\n'
                "}"
            )

            prompt = f"متن پیام یا پیاده‌سازی صوت مکالمه مخاطب:\n«««\n{text}\n»»»\nشماره تماس: {sender_phone}"

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )

            if response and response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, dict) and 'role' in parsed:
                    return parsed
        except Exception as e:
            logger.warning(f"Gemini semantic classification failed: {e}. Moving to rule-based fallback.")

        return None

    @classmethod
    def _local_rule_extraction(cls, text: str, sender_phone: str, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        کلاسیفایر هوشمند محلی و کاملاً مستقل بدون نیاز به اینترنت
        تضمین‌کننده فعالیت مداوم سامانه تحت هر شرایط
        """
        # الگوهای ساختاری قوی نقش مالک: داشتن ملک، قصد فروش یا اجاره دادن
        owner_patterns = [
            r'(?:یک واحد|واحد|آپارتمان|ملک|خونه|ساختمان|مغازه|زمین).*?دارم',
            r'دارم برای (?:اجاره|فروش|رهن)',
            r'برای (?:اجاره|فروش|رهن) دارم',
            r'مالک(?:م| هستم)',
            r'صاحب (?:ملک|خونه)',
            r'فروشنده(?:‌ام| هستم| ام)',
            r'می‌?خوام (?:بفروشم|اجاره بدم|رهن بدم)',
            r'واگذار (?:می‌?کنم|کنم)',
            r'سند تک‌?برگ'
        ]

        # الگوهای ساختاری قوی نقش متقاضی: متقاضی خرید یا اجاره، بودجه، جستجوی فایل
        lead_patterns = [
            r'دنبال (?:ملک|خونه|آپارتمان|واحد|مورد|مغازه)',
            r'می‌?خوام (?:بخرم|اجاره کنم|رهن کنم)',
            r'برای خرید',
            r'قصد (?:خرید|اجاره|رهن)',
            r'خریدار(?:م| هستم)',
            r'متقاضی(?:‌ام| هستم| ام)?',
            r'بودجه.*?(?:دارم|من|هست)',
            r'پیشنهاد بدید',
            r'سراغ دارید',
            r'فایل.*?دارید'
        ]

        owner_score = sum(1 for kw in cls.OWNER_KEYWORDS if kw in text) + sum(3 for pat in owner_patterns if re.search(pat, text))
        lead_score = sum(1 for kw in cls.LEAD_KEYWORDS if kw in text) + sum(3 for pat in lead_patterns if re.search(pat, text))

        # اگر نوع معامله فروش یا اجاره باشد
        is_sale = any(k in text for k in ['خرید', 'فروش', 'فروشی', 'پیش‌فروش', 'سرمایه‌گذاری'])
        deal_type = 'sale' if is_sale else 'rent'

        # تشخیص نقش
        if owner_score > lead_score:
            role = 'owner'
        elif lead_score > owner_score:
            role = 'lead'
        else:
            if any(k in text for k in ['ملک دارم', 'آپارتمان دارم', 'خونه دارم', 'واحد دارم', 'کلید دارم', 'واگذار', 'سند تک‌برگ']):
                role = 'owner'
            else:
                role = 'lead'

        # استخراج مناطق و محله‌ها
        detected_districts = []
        target_region = '5'

        # نگاشت محله‌های پرکاربرد و ریشه‌ای تهران جهت تطابق سریع و دقیق
        COMMON_BASE_DISTRICTS = {
            'جنت‌آباد': ('جنت‌آباد', '5'),
            'جنت اباد': ('جنت‌آباد', '5'),
            'پونک': ('پونک', '5'),
            'صادقیه': ('صادقیه', '5'),
            'شهران': ('شهران', '5'),
            'فردوس': ('بلوار فردوس', '5'),
            'بلوار فردوس': ('بلوار فردوس', '5'),
            'سعادت‌آباد': ('سعادت‌آباد', '2'),
            'سعادت اباد': ('سعادت‌آباد', '2'),
            'شهرک غرب': ('شهرک غرب', '2'),
            'گیشا': ('گیشا', '2'),
            'مرزداران': ('مرزداران', '2'),
            'ستارخان': ('ستارخان', '2'),
            'تهرانپارس': ('تهرانپارس', '4'),
            'نیاوران': ('نیاوران', '1'),
            'زعفرانیه': ('زعفرانیه', '1'),
            'الهیه': ('الهیه', '1'),
            'ولنجک': ('ولنجک', '1'),
            'پاسداران': ('پاسداران', '3'),
            'ونک': ('ونک', '3')
        }

        for base_kw, (canon_name, b_reg) in COMMON_BASE_DISTRICTS.items():
            pattern = r'(?:^|[^\w])' + re.escape(base_kw) + r'(?:[^\w]|$)'
            if re.search(pattern, text):
                if canon_name not in detected_districts:
                    detected_districts.append(canon_name)
                    target_region = b_reg

        for reg_id, reg_data in TEHRAN_REGIONS.items():
            for d in reg_data.get('districts', []):
                keywords = list(d.get('keywords', [])) + [d['name']]
                # اضافه کردن فرم ریشه بدون پیشوند و پسوندهای مکانی
                for kw in keywords:
                    if kw and re.search(r'(?:^|[^\w])' + re.escape(kw) + r'(?:[^\w]|$)', text):
                        if d['name'] not in detected_districts:
                            detected_districts.append(d['name'])
                            target_region = reg_id

        if not detected_districts:
            matched = find_matched_district(text)
            if matched:
                detected_districts.append(matched)

        primary_district = detected_districts[0] if detected_districts else 'منطقه ۵'

        # استخراج متراژ
        min_area, max_area = 0, 0
        range_match = re.search(r'(\d+)\s*(?:تا|الی|-)\s*(\d+)\s*(?:متر|متری)', text)
        if range_match:
            min_area = int(range_match.group(1))
            max_area = int(range_match.group(2))
        else:
            area_match = re.search(r'(\d+)\s*(?:متر|متری)', text)
            if area_match:
                single_area = int(area_match.group(1))
                min_area = single_area
                max_area = single_area + 15

        # استخراج امکانات
        features = []
        has_parking = 'پارکینگ' in text
        has_elevator = 'آسانسور' in text
        has_warehouse = 'انباری' in text
        has_balcony = any(b in text for b in ['بالکن', 'تراس'])
        if has_parking: features.append('پارکینگ')
        if has_elevator: features.append('آسانسور')
        if has_warehouse: features.append('انباری')
        if has_balcony: features.append('بالکن')

        # استخراج مبالغ مالی
        total_price, deposit, rent = 0, 0, 0
        if deal_type == 'sale':
            total_price = extract_numeric_clause_near(text, ['میلیارد تومان', 'میلیارد', 'همت', 'قیمت کل', 'بودجه', 'قیمت'])
            if 0 < total_price < 100_000:
                total_price = total_price * 1_000_000_000
        else:
            deposit = extract_numeric_clause_near(text, ['میلیون تومان ودیعه', 'ودیعه', 'رهن', 'پیش'])
            if 0 < deposit < 100_000:
                deposit = deposit * 1_000_000
            rent = extract_numeric_clause_near(text, ['میلیون اجاره', 'تومان اجاره', 'اجاره ماهانه', 'اجاره'])
            if 0 < rent < 100_000:
                rent = rent * 1_000_000

        # تشخیص پیام‌رسان فعال
        active_messenger = 'telegram'
        if 'ایتا' in text or metadata.get('channel') == 'eitaa':
            active_messenger = 'eitaa'
        elif 'بله' in text or metadata.get('channel') == 'bale':
            active_messenger = 'bale'
        elif 'واتساپ' in text or 'whatsapp' in text.lower() or metadata.get('channel') == 'whatsapp':
            active_messenger = 'whatsapp'
        elif 'روبیکا' in text or metadata.get('channel') == 'rubika':
            active_messenger = 'rubika'
        elif metadata.get('channel') == 'instagram':
            active_messenger = 'instagram'

        # تشخیص وضعیت مدارک
        doc_status = 'در دست بررسی'
        if 'تک برگ' in text or 'تک‌برگ' in text:
            doc_status = 'سند تک‌برگ عرصه و عیان'
        elif 'قولنامه' in text:
            doc_status = 'قولنامه‌ای معتبر با کد رهگیری'
        elif 'اوقاف' in text:
            doc_status = 'اوقافی'

        owner_payload = None
        lead_payload = None

        if role == 'owner':
            area_val = min_area if min_area > 0 else 85
            owner_payload = {
                'title': f"ملک شخصی {primary_district} ({area_val} متری)",
                'district': primary_district,
                'city': 'تهران',
                'area': area_val,
                'rooms': 2,
                'floor': 2,
                'deal_type': deal_type,
                'total_price': total_price,
                'deposit': deposit,
                'monthly_rent': rent,
                'has_parking': has_parking,
                'has_elevator': has_elevator,
                'has_warehouse': has_warehouse,
                'has_balcony': has_balcony,
                'features': features,
                'document_status': doc_status,
                'owner_name': metadata.get('sender_name') or f"مالک {primary_district}",
                'phone': sender_phone or metadata.get('sender_id', ''),
                'notes': f"دریافت شده از درگاه {metadata.get('channel', 'omnichannel')}"
            }
        else:
            lead_payload = {
                'full_name': metadata.get('sender_name') or f"متقاضی {primary_district}",
                'phone': sender_phone or metadata.get('sender_id', ''),
                'deal_type': deal_type,
                'preferred_districts': detected_districts if detected_districts else [primary_district],
                'region': target_region,
                'min_budget': 0,
                'max_budget': total_price,
                'max_deposit': deposit,
                'max_rent': rent,
                'min_area': min_area,
                'max_area': max_area if max_area > 0 else min_area + 20,
                'preferred_features': features,
                'active_messenger': active_messenger
            }

        deal_label = 'فروش' if deal_type == 'sale' else 'رهن و اجاره'
        role_label = 'مالک ملک' if role == 'owner' else 'متقاضی ملک'

        return {
            'role': role,
            'confidence': 0.88,
            'deal_type': deal_type,
            'summary': f"پیام با نقش {role_label} در حوزه {deal_label} در محدوده {primary_district}",
            'owner_payload': owner_payload,
            'lead_payload': lead_payload
        }
