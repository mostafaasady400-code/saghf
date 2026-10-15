"""
High-Speed Text-Mining Contact Extractor for Saghf Platform.
Extracts Iranian mobile phone numbers from Persian descriptions, titles,
spelled-out numbers, obfuscated digits, and repetitive phrases.
Zero API Quota Consumed. Zero Mock.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from crawler.contact_extractor import ContactExtractor


class TextPhoneMiner:
    """
    موتور استخراج فوق‌سریع شماره تلفن از متون فارسی و نشانه‌گذاری‌های مبهم.
    ویژگی‌ها:
    - تشخیص ارقام فارسی، عربی و انگلیسی
    - تشخیص صفر نوشته‌شده با حروف انگلیسی O / o در پیش‌شماره (o912 / O912)
    - تبدیل عبارات تکرار مانند «سه تا ۵» به «۵۵۵» یا «دو تا ۲» به «۲۲»
    - تبدیل کامل اعداد حروفی فارسی به ارقام
    - پالایش دقیق و استانداردسازی به فرمت 09xxxxxxxxx
    - صفر مصرف سهمیه API دیوار (کاملاً درون‌برنامه‌ای و در کسری از میلی‌ثانیه)
    """

    # الگوهای تکرار کلامی (مانند "سه تا پنج" -> 555)
    REPEAT_WORDS = {
        'یک': '1', 'دو': '2', 'سه': '3', 'چهار': '4',
        'پنج': '5', 'شش': '6', 'شیش': '6', 'هفت': '7', 'هشت': '8', 'نه': '9', 'صفر': '0'
    }
    COUNT_WORDS = {
        'دو': 2, 'سه': 3, 'چهار': 4, 'پنج': 5,
        '۲': 2, '۳': 3, '۴': 4, '۵': 5,
        '2': 2, '3': 3, '4': 4, '5': 5
    }

    @classmethod
    def expand_repeat_phrases(cls, text: str) -> str:
        """تبدیل عباراتی نظیر 'سه تا ۵' یا '۲ تا هشت' به ارقام متوالی"""
        if not text:
            return ""

        result = text
        # الگوی: [تعداد] تا [رقم یا کلمه رقم]
        # مثال: "سه تا ۵" یا "دو تا هفت"
        pattern = re.compile(
            r'(\b(?:دو|سه|چهار|پنج|[۲-۵]|[2-5]))\s*تا\s*(\b(?:صفر|یک|دو|سه|چهار|پنج|شش|شیش|هفت|هشت|نه|[۰-۹]|[0-9]))',
            re.IGNORECASE
        )

        def replacer(m):
            count_str = m.group(1).strip()
            digit_str = m.group(2).strip()

            count = cls.COUNT_WORDS.get(count_str, 1)
            target_digit = cls.REPEAT_WORDS.get(digit_str, digit_str)
            target_digit = ContactExtractor.normalize_persian_digits(target_digit)
            return target_digit * count

        return pattern.sub(replacer, result)

    @classmethod
    def clean_obfuscation(cls, text: str) -> str:
        """حذف نشانه‌های استتار و تبدیل حروف شبه‌رقم"""
        if not text:
            return ""

        # استانداردسازی حروف عربی به فارسی
        t = text.replace('ي', 'ی').replace('ك', 'ک')

        # جایگزینی حرف انگلیسی o یا O در ابتدای کلمات شبیه به شماره (o912 -> 0912)
        t = re.sub(r'\b[oO](9\d{2})', r'0\1', t)
        t = re.sub(r'\b[oO]\s*(9\d{2})', r'0\1', t)

        # بسط عبارات تکراری (سه تا پنج -> 555)
        t = cls.expand_repeat_phrases(t)

        # تبدیل اعداد حروفی فارسی به ارقام
        t = ContactExtractor.normalize_persian_digits(t)
        t = ContactExtractor.convert_persian_words_to_digits(t)

        return t

    @classmethod
    def mine_phone(
        cls,
        text: Optional[str],
        additional_text: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        استخراج شماره موبایل واقعی از متن اصلی (توضیحات) یا متن جانبی (عنوان).
        خروجی: دیکشنری شامل شماره نرمال‌شده و جزئیات اعتبارسنجی یا None.
        """
        combined = f"{text or ''} {additional_text or ''}".strip()
        if not combined:
            return None

        cleaned = cls.clean_obfuscation(combined)

        # استخراج با ContactExtractor
        extracted = ContactExtractor.extract_primary_phone(cleaned, filter_dummy=True)
        if extracted:
            val = ContactExtractor.validate_and_normalize(extracted)
            if val and val.get('is_valid') and not val.get('is_suspicious') and val.get('type') == 'mobile':
                return {
                    'phone': val['normalized'],
                    'operator': val.get('operator'),
                    'source': 'text_miner',
                    'confidence': 95,
                    'is_valid': True
                }

        # بررسی الگوهای چسبیده به حروف مانند تماس:09123456789
        tight_match = re.search(r'(?:09|\+989|989)(?:\d[\s\-\.\_\*]*){9}', cleaned)
        if tight_match:
            digits = re.sub(r'\D', '', tight_match.group(0))
            if digits.startswith('989'):
                digits = '0' + digits[2:]
            val = ContactExtractor.validate_and_normalize(digits)
            if val and val.get('is_valid') and not val.get('is_suspicious') and val.get('type') == 'mobile':
                return {
                    'phone': val['normalized'],
                    'operator': val.get('operator'),
                    'source': 'text_miner_tight',
                    'confidence': 90,
                    'is_valid': True
                }

        return None

    @classmethod
    def mine_all_phones(cls, text: Optional[str]) -> List[str]:
        """استخراج تمام شماره‌های معتبر یکتا از متن"""
        if not text:
            return []
        cleaned = cls.clean_obfuscation(text)
        all_found = ContactExtractor.extract_all_phones(cleaned)
        valid_phones: List[str] = []
        for p in all_found:
            val = ContactExtractor.validate_and_normalize(p)
            if val and val.get('is_valid') and not val.get('is_suspicious'):
                if val['normalized'] not in valid_phones:
                    valid_phones.append(val['normalized'])
        return valid_phones
