import re
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import dataclass, field

# جدول استانداردسازی حروف فارسی و عربی
ARABIC_TO_PERSIAN = str.maketrans({
    'ي': 'ی',
    'ك': 'ک',
    'ة': 'ه',
    'ۀ': 'ه',
    'ؤ': 'و',
    'إ': 'ا',
    'أ': 'ا',
    'ء': '',
    '\u200c': ' ',  # نیم‌فاصله به فاصله جهت یکپارچگی تطابق رگکس
    '\u00a0': ' ',
})

def clean_persian_text(text: Optional[str]) -> str:
    """استانداردسازی متن، یکپارچه‌سازی حروف و حذف فاصله‌های اضافه"""
    if not text:
        return ""
    normalized = str(text).translate(ARABIC_TO_PERSIAN).lower()
    return re.sub(r'\s+', ' ', normalized).strip()

@dataclass
class FilterResult:
    is_personal: bool
    status: str  # 'approved_personal', 'rejected_account_type', 'rejected_forbidden_words'
    reason: str
    detected_terms: List[str] = field(default_factory=list)
    owner_type: str = "personal"

class OwnerFilter:
    """
    فیلتر هوشمند دومرحله‌ای مطابق دستور دقیق و اولویت‌بندی شده:
    
    مرحله ۱ (بررسی نوع آگهی‌دهنده):
        بررسی نوع حساب کاربری در متادیتا و مشخصات سیستمی.
        اگر آگهی از پنل املاک، آژانس، حساب تجاری یا هر حسابی غیر از کاربر شخصی باشد،
        همان ابتدا حذف و فیلتر می‌شود.
        
    مرحله ۲ (بررسی عنوان و متن آگهی شخصی):
        اگر آگهی‌دهنده شخصی بود، عنوان و متن توضیحات بررسی شده و در صورت وجود کلماتی مثل:
        (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار و...)، آگهی بلافاصله فیلتر شده
        و در دیتابیس ثبت نمی‌گردد.
    """

    # --- مرحله اول: نشانه‌های پنل املاک، آژانس، دپارتمان یا حساب‌های تجاری ---
    NON_PERSONAL_ACCOUNT_TERMS = [
        'آژانس', 'املاک', 'املاك', 'دپارتمان', 'مشاور', 'مشاورین', 'مشاوران',
        'هلدینگ', 'مسکن', 'مسكن', 'کارگزاری', 'گروه ساختمانی', 'دفتر فروش',
        'کاسپین', 'پازل', 'شایگان', 'مهرایران', 'بالون', 'افرا', 'کلید',
        'مهندسین', 'گروه مشاورین', 'آژانس مسکن', 'آژانس املاک', 'بنگاه'
    ]

    # --- مرحله دوم: کلمات ممنوعه در عنوان و توضیحات آگهی‌های شخصی ---
    # طبق دستور کاربر: (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار و...)
    FORBIDDEN_WORDS = [
        # واژگان صریح خواسته شده:
        'املاک', 'املاکی', 'املاك',
        'مسکن', 'مسكن',
        'خانه',
        'مشاور', 'مشاوران', 'مشاورین', 'مشاوره',
        'کارشناس', 'کارشناسان', 'کارشناسی',
        'کمیسیون', 'کمسیون',
        'همکار', 'همکاران',

        # اصطلاحات تکمیلی دفاتر و بازاریابی املاک:
        'دپارتمان',
        'آژانس',
        'بنگاه',
        'مهندسین',
        'حق الزحمه',
        'شیرینی مشاور',
        'موارد مشابه',
        'فایل های مشابه',
        'فایلهای مشابه',
        'فایلینگ',
        'اتاق قرارداد',
        'کلید نزد املاک',
        'کلید در اختیار دفتر',
        'کلید در اختیار املاک'
    ]

    # الگوهای ترکیبی مشاوران در متن
    EXTRA_TEXT_PATTERNS = [
        (r'مهندس\s+[آ-ی]{3,}', 'مهندس/کارشناس دپارتمانی'),
        (r'پاسخگویی\s+تا\s+(?:۲۴|۱۲\s+شب|۲\s+بامداد|ساعت\s+۱۲|۲۴\s*ساعته)', 'پاسخگویی ۲۴ ساعته مشاور'),
        (r'تماس\s+تا\s+(?:۱۲\s+شب|ساعت\s+۱۲|۲۴)', 'تماس تا ۱۲ شب مشاور'),
        (r'بازدید\s+(?:فقط\s+)?با\s+هماهنگی\s+(?:دفتر|املاک|مشاور)', 'بازدید با هماهنگی دفتر'),
        (r'تیم\s+(?:فروش|تخصصی|معاملاتی)', 'تیم معاملات دپارتمان')
    ]

    @classmethod
    def evaluate(cls, 
                  platform: str, 
                  title: str, 
                  description: str = "", 
                  widget_data: Optional[Dict[str, Any]] = None,
                  raw_text: str = "") -> FilterResult:
        """
        ارزیابی دومرحله‌ای دقیق به ترتیب درخواست:
        ۱. اول نوع آگهی‌دهنده را بررسی کن؛ اگر غیر شخصی، آژانس یا پنل املاک بود فوراً رد کن.
        ۲. اگر شخصی بود، عنوان و متن را بررسی کن و در صورت وجود کلمات فیلتر، رد کن.
        """
        widget_data = widget_data or {}

        # =========================================================================
        # مرحله اول: بررسی نوع آگهی‌دهنده (Account / Advertiser Type Check)
        # =========================================================================
        account_is_personal, account_reason, detected_account_terms = cls._check_advertiser_account_type(
            platform=platform,
            widget_data=widget_data,
            raw_text=raw_text
        )

        if not account_is_personal:
            # اگر آگهی از پنل املاک، آژانس یا هر حسابی غیر از کاربر شخصی بود، همون اول حذف شود
            return FilterResult(
                is_personal=False,
                status='rejected_account_type',
                reason=account_reason,
                detected_terms=detected_account_terms,
                owner_type='agency'
            )

        # =========================================================================
        # مرحله دوم: بررسی عنوان و متن آگهی شخصی (Title & Description Content Check)
        # =========================================================================
        text_is_clean, text_reason, detected_text_terms = cls._check_forbidden_words_in_content(
            title=title,
            description=f"{description} {raw_text}".strip()
        )

        if not text_is_clean:
            # وجود کلمات فیلتر (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار و...) در عنوان یا متن
            return FilterResult(
                is_personal=False,
                status='rejected_forbidden_words',
                reason=text_reason,
                detected_terms=detected_text_terms,
                owner_type='agency'
            )

        # =========================================================================
        # تأیید نهایی: آگهی‌دهنده شخصی + بدون کلمات املاکی در عنوان و متن
        # =========================================================================
        return FilterResult(
            is_personal=True,
            status='approved_personal',
            reason="تأییدشده: حساب کاربری شخصی و فاقد کلمات فیلتر در عنوان و متن",
            detected_terms=[],
            owner_type='personal'
        )

    @classmethod
    def _check_advertiser_account_type(cls, platform: str, widget_data: Dict[str, Any], raw_text: str) -> Tuple[bool, str, List[str]]:
        """
        مرحله اول: چک کردن نوع آگهی‌دهنده
        بررسی این که آیا حساب متعلق به پنل املاک، آژانس، حساب تجاری یا هر حسابی غیر از کاربر شخصی است یا خیر.
        خروجی: (is_personal, reason, detected_terms)
        """
        detected: List[str] = []

        if platform == 'divar':
            # ۱. بررسی لاگ سرور دیوار برای نوع اکانت (is_business / agency_id / business_type)
            server_info = widget_data.get('action_log', {}).get('server_side_info', {}).get('info', {})
            if isinstance(server_info, dict):
                if server_info.get('is_business') is True:
                    detected.append("divar:is_business=True")
                if server_info.get('agency_id') or server_info.get('business_id'):
                    detected.append("divar:has_agency_id")
                b_type = str(server_info.get('business_type', '')).lower()
                if b_type and b_type not in ['personal', 'none', '']:
                    detected.append(f"divar:business_type={b_type}")

            # ۲. بررسی تگ‌های پنل/آژانس (image_top_left_tag / red_text)
            tag_obj = widget_data.get('image_top_left_tag') or widget_data.get('red_text') or ''
            if isinstance(tag_obj, dict):
                tag_text = clean_persian_text(tag_obj.get('text', ''))
                if any(t in tag_text for t in ['آژانس', 'املاک', 'مشاور', 'تجاری']):
                    detected.append(f"tag:{tag_text}")
            elif isinstance(tag_obj, str) and any(t in clean_persian_text(tag_obj) for t in ['آژانس', 'املاک', 'تجاری']):
                detected.append(f"tag:{tag_obj}")

            # ۳. در دیوار، نام آژانس و دفتر املاک در bottom_description_text یا top_description_text درج می‌شود
            # برای کاربران شخصی، همواره زمان ثبت (مانند «دقایقی پیش در ...») درج می‌شود نه نام آژانس
            bottom_desc = clean_persian_text(widget_data.get('bottom_description_text', ''))
            top_desc = clean_persian_text(widget_data.get('top_description_text', ''))
            meta_combined = f"{bottom_desc} {top_desc}"

            for term in cls.NON_PERSONAL_ACCOUNT_TERMS:
                if term in meta_combined:
                    detected.append(f"account_name_has:{term}")

        elif platform == 'sheypoor':
            cleaned_raw = clean_persian_text(raw_text)
            # شیپور: برچسب Ad یا تابلو شده یا نام آژانس نشان‌دهنده حساب تجاری/دفتر است
            if 'ad تابلو شده' in cleaned_raw or 'تابلو شده' in cleaned_raw or 'ad' in raw_text.split():
                detected.append("sheypoor:sponsored_ad_account")

            for term in ['آژانس', 'املاک', 'دپارتمان', 'مشاورین', 'مسکن', 'فروشگاه']:
                if term in cleaned_raw:
                    detected.append(f"sheypoor_meta:{term}")

        if detected:
            return (False, "حساب کاربری غیرشخصی است (پنل املاک / آژانس / حساب تجاری)", detected)

        return (True, "حساب کاربری شخصی تأیید شد", [])

    @classmethod
    def _check_forbidden_words_in_content(cls, title: str, description: str) -> Tuple[bool, str, List[str]]:
        """
        مرحله دوم: بررسی دقیق عنوان و متن آگهی در صورت شخصی بودن حساب
        جستجوی کلماتی مثل (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار و...)
        با حریم کلمات جهت پیشگیری از خطای مثبت کاذب (مانند کارخانه).
        خروجی: (is_clean, reason, detected_terms)
        """
        combined = clean_persian_text(f"{title} {description}")
        detected: List[str] = []

        # عبارات طبیعی مالکین برای کلمه «خانه» (مانند صاحب‌خانه، آشپزخانه، این خانه، تخلیه خانه و ...)
        # تا از رد شدن مالکین شخصی واقعی جلوگیری شود
        SAFE_KHANEH_PHRASES = [
            'صاحب خانه', 'صاحبخانه', 'آشپز خانه', 'آشپزخانه', 'هم خانه', 'همخانه',
            'این خانه', 'خانه دربست', 'خانه ویلایی', 'خانه مسکونی', 'خانه تمیز',
            'تحویل خانه', 'تخلیه خانه', 'کل این خانه', 'داخل خانه', 'فضای خانه', 'پشت قباله خانه'
        ]
        text_to_check = combined
        for safe_p in SAFE_KHANEH_PHRASES:
            text_to_check = text_to_check.replace(safe_p, '___SAFE___')

        # ۱. بررسی کلمات ممنوعه با حریم کلمه (Word Boundary برای زبان فارسی)
        for word in cls.FORBIDDEN_WORDS:
            # الگوی تطابق کلمه مستقل: قبل و بعد آن نباید کاراکتر فارسی یا انگلیسی باشد
            pattern = rf'(?<![آ-یa-zA-Z0-9_]){re.escape(word)}(?![\u200cآ-یa-zA-Z0-9_])'
            match = re.search(pattern, text_to_check)
            if match:
                detected.append(match.group(0))

        # ۲. بررسی الگوهای ترکیبی مشاوران
        for pattern, label in cls.EXTRA_TEXT_PATTERNS:
            match = re.search(pattern, combined)
            if match:
                detected.append(f"{label} ('{match.group(0)}')")

        if detected:
            terms_str = "، ".join(detected)
            return (False, f"وجود کلمات فیلتر در عنوان یا متن آگهی: [{terms_str}]", detected)

        return (True, "عنوان و متن فاقد هرگونه کلمات فیلتر است", [])

