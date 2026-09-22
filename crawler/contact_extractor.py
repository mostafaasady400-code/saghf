"""
Contact Number Extraction & Verification Engine for Saghf Platform.
Extracts, decodes, normalizes, and validates Iranian mobile & landline phone numbers
from raw texts, obfuscated strings, Persian words, and deep JSON API payloads.
Zero-Mock Implementation.
"""

import re
from typing import Optional, Dict, Any, List, Set, Tuple

class ContactExtractor:
    """
    موتور متمرکز استخراج و اعتبارسنجی شماره تماس مالکین
    پشتیبانی از دیکودر ارقام حروفی فارسی، تشخیص اپراتور، فیلتر شماره‌های جعلی،
    و جستجوی بازگشتی در اشیاء و ویجت‌های پلتفرم‌های دیوار و شیپور
    """

    # نقشه‌های تبدیل اعداد حروفی فارسی به ارقام
    COMPOUND_PREFIXES = {
        'صفر نهصد و دوازده': '0912',
        'نهصد و دوازده': '0912',
        'صفر نهصد و نوزده': '0919',
        'نهصد و نوزده': '0919',
        'صفر نهصد و هجده': '0918',
        'نهصد و هجده': '0918',
        'صفر نهصد و هفده': '0917',
        'نهصد و هفده': '0917',
        'صفر نهصد و شانزده': '0916',
        'نهصد و شانزده': '0916',
        'صفر نهصد و پانزده': '0915',
        'نهصد و پانزده': '0915',
        'صفر نهصد و چهارده': '0914',
        'نهصد و چهارده': '0914',
        'صفر نهصد و سیزده': '0913',
        'نهصد و سیزده': '0913',
        'صفر نهصد و ده': '0910',
        'نهصد و ده': '0910',
        'صفر نهصد و سی و نه': '0939',
        'نهصد و سی و نه': '0939',
        'صفر نهصد و سی و هشت': '0938',
        'نهصد و سی و هشت': '0938',
        'نهصد و سی و هفت': '0937',
        'نهصد و سی و هفت': '0937',
        'صفر نهصد و سی و شش': '0936',
        'نهصد و سی و شش': '0936',
        'صفر نهصد و سی و پنج': '0935',
        'نهصد و سی و پنج': '0935',
        'صفر نهصد و سی و سه': '0933',
        'نهصد و سی و سه': '0933',
        'صفر نهصد و سی': '0930',
        'نهصد و سی': '0930',
        'صفر نهصد و بیست و دو': '0922',
        'نهصد و بیست و دو': '0922',
        'صفر نهصد و بیست و یک': '0921',
        'نهصد و بیست و یک': '0921',
        'صفر نهصد و بیست': '0920',
        'نهصد و بیست': '0920',
        'صفر نهصد و نود و یک': '0991',
        'نهصد و نود و یک': '0991',
        'صفر نهصد و نود': '0990',
        'نهصد و نود': '0990',
        'صفر نهصد': '09',
        'نهصد': '09'
    }

    HUNDREDS = {
        'یکصد': '1', 'صد': '1', 'دویست': '2', 'سیصد': '3', 'چهارصد': '4',
        'پانصد': '5', 'پونصد': '5', 'ششصد': '6', 'شیشصد': '6', 'هفتصد': '7', 'هشتصد': '8', 'نهصد': '9'
    }

    TENS = {
        'بیست': '20', 'سی': '30', 'چهل': '40', 'پنجاه': '50',
        'شصت': '60', 'هفتاد': '70', 'هشتاد': '80', 'نود': '90'
    }

    TEENS = {
        'ده': '10', 'یازده': '11', 'دوازده': '12', 'سیزده': '13', 'چهارده': '14',
        'پانزده': '15', 'پونزده': '15', 'شانزده': '16', 'شونزده': '16', 'هفده': '17', 'هجده': '18', 'نوزده': '19'
    }

    ONES = {
        'صفر': '0', 'یک': '1', 'دو': '2', 'سه': '3', 'چهار': '4',
        'پنج': '5', 'شش': '6', 'شیش': '6', 'هفت': '7', 'هشت': '8', 'نه': '9'
    }

    # پیش‌شماره‌های معتبر اپراتورهای موبایل ایران
    OPERATOR_PREFIXES = {
        'MCI': {
            '0910', '0911', '0912', '0913', '0914', '0915', '0916', '0917', '0918', '0919',
            '0990', '0991', '0992', '0993', '0994', '0995', '0996'
        },
        'MTN_Irancell': {
            '0930', '0933', '0935', '0936', '0937', '0938', '0939',
            '0901', '0902', '0903', '0904', '0905'
        },
        'Rightel': {
            '0920', '0921', '0922', '0923'
        },
        'Other_MVNO': {
            '0932', '0934', '0998', '0999'
        }
    }

    # الگوهای تلفن‌های ثابت (کدهای استانی متداول ایران)
    LANDLINE_PREFIXES = {
        '021': 'تهران', '026': 'البرز', '031': 'اصفهان', '051': 'خراسان رضوی',
        '071': 'فارس', '041': 'آذربایجان شرقی', '013': 'گیلان', '011': 'مازندران',
        '081': 'همدان', '086': 'مرکزی', '035': 'یزد', '034': 'کرمان', '061': 'خوزستان'
    }

    @classmethod
    def convert_persian_words_to_digits(cls, text: Optional[str]) -> str:
        """
        تبدیل پیشرفته و مقاوم اعداد حروفی فارسی به ارقام عددی
        پشتیبانی از پیش‌شماره‌های ترکیبی، اعداد صدگان، دهگان و یکان
        """
        if not text:
            return ""

        result = str(text)

        # ۱. تبدیل پیش‌شماره‌های ترکیبی
        for phrase, digits in cls.COMPOUND_PREFIXES.items():
            result = re.sub(rf'\b{re.escape(phrase)}\b', digits, result)
            result = result.replace(phrase, digits)

        # ۲. تبدیل اعداد ده‌تایی بعد از عدد (مثلا: "نهصد و سی و پنج" -> 0935)
        for teen, d in cls.TEENS.items():
            result = re.sub(rf'(?<=\d)\s*و\s*{re.escape(teen)}\b', d, result)
            result = re.sub(rf'\b{re.escape(teen)}\b', d, result)

        for ten, d in cls.TENS.items():
            result = re.sub(rf'(?<=\d)\s*و\s*{re.escape(ten)}\b', d, result)
            result = re.sub(rf'\b{re.escape(ten)}\b', d, result)

        for one, d in cls.ONES.items():
            result = re.sub(rf'(?<=\d)\s*و\s*{re.escape(one)}\b', d, result)
            result = re.sub(rf'\b{re.escape(one)}\b', d, result)
            result = result.replace(f" {one} ", f" {d} ")

        return result

    @classmethod
    def normalize_persian_digits(cls, text: Optional[str]) -> str:
        """استانداردسازی ارقام فارسی و عربی به ارقام انگلیسی"""
        if not text:
            return ""
        fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
        en_digits = '01234567890123456789'
        trans = str.maketrans(fa_digits, en_digits)
        return str(text).translate(trans)

    @classmethod
    def is_dummy_or_suspicious(cls, phone: str) -> bool:
        """
        تشخیص شماره‌های تستی، ساختگی، رند مصنوعی یا غیرواقعی
        مثال:
            09111111111 (همه ارقام یکسان)
            09123456789 (توالی افزایشی عددی)
            09127654321 (توالی معکوس تست)
            09000000000 (صفر مطلق)
            09120000000 (صفر یکنواخت در بدنه)
        """
        digits = re.sub(r'\D', '', str(phone))
        if len(digits) != 11:
            return True

        body = digits[4:]  # ۷ رقم آخر

        # الف) تمامی ارقام بدنه یکسان باشند (مثلا 09121111111 یا 09352222222)
        if len(set(body)) <= 1:
            return True

        # ب) ارقام تکراری یکنواخت کل شماره
        if len(set(digits[2:])) <= 1:
            return True

        # ج) شماره‌های شناخته‌شده تست و نمونه در اسناد یا توالی سراسری
        KNOWN_DUMMY = {
            '09123456789', '09127654321', '09120000000', '09999999999',
            '09000000000', '09876543210', '01234567890'
        }
        if digits in KNOWN_DUMMY:
            return True

        return False

    @classmethod
    def validate_and_normalize(cls, raw_phone: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        اعتبارسنجی دقیق و نرمال‌سازی شماره همراه یا ثابت ایران
        خروجی: دیکشنری شامل شماره نرمال‌شده (09xxxxxxxxx)، اپراتور و وضعیت سلامت
        """
        if not raw_phone:
            return None

        # تبدیل حروف فارسی به رقم و استانداردسازی
        normalized = cls.normalize_persian_digits(str(raw_phone))
        digits = re.sub(r'\D', '', normalized)

        # ۱. رسیدگی به شماره‌های بین‌المللی: +989... یا 00989... یا 989...
        if digits.startswith('00989') and len(digits) == 14:
            digits = '0' + digits[4:]
        elif digits.startswith('989') and len(digits) == 12:
            digits = '0' + digits[2:]
        elif digits.startswith('9') and len(digits) == 10:
            digits = '0' + digits

        # ارزیابی شماره موبایل ۱۱ رقمی استاندارد
        if len(digits) == 11 and digits.startswith('09'):
            prefix = digits[:4]
            operator = 'Unknown'
            for op_name, prefixes in cls.OPERATOR_PREFIXES.items():
                if prefix in prefixes:
                    operator = op_name
                    break

            is_suspicious = cls.is_dummy_or_suspicious(digits)

            return {
                'raw': raw_phone,
                'normalized': digits,
                'type': 'mobile',
                'operator': operator,
                'prefix': prefix,
                'is_valid': True,
                'is_suspicious': is_suspicious,
                'formatted': f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"
            }

        # ارزیابی شماره تلفن ثابت شهری ۱۱ رقمی (مثلاً 02188776655)
        if len(digits) == 11 and digits.startswith('0'):
            prefix3 = digits[:3]
            if prefix3 in cls.LANDLINE_PREFIXES:
                province = cls.LANDLINE_PREFIXES[prefix3]
                return {
                    'raw': raw_phone,
                    'normalized': digits,
                    'type': 'landline',
                    'operator': f'Telecommunication_{province}',
                    'prefix': prefix3,
                    'is_valid': True,
                    'is_suspicious': False,
                    'formatted': f"{digits[:3]}-{digits[3:]}"
                }

        # شماره ثابت ۸ رقمی بدون پیش‌شماره شهری (پیش‌فرض تهران ۰۲۱)
        if len(digits) == 8 and digits[0] in ('2', '3', '4', '5', '6', '7', '8'):
            full_landline = f"021{digits}"
            return {
                'raw': raw_phone,
                'normalized': full_landline,
                'type': 'landline',
                'operator': 'Telecommunication_تهران',
                'prefix': '021',
                'is_valid': True,
                'is_suspicious': False,
                'formatted': f"021-{digits}"
            }

        return None

    @classmethod
    def extract_primary_phone(
        cls,
        text: Optional[str],
        context: Optional[Dict[str, Any]] = None,
        filter_dummy: bool = True
    ) -> Optional[str]:
        """
        استخراج مهم‌ترین و قطعی‌ترین شماره موبایل مالک از متن یا بافت ورودی
        دارای اولویت‌بندی: موبایل معتبر شخصی > شماره ثابت
        """
        if not text and not context:
            return None

        # الف) در صورت وجود ساختار بافت/دیکشنری (context)
        if context and isinstance(context, dict):
            phone_from_ctx = cls.extract_from_json_recursive(context)
            if phone_from_ctx:
                return phone_from_ctx

        if not text:
            return None

        # ب) استانداردسازی ارقام و دیکود کردن کلمات حروفی فارسی
        norm = cls.normalize_persian_digits(str(text))
        norm = cls.convert_persian_words_to_digits(norm)

        # ۱. الگوهای ارقام با فاصله عمدی: 0 9 1 2 3 4 5 6 7 8 9
        spaced_match = re.search(r'(?:^|[^\d])(0\s*9(?:\s*\d){9})(?:[^\d]|$)', norm)
        if spaced_match:
            cand = re.sub(r'\D', '', spaced_match.group(1))
            val = cls.validate_and_normalize(cand)
            if val and val['is_valid'] and (not filter_dummy or not val['is_suspicious']):
                return val['normalized']

        # ۲. پیش‌شماره‌های بین‌المللی: +989... یا 00989... یا 989...
        int_match = re.search(r'(?:\+98|0098|98)(9\d{9})\b', norm)
        if int_match:
            cand = '0' + int_match.group(1)
            val = cls.validate_and_normalize(cand)
            if val and val['is_valid'] and (not filter_dummy or not val['is_suspicious']):
                return val['normalized']

        # ۳. شماره‌های دارای نمادهای جداکننده مختلف (خط تیره، نقطه، اسلش، ستاره، پرانتز)
        sep_match = re.search(r'(?:^|[^\d])(0?9[\d\s\-\.\/\_\*\(\)]{9,18}\d)(?:[^\d]|$)', norm)
        if sep_match:
            cleaned = re.sub(r'\D', '', sep_match.group(1))
            val = cls.validate_and_normalize(cleaned)
            if val and val['is_valid'] and (not filter_dummy or not val['is_suspicious']):
                return val['normalized']

        # ۴. شماره‌های ساده ۱۱ رقمی 09xxxxxxxxx
        ten_eleven = re.findall(r'(?<!\d)(?:09\d{9}|9\d{9})(?!\d)', norm)
        for cand in ten_eleven:
            val = cls.validate_and_normalize(cand)
            if val and val['is_valid'] and (not filter_dummy or not val['is_suspicious']):
                return val['normalized']

        # ۵. در صورت نبود موبایل سالم، بررسی تلفن ثابت با پیش‌شماره شهری
        landline_match = re.search(r'(?<!\d)(02[1-9]\d{8})(?!\d)', norm)
        if landline_match:
            val = cls.validate_and_normalize(landline_match.group(1))
            if val and val['is_valid'] and (not filter_dummy or not val['is_suspicious']):
                return val['normalized']
            if val and val['is_valid']:
                return val['normalized']

        return None

    @classmethod
    def extract_all_phones(cls, text: Optional[str]) -> List[str]:
        """استخراج تمامی شماره‌های معتبر و منحصربه‌فرد (موبایل و ثابت) از متن"""
        if not text:
            return []

        norm = cls.normalize_persian_digits(str(text))
        norm = cls.convert_persian_words_to_digits(norm)

        found_phones: List[str] = []
        seen: Set[str] = set()

        # جستجوی تمام تطابق‌های موبایل و بین‌المللی
        patterns = [
            r'(?:(?:\+98|0098|98)\s*9\d{9})',
            r'(?:0\s*9(?:\s*[\d\-\.\_\*\/\(\)]){8,18}\d)',
            r'(?<!\d)(?:09\d{9})(?!\d)',
            r'(?<!\d)(?:9\d{9})(?!\d)',
            r'(?<!\d)(?:02[1-9]\d{8})(?!\d)'
        ]

        for pat in patterns:
            for m in re.finditer(pat, norm):
                raw = m.group(0)
                val = cls.validate_and_normalize(raw)
                if val and val['is_valid'] and not val['is_suspicious']:
                    num = val['normalized']
                    if num not in seen:
                        seen.add(num)
                        found_phones.append(num)

        return found_phones

    @classmethod
    def extract_from_json_recursive(cls, data: Any) -> Optional[str]:
        """
        جستجوی بازگشتی عمیق در ساختارهای تودرتوی JSON و ویجت‌های دیوار و شیپور
        یافتن اولین شماره تماس واقعی معتبر
        """
        if isinstance(data, dict):
            # ۱. بررسی اولویت‌دار کلیدهای رایج شماره تماس
            for key in ['phone_number', 'phone', 'mobile', 'call_number', 'contact_number']:
                if key in data and data[key]:
                    val = str(data[key])
                    norm_val = cls.validate_and_normalize(val)
                    if norm_val and norm_val['is_valid'] and not norm_val['is_suspicious']:
                        return norm_val['normalized']

            # ۲. بررسی ویجت‌های اکشن تماس دیوار (Action Payload)
            action = data.get('action', {})
            payload = action.get('payload', {}) if isinstance(action, dict) else {}
            if isinstance(payload, dict):
                for key in ['phone_number', 'phone', 'mobile']:
                    if key in payload and payload[key]:
                        norm_val = cls.validate_and_normalize(str(payload[key]))
                        if norm_val and norm_val['is_valid'] and not norm_val['is_suspicious']:
                            return norm_val['normalized']

            # ۳. جستجوی بازگشتی در سایر مقادیر دیکشنری
            for v in data.values():
                res = cls.extract_from_json_recursive(v)
                if res:
                    return res

        elif isinstance(data, list):
            for item in data:
                res = cls.extract_from_json_recursive(item)
                if res:
                    return res

        elif isinstance(data, str):
            # بررسی متن رشته‌ای
            if '09' in data or '9' in data:
                return cls.extract_primary_phone(data)

        return None
