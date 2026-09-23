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
            'deal_type': 'rent',
            'districts': [],
            'region': '5',
            'min_area': 0,
            'max_area': 0,
            'max_deposit': 0,
            'max_rent': 0,
            'max_budget': 0,
            'features': [],
            'active_messenger': 'telegram'
        }

        # ۱. تشخیص نوع معامله
        if any(k in norm for k in ['خرید', 'فروش', 'پیش‌فروش', 'سرمایه‌گذاری', 'پیش خرید']):
            criteria['deal_type'] = 'sale'
        else:
            criteria['deal_type'] = 'rent'

        # ۲. تشخیص محله‌ها و مناطق با بررسی مرز کلمات (جلوگیری از انطباق ونک در پونک)
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
        for _, kw, d_name, reg_id in all_candidate_districts:
            pattern = r'(?:^|[^\w])' + re.escape(kw) + r'(?:[^\w]|$)'
            if re.search(pattern, norm):
                if d_name not in found_names:
                    found_names.add(d_name)
                    detected_districts.append(d_name)
                    criteria['region'] = reg_id

        # اولویت تشخیص محله و منطقه
        if not detected_districts:
            matched = find_matched_district(norm)
            if matched:
                detected_districts.append(matched)

        criteria['districts'] = detected_districts

        # ۳. استخراج متراژ
        range_match = re.search(r'(\d+)\s*(?:تا|الی|-)\s*(\d+)\s*(?:متر|متری)', norm)
        if range_match:
            try:
                criteria['min_area'] = int(range_match.group(1))
                criteria['max_area'] = int(range_match.group(2))
            except ValueError:
                pass
        else:
            area_match = re.search(r'(\d+)\s*(?:متر|متری)', norm)
            if area_match:
                try:
                    area_val = int(area_match.group(1))
                    criteria['min_area'] = max(30, area_val - 15)
                    criteria['max_area'] = area_val + 20
                except ValueError:
                    pass
            else:
                criteria['min_area'] = 0  # در صورتی که کاربر متراژ خاصی نگفت، صفر باشد

        # ۴. استخراج امکانات الزامی
        features = []
        if 'پارکینگ' in norm:
            features.append('پارکینگ')
        if 'آسانسور' in norm:
            features.append('آسانسور')
        if 'انباری' in norm:
            features.append('انباری')
        if any(b in norm for b in ['بالکن', 'تراس']):
            features.append('بالکن')
        criteria['features'] = features

        # ۵. استخراج مبالغ مالی و بودجه
        if criteria['deal_type'] == 'sale':
            amt = extract_numeric_clause_near(norm, ['میلیارد تومان', 'میلیارد', 'همت', 'قیمت کل', 'بودجه', 'سرمایه'])
            if amt > 0:
                if amt < 100_000:
                    amt = amt * 1_000_000_000
                criteria['max_budget'] = amt
            else:
                criteria['max_budget'] = 0
        else:
            # استخراج ساختار گفتاری «بین X میلیون تا Y میلیون» (ودیعه و اجاره)
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
                # استخراج ودیعه / رهن
                dep_amt = extract_numeric_clause_near(norm, ['میلیون تومان ودیعه', 'میلیون تومان رهن', 'ودیعه', 'رهن', 'پیش', 'میلیون تومان'])
                if dep_amt > 0:
                    if dep_amt < 100_000:
                        dep_amt = dep_amt * 1_000_000
                    criteria['max_deposit'] = dep_amt
                else:
                    criteria['max_deposit'] = 0

                # استخراج اجاره ماهانه
                rent_amt = extract_numeric_clause_near(norm, ['میلیون اجاره', 'میلیون تومن اجاره', 'تومان اجاره', 'اجاره در ماه', 'اجاره ماهانه', 'اجاره'])
                if rent_amt > 0:
                    if rent_amt < 100_000:
                        rent_amt = rent_amt * 1_000_000
                    criteria['max_rent'] = rent_amt
                else:
                    criteria['max_rent'] = 0

        # ۶. پیام‌رسان فعال متقاضی
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