def convert_persian_words_to_digits(text: str) -> str:
    """تبدیل اعداد حروفی فارسی به ارقام جهت استخراج شماره‌های نوشته‌شده به حروف"""
    if not text:
        return ""
    
    # الگوهای پیش‌شماره‌های مرکب
    PREFIX_WORDS = {
        'نهصد و دوازده': '0912',
        'نهصد و نوزده': '0919',
        'نهصد و هجده': '0918',
        'نهصد و هفده': '0917',
        'نهصد و شانزده': '0916',
        'نهصد و پانزده': '0915',
        'نهصد و چهارده': '0914',
        'نهصد و سیزده': '0913',
        'نهصد و ده': '0910',
        'نهصد و سی و نه': '0939',
        'نهصد و سی و هشت': '0938',
        'نهصد و سی و هفت': '0937',
        'نهصد و سی و شش': '0936',
        'نهصد و سی و پنج': '0935',
        'نهصد و سی و سه': '0933',
        'نهصد و سی': '0930',
        'نهصد و بیست و یک': '0921',
        'نهصد و بیست و دو': '0922',
        'نهصد و بیست': '0920',
        'نهصد و نود و یک': '0991',
        'نهصد و نود': '0990',
        'صفر نهصد': '09',
        'نهصد': '09'
    }

    # ارقام تکی و ترکیبی
    SINGLE_WORDS = {
        'صفر': '0', 'یک': '1', 'دو': '2', 'سه': '3', 'چهار': '4',
        'پنج': '5', 'شش': '6', 'شیش': '6', 'هفت': '7', 'هشت': '8', 'نه': '9',
        'یازده': '11', 'دوازده': '12', 'سیزده': '13', 'چهارده': '14',
        'پانزده': '15', 'شانزده': '16', 'هفده': '17', 'هجده': '18', 'نوزده': '19',
        'بیست': '20', 'سی': '30', 'چهل': '40', 'پنجاه': '50',
        'شصت': '60', 'هفتاد': '70', 'هشتاد': '80', 'نود': '90'
    }

    result = text
    for word_phrase, digit_val in PREFIX_WORDS.items():
        result = re.sub(rf'\b{re.escape(word_phrase)}\b', digit_val, result)
        result = result.replace(word_phrase, digit_val)

    for word, digit in SINGLE_WORDS.items():
        result = re.sub(rf'(?<=\d)\s*و\s*{re.escape(word)}\b', digit, result)
        result = re.sub(rf'\b{re.escape(word)}\b', digit, result)
        result = result.replace(word, digit)

    return result

