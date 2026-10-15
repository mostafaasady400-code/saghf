"""
ماژول تحلیل هوشمند گفتار و استخراج شروط معامله (Persian Real Estate NLP Extractor)
جهت استخراج خودکار منطقه، محله، نوع معامله، بودجه (ودیعه و اجاره یا قیمت کل)، متراژ و امکانات الزامی از متن مکالمات
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional
from data.tehran_districts import TEHRAN_REGIONS, find_matched_district
from database.db import db
from database.models import CallRecord, CustomerLead

logger = logging.getLogger(__name__)

# جدول تبدیل ارقام و واژگان فارسی به اعداد
PERSIAN_WORD_NUMBERS = {
    'یک': 1, 'دو': 2, 'سه': 3, 'چهار': 4, 'پنج': 5,
    'شش': 6, 'هفت': 7, 'هشت': 8, 'نه': 9, 'ده': 10,
    'یازده': 11, 'دوازده': 12, 'سیزده': 13, 'چهارده': 14, 'پانزده': 15,
    'شانزده': 16, 'هفده': 17, 'هجده': 18, 'نوزده': 19, 'بیست': 20,
    'سی': 30, 'چهل': 40, 'پنجاه': 50, 'شصت': 60, 'هفتاد': 70, 'هشتاد': 80, 'نود': 90,
    'صد': 100, 'دویست': 200, 'سیصد': 300, 'چهارصد': 400, 'پانصد': 500,
    'ششصد': 600, 'هفتصد': 700, 'هشتصد': 800, 'نهصد': 900,
    'هزار': 1_000,
    'میلیون': 1_000_000,
    'میلیارد': 1_000_000_000,
    'همت': 1_000_000_000_000
}

def normalize_persian_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('ة', 'ه')
    # تبدیل ارقام فارسی به انگلیسی
    fa_digits = '۰۱۲۳۴۵۶۷۸۹'
    en_digits = '0123456789'
    trans = str.maketrans(fa_digits, en_digits)
    return text.translate(trans)

def parse_persian_money_amount(text: str) -> int:
    """
    استخراج مبالغ ریالی/تومانی از ساختارهای متنی فارسی مانند:
    'پانصد میلیون'، '۶۰۰ میلیون'، '۲ میلیارد'، 'بیست و پنج میلیون'
    خروجی: مبلغ به تومان (عدد صحیح)
    """
    if not text:
        return 0
    norm = normalize_persian_text(text).lower()

    # الگوی عددی صریح با پسوند میلیون / میلیارد
    # مثال: 500 میلیون یا 2.5 میلیارد
    match = re.search(r'([\d\.\,]+)\s*(میلیارد|میلیون|تومان|تومن)', norm)
    if match:
        num_str = match.group(1).replace(',', '')
        unit = match.group(2)
        try:
            val = float(num_str)
            if 'میلیارد' in unit:
                return int(val * 1_000_000_000)
            elif 'میلیون' in unit:
                return int(val * 1_000_000)
            elif 'تومان' in unit or 'تومن' in unit:
                return int(val)
        except ValueError:
            pass

    # تحلیل واژگانی عددی
    total = 0
    current = 0
    words = re.findall(r'[\w]+', norm)
    has_money_words = False

    for w in words:
        if w in PERSIAN_WORD_NUMBERS:
            has_money_words = True
            v = PERSIAN_WORD_NUMBERS[w]
            if v == 1_000_000_000:
                current = max(1, current) * 1_000_000_000
                total += current
                current = 0
            elif v == 1_000_000:
                current = max(1, current) * 1_000_000
                total += current
                current = 0
            elif v == 1_000:
                current = max(1, current) * 1_000
                total += current
                current = 0
            else:
                current += v

    total += current
    return total if has_money_words else 0

def extract_numeric_clause_near(text: str, marker_words: List[str]) -> int:
    """
    استخراج عدد نزدیک به کلمات کلیدی (مثلاً اجاره یا ودیعه)
    با جداسازی دقیق واژگان عددی فارسی قبل یا بعد از کلیدواژه
    """
    norm = normalize_persian_text(text)
    # ۱. جستجوی عبارت بلافاصله قبل از کلیدواژه
    for kw in marker_words:
        pos = norm.find(kw)
        if pos != -1:
            sub = norm[:pos].strip()
            words = sub.split()
            valid_words = []
            for w in reversed(words):
                w_clean = w.strip('،.:؛!؟()[]')
                if w_clean in PERSIAN_WORD_NUMBERS or w_clean.isdigit() or w_clean == 'و':
                    valid_words.insert(0, w_clean)
                else:
                    break
            if valid_words:
                amt = parse_persian_money_amount(' '.join(valid_words))
                if amt > 0:
                    return amt

    # ۲. جستجوی عبارت بلافاصله بعد از کلیدواژه
    for kw in marker_words:
        pos = norm.find(kw)
        if pos != -1:
            sub = norm[pos + len(kw):].strip()
            words = sub.split()
            valid_words = []
            for w in words:
                w_clean = w.strip('،.:؛!؟()[]')
                if w_clean in PERSIAN_WORD_NUMBERS or w_clean.isdigit() or w_clean == 'و' or w_clean in ['تا', 'حداکثر', 'حدود']:
                    if w_clean not in ['تا', 'حداکثر', 'حدود']:
                        valid_words.append(w_clean)
                else:
                    break
            if valid_words:
                amt = parse_persian_money_amount(' '.join(valid_words))
                if amt > 0:
                    return amt

    return 0

class PropertyLeadNLPExtractor:
    """
    موتور استخراج هوشمند نیازهای ملکی و پروفایل متقاضی
    """

    @classmethod
    def extract_criteria(cls, text: str) -> Dict[str, Any]:
        """
        استخراج پارامترهای اصلی شامل نوع معامله، محله‌ها، بودجه، متراژ و امکانات
        """
        norm = normalize_persian_text(text)
        criteria: Dict[str, Any] = {
            'deal_type': 'any',
            'deal_type_fa': 'نامشخص',
            'property_type': 'apartment',
            'property_type_fa': 'آپارتمان',
            'districts': [],
            'region': '5',
            'min_area': 0,
            'max_area': 0,
            'rooms': None,
            'min_budget': 0,
            'max_budget': 0,
            'min_deposit': 0,
            'max_deposit': 0,
            'min_rent': 0,
            'max_rent': 0,
            'features': [],
            'descriptive_tags': [],
            'has_parking': False,
            'has_elevator': False,
            'has_warehouse': False,
            'has_balcony': False,
            'active_messenger': 'telegram'
        }

        # ۱. تشخیص نوع معامله (خرید / رهن / اجاره)
        if any(k in norm for k in ['خرید', 'فروش', 'پیش‌فروش', 'پیش فروش', 'سرمایه‌گذاری', 'سرمایه گذاری', 'پیش خرید']) or (any(k in norm for k in ['میلیارد', 'همت']) and not any(r in norm for r in ['اجاره', 'ودیعه', 'رهن', 'ماهانه', 'ماهی'])):
            criteria['deal_type'] = 'sale'
            criteria['deal_type_fa'] = 'خرید و فروش'
        elif any(k in norm for k in ['رهن کامل', 'فقط رهن', 'بدون اجاره']):
            criteria['deal_type'] = 'rent'
            criteria['deal_type_fa'] = 'رهن کامل'
        elif any(k in norm for k in ['اجاره', 'ودیعه', 'رهن', 'ماهانه', 'ماهی', 'مستاجر', 'مستأجر']):
            criteria['deal_type'] = 'rent'
            criteria['deal_type_fa'] = 'رهن و اجاره'

        # ۲. تشخیص نوع کاربری (مسکونی / تجاری / زمین / ویلا)
        if any(k in norm for k in ['تجاری', 'مغازه', 'اداری', 'دفتر کار', 'مطب', 'پاساژ']):
            criteria['property_type'] = 'commercial'
            criteria['property_type_fa'] = 'تجاری و اداری'
        elif any(k in norm for k in ['زمین', 'کلنگی', 'مشارکت در ساخت', 'تراکم']):
            criteria['property_type'] = 'land'
            criteria['property_type_fa'] = 'زمین و کلنگی'
        elif any(k in norm for k in ['ویلا', 'ویلایی', 'باغ', 'عمارت', 'دوبلکس', 'تریپلکس']):
            criteria['property_type'] = 'villa'
            criteria['property_type_fa'] = 'ویلا'
        else:
            criteria['property_type'] = 'apartment'
            criteria['property_type_fa'] = 'آپارتمان'

        # ۳. تشخیص محله‌ها و مناطق
        detected_districts = []
        all_candidate_districts = []
        for reg_id, reg_data in TEHRAN_REGIONS.items():
            for d in reg_data['districts']:
                keywords = d.get('keywords', []) + [d['name']]
                for kw in keywords:
                    if kw:
                        all_candidate_districts.append((len(kw), kw, d['name'], reg_id))

        all_candidate_districts.sort(key=lambda x: x[0], reverse=True)

        found_names = set()
        # عبارات فعل مرکب با کن که نباید با محله «کن» اشتباه شوند
        verb_kan_patterns = [r'پیدا\s*کن', r'جستجو\s*کن', r'معرفی\s*کن', r'استخراج\s*کن', r'بررسی\s*کن', r'چک\s*کن', r'مشخص\s*کن', r'ثبت\s*کن', r'انتخاب\s*کن', r'درست\s*کن', r'کمک\s*کن']

        for _, kw, d_name, reg_id in all_candidate_districts:
            pattern = r'(?:^|[^\w])' + re.escape(kw) + r'(?:[^\w]|$)'
            if re.search(pattern, norm):
                # اگر کلمه کلیدی کن بود ولی در حقیقت فعل جمله بود نادیده گرفته شود
                if kw == 'کن' and any(re.search(vp, norm) for vp in verb_kan_patterns):
                    continue
                if d_name not in found_names:
                    found_names.add(d_name)
                    detected_districts.append(d_name)
                    criteria['region'] = reg_id

        # اگر منطقه ۵ یا منطقه ۲ در متن ذکر شده بود
        if any(r in norm for r in ['منطقه ۵', 'منطقه 5', 'منطقه پنج']) and 'منطقه ۵' not in detected_districts:
            detected_districts.append('منطقه ۵')
            criteria['region'] = 'region_5'
        if any(r in norm for r in ['منطقه ۲', 'منطقه 2', 'منطقه دو', 'یا ۲', 'یا 2']) and 'منطقه ۲' not in detected_districts:
            detected_districts.append('منطقه ۲')
            if not criteria.get('region'):
                criteria['region'] = 'region_2'

        if not detected_districts:
            matched = find_matched_district(norm)
            if matched:
                detected_districts.append(matched)

        criteria['districts'] = detected_districts

        # ۴. استخراج متراژ
        range_match = re.search(r'(\d+)\s*(?:تا|الی|-)\s*(\d+)\s*(?:متر|متری)', norm)
        if range_match:
            try:
                criteria['min_area'] = int(range_match.group(1))
                criteria['max_area'] = int(range_match.group(2))
                criteria['area_match_mode'] = 'range'
            except ValueError:
                pass
        else:
            area_match = re.search(r'(\d+)\s*(?:متر|متری)', norm)
            if area_match:
                try:
                    area_val = int(area_match.group(1))
                    # «۸۰ متری» یک مقدار صریح است؛ دامنهٔ دلخواه اختراع نمی‌کنیم.
                    criteria['min_area'] = area_val
                    criteria['max_area'] = area_val
                    criteria['area_match_mode'] = 'exact'
                except ValueError:
                    pass

        # ۵. استخراج تعداد اتاق خواب
        rooms_match = re.search(r'(\d+)\s*(?:خواب|خوابه|اتاق)', norm)
        if rooms_match:
            try:
                criteria['rooms'] = int(rooms_match.group(1))
            except ValueError:
                pass
        elif 'تک خواب' in norm or 'یک خواب' in norm:
            criteria['rooms'] = 1
        elif 'دو خواب' in norm:
            criteria['rooms'] = 2
        elif 'سه خواب' in norm or '۳ خواب' in norm:
            criteria['rooms'] = 3
        elif 'چهار خواب' in norm:
            criteria['rooms'] = 4
        elif 'سوئیت' in norm or 'بدون اتاق' in norm:
            criteria['rooms'] = 0
        if criteria['rooms'] is not None:
            criteria['rooms_match_mode'] = 'exact'

        # ۶. استخراج امکانات الزامی و فیزیکی
        features = []
        if 'پارکینگ' in norm:
            features.append('پارکینگ')
            criteria['has_parking'] = True
        if 'آسانسور' in norm:
            features.append('آسانسور')
            criteria['has_elevator'] = True
        if 'انباری' in norm:
            features.append('انباری')
            criteria['has_warehouse'] = True
        if any(b in norm for b in ['بالکن', 'تراس']):
            features.append('بالکن')
            criteria['has_balcony'] = True
        criteria['features'] = features

        # ۷. تبدیل عبارات توصیفی کاربر به فیلترهای تحلیلی
        descriptive_tags = []
        if any(m in norm for m in ['مترو', 'ایستگاه مترو', 'نزدیک مترو', 'دسترسی مترو']):
            descriptive_tags.append('نزدیک ایستگاه مترو')
        if any(m in norm for m in ['خوش نقشه', 'خوشنقشه', 'خوش چیدمان', 'بدون پرتی']):
            descriptive_tags.append('خوش‌نقشه')
        if any(m in norm for m in ['نورگیر', 'نورگیر عالی', 'غرق نور', 'رو به آفتاب', 'آفتابگیر']):
            descriptive_tags.append('نورگیر عالی')
        if any(m in norm for m in ['فول امکانات', 'فول', 'کامل']):
            descriptive_tags.append('فول امکانات')
        if any(m in norm for m in ['نوساز', 'کلید نخورده', 'صفر']):
            descriptive_tags.append('نوساز و کلید نخورده')
        if any(m in norm for m in ['شخصی ساز', 'شخصیساز', 'شخصی']):
            descriptive_tags.append('شخصی‌ساز')
        if any(m in norm for m in ['بازسازی', 'بازسازی شده', 'شیک']):
            descriptive_tags.append('بازسازی شده')
        if any(m in norm for m in ['تخلیه', 'اماده تخلیه', 'آماده تحویل']):
            descriptive_tags.append('تخلیه و آماده سکونت')

        criteria['descriptive_tags'] = descriptive_tags

        # ۸. استخراج مبالغ مالی و بودجه (کف و سقف)
        if criteria['deal_type'] == 'sale':
            range_budget = re.search(r'(\d+)\s*(?:تا|الی|-)\s*(\d+)\s*میلیارد', norm)
            if range_budget:
                criteria['min_budget'] = int(range_budget.group(1)) * 1_000_000_000
                criteria['max_budget'] = int(range_budget.group(2)) * 1_000_000_000
            else:
                amt = extract_numeric_clause_near(norm, ['میلیارد تومان', 'میلیارد', 'همت', 'قیمت کل', 'بودجه', 'سرمایه'])
                if amt > 0:
                    if amt < 100_000:
                        amt = amt * 1_000_000_000
                    criteria['max_budget'] = amt
        else:
            # الگوی محاوره‌ای دو رقمی رهن و اجاره: مثال «۱ تومن ۶۰ تومن» یا «۱ میلیارد ۶۰ میلیون»
            colloquial_match = re.search(r'(\d+)\s*(?:تومن|تومان|میلیارد|همت)\s*(\d+)\s*(?:تومن|تومنه|تومان|میلیون)', norm)
            if colloquial_match:
                v1 = int(colloquial_match.group(1))
                v2 = int(colloquial_match.group(2))
                # در بازار ملک تهران: عدد اول ودیعه (مثلاً ۱ میلیارد) و عدد دوم اجاره ماهانه (مثلاً ۶۰ میلیون)
                if v1 <= 20: # زیر ۲۰ معمولاً به معنی میلیارد تومان است (مثلاً ۱ تومن = ۱ میلیارد)
                    criteria['max_deposit'] = v1 * 1_000_000_000
                else:
                    criteria['max_deposit'] = v1 * 1_000_000
                
                if v2 < 1000: # مثلاً ۶۰ تومن اجاره = ۶۰ میلیون تومان
                    criteria['max_rent'] = v2 * 1_000_000
                else:
                    criteria['max_rent'] = v2
            else:
                between_match = re.search(r'بین\s*([\d\.\,]+)\s*(میلیارد|میلیون)\s*(?:ودیعه|رهن)?\s*تا\s*([\d\.\,]+)\s*(میلیارد|میلیون)\s*(?:اجاره)?', norm)
                if between_match:
                    v1 = float(between_match.group(1).replace(',', ''))
                    u1 = between_match.group(2)
                    v2 = float(between_match.group(3).replace(',', ''))
                    u2 = between_match.group(4)
                    amt1 = int(v1 * (1_000_000_000 if 'میلیارد' in u1 else 1_000_000))
                    amt2 = int(v2 * (1_000_000_000 if 'میلیارد' in u2 else 1_000_000))
                    criteria['max_deposit'] = max(amt1, amt2)
                    criteria['max_rent'] = min(amt1, amt2)
                else:
                    dep_amt = extract_numeric_clause_near(norm, ['میلیون تومان ودیعه', 'میلیون تومان رهن', 'ودیعه', 'رهن', 'پیش', 'میلیون تومان'])
                    if dep_amt > 0:
                        if dep_amt < 100_000:
                            dep_amt = dep_amt * 1_000_000
                        criteria['max_deposit'] = dep_amt

                    rent_amt = extract_numeric_clause_near(norm, ['میلیون اجاره', 'میلیون تومن اجاره', 'تومان اجاره', 'اجاره در ماه', 'اجاره ماهانه', 'اجاره'])
                    if rent_amt > 0:
                        if rent_amt < 100_000:
                            rent_amt = rent_amt * 1_000_000
                        criteria['max_rent'] = rent_amt

        # ۹. پیام‌رسان فعال
        if 'ایتا' in norm:
            criteria['active_messenger'] = 'eitaa'
        elif 'بله' in norm:
            criteria['active_messenger'] = 'bale'
        elif 'واتساپ' in norm or 'whatsapp' in norm.lower():
            criteria['active_messenger'] = 'whatsapp'
        elif 'روبیکا' in norm:
            criteria['active_messenger'] = 'rubika'
        else:
            criteria['active_messenger'] = 'telegram'

        return criteria

    @classmethod
    def process_call_and_save_lead(cls, call_id: Optional[str], caller_phone: str, audio_url: Optional[str], transcribed_text: str, duration_seconds: int = 0) -> Dict[str, Any]:
        """
        پردازش مکالمه و ذخیره دوطرفه در جداول CallRecord و CustomerLead
        """
        from datetime import datetime

        criteria = cls.extract_criteria(transcribed_text)

        # ۱. ذخیره یا به‌روزرسانی در CallRecord
        call_record = None
        if call_id:
            call_record = CallRecord.query.filter_by(call_id=call_id).first()

        if not call_record:
            call_record = CallRecord(
                call_id=call_id or f"CALL-{int(datetime.utcnow().timestamp())}",
                caller_phone=caller_phone,
                audio_url=audio_url,
                transcribed_text=transcribed_text,
                extracted_criteria_json=json.dumps(criteria, ensure_ascii=False),
                processing_status='analyzed',
                duration_seconds=duration_seconds,
                created_at=datetime.utcnow()
            )
            db.session.add(call_record)
        else:
            call_record.transcribed_text = transcribed_text
            call_record.extracted_criteria_json = json.dumps(criteria, ensure_ascii=False)
            call_record.processing_status = 'analyzed'
            call_record.duration_seconds = duration_seconds

        # ۲. ثبت یا به‌روزرسانی سرنخ در CustomerLead
        lead = CustomerLead.query.filter_by(phone_number=caller_phone).first()
        if not lead:
            lead = CustomerLead(
                phone_number=caller_phone,
                full_name=f"متقاضی {criteria['districts'][0] if criteria['districts'] else 'منطقه ۵'}",
                deal_type=criteria['deal_type'],
                preferred_districts_json=json.dumps(criteria['districts'], ensure_ascii=False),
                min_budget=0,
                max_budget=criteria.get('max_budget', 0),
                max_deposit=criteria.get('max_deposit', 0),
                max_rent=criteria.get('max_rent', 0),
                min_area=criteria.get('min_area', 0),
                preferred_features_json=json.dumps(criteria.get('features', []), ensure_ascii=False),
                active_messenger=criteria.get('active_messenger', 'telegram'),
                last_interaction_at=datetime.utcnow(),
                created_at=datetime.utcnow()
            )
            db.session.add(lead)
        else:
            lead.deal_type = criteria['deal_type']
            lead.preferred_districts_json = json.dumps(criteria['districts'], ensure_ascii=False)
            if criteria['deal_type'] == 'sale':
                lead.max_budget = criteria.get('max_budget', 0)
            else:
                lead.max_deposit = criteria.get('max_deposit', 0)
                lead.max_rent = criteria.get('max_rent', 0)
            lead.min_area = criteria.get('min_area', 0)
            lead.preferred_features_json = json.dumps(criteria.get('features', []), ensure_ascii=False)
            lead.active_messenger = criteria.get('active_messenger', lead.active_messenger)
            lead.last_interaction_at = datetime.utcnow()

        db.session.commit()

        return {
            'call_record': call_record.to_dict(),
            'customer_lead': lead.to_dict(),
            'criteria': criteria
        }