def extract_phone_number(text: Optional[str]) -> Optional[str]:
    """
    استخراج شماره موبایل واقعی (ایران: 09xxxxxxxxx) از متن آگهی یا توضیحات
    با پشتیبانی کامل از:
    ۱. ارقام حروفی فارسی (مانند نهصد و دوازده...)
    ۲. ارقام فارسی/عربی و انگلیسی
    ۳. ارقام فاصله‌دار (0 9 1 2 ...)
    ۴. کاراکترهای جداکننده مختلف (خط تیره، اسلش، نقطه، ستاره و...)
    ۵. پیش‌شماره‌های بین‌المللی (+989..., 00989..., 989...)
    """
    if not text:
        return None

    # استانداردسازی کاراکترهای فارسی و عربی
    fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
    en_digits = '01234567890123456789'
    trans = str.maketrans(fa_digits, en_digits)
    norm = str(text).translate(trans)

    # تبدیل اعداد حروفی به رقم
    norm = convert_persian_words_to_digits(norm)

    # ۱. شماره‌هایی که تک‌تک ارقام آنها با فاصله جدا شده‌اند جهت دور زدن فیلتر: 0 9 1 2 3 4 5 6 7 8 9
    spaced_match = re.search(r'(?:^|[^\d])(0\s*9(?:\s*\d){9})(?:[^\d]|$)', norm)
    if spaced_match:
        digits = re.sub(r'\D', '', spaced_match.group(1))
        if len(digits) == 11 and digits.startswith('09'):
            return digits

    # ۲. پیش‌شماره‌های بین‌المللی: +989... یا 00989... یا 989...
    int_match = re.search(r'(?:\+98|0098|98)(9\d{9})\b', norm)
    if int_match:
        return '0' + int_match.group(1)

    # ۳. شماره‌های استاندارد با کاراکترهای جداکننده مختلف (فاصله، خط تیره، اسلش، نقطه، ستاره، خط زیر)
    sep_match = re.search(r'(?:^|[^\d])(0?9[\d\s\-\.\/\_\*]{9,16}\d)(?:[^\d]|$)', norm)
    if sep_match:
        cleaned = re.sub(r'\D', '', sep_match.group(1))
        if len(cleaned) == 10 and cleaned.startswith('9'):
            return '0' + cleaned
        elif len(cleaned) == 11 and cleaned.startswith('09'):
            return cleaned

    # ۴. شماره‌های ۱۰ رقمی بدون صفر اول: 9121234567
    ten_digit = re.search(r'(?:^|[^\d])(9\d{9})(?:[^\d]|$)', norm)
    if ten_digit:
        return '0' + ten_digit.group(1)

    return None

