import re
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import dataclass, field

# جدول استانداردسازی حروف فارسی و عربی، حذف کشیدگی و نویسه‌های کنترلی یونیکد
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
    '\u200b': '',   # zero-width space
    '\u200d': '',   # zero-width joiner
    '\u2060': '',   # word joiner
    '\u0640': '',   # کشیدگی حروف (تطویل یا کَشیده - مانند اـمـلـاـک)
    '\u00a0': ' ',  # non-breaking space
    '\ufeff': '',   # byte order mark
})

def clean_persian_text(text: Optional[str]) -> str:
    """استانداردسازی متن، یکپارچه‌سازی حروف، حذف تطویل و نویسه‌های مخفی یونیکد"""
    if not text:
        return ""
    normalized = str(text).translate(ARABIC_TO_PERSIAN).lower()
    normalized = re.sub(r'[\u200b-\u200f\u0640\ufeff]', '', normalized)
    return re.sub(r'\s+', ' ', normalized).strip()

@dataclass
class FilterResult:
    is_personal: bool
    status: str  # 'approved_personal', 'rejected_account_type', 'rejected_forbidden_words'
    reason: str
    detected_terms: List[str] = field(default_factory=list)
    owner_type: str = "personal"
    confidence_score: int = 85
    risk_level: str = "low"
    metadata: Dict[str, Any] = field(default_factory=dict)

class OwnerFilter:
    """
    فیلتر هوشمند دومرحله‌ای مجهز به ممیزی حریم خصوصی، خنثی‌سازی تکنیک‌های گریز و نمره‌دهی اعتبار:
    
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
    # --- مرحله اول: نشانه‌های قطعی پنل املاک، آژانس، دپارتمان یا برندهای شناخته‌شده مشاورین ---
    NON_PERSONAL_ACCOUNT_TERMS = [
        'آژانس', 'املاک', 'املاك', 'دپارتمان', 'مشاور', 'مشاورین', 'مشاوران', 'مشاوره',
        'مشاوره املاک', 'مشاور املاک', 'املاک آرتا', 'آژانس مسکن', 'آژانس املاک', 'بنگاه',
        'هلدینگ مسکن', 'هلدینگ املاک', 'کارگزاری مسکن', 'کارگزاری املاک', 'گروه ساختمانی',
        'دفتر فروش', 'دفتر املاک', 'دفتر معاملات', 'دپارتمان بزرگ', 'کانون املاک',
        'املاک دلتا', 'املاک کیا', 'املاک بارمان', 'املاک رویال', 'املاک سفیر', 'املاک آراز',
        'املاک شایگان', 'املاک پازل', 'املاک کاسپین', 'املاک بالون', 'املاک افرا', 'املاک دیار',
        'مهندسین و مشاورین', 'گروه مهندسین', 'گروه مشاورین'
    ]

    # --- مرحله دوم: کلمات ممنوعه مشاوران در عنوان و توضیحات ---
    # حذف قطعی هرگونه اصطلاحات مشاوره‌ای، بازاریابی دپارتمانی و کمیسیونی
    FORBIDDEN_WORDS = [
        'املاک', 'املاکی', 'املاك', 'املاک آرتا',
        'مشاور', 'مشاوران', 'مشاورین', 'مشاوره املاک', 'مشاور املاک', 'مشاور شما', 'مشاور فروش', 'مشاور منطقه',
        'امین شما', 'امین ملکی', 'امین منطقه',
        'کارشناس', 'کارشناسان', 'کارشناسی', 'کارشناس فروش', 'کارشناس منطقه', 'کارشناس امور ملکی', 'کارشناس تخصصی',
        'کمیسیون', 'کمسیون', 'حق کمیسیون', 'حق الزحمه مشاور', 'شیرینی مشاور',
        'همکار', 'همکاران', 'همکاران محترم', 'همکار گرامی', 'همکاران املاک',
        'دپارتمان', 'دپارتمان املاک', 'کانون املاک', 'آژانس مسکن', 'آژانس املاک', 'بنگاه املاک',
        'موارد مشابه', 'فایل های مشابه', 'فایلهای مشابه', 'واحدهای مشابه', 'فایلینگ', 'فایل شخصی مشاور', 'فایل انحصاری',
        'اتاق قرارداد',
        'کلید نزد املاک', 'کلید در اختیار دفتر', 'کلید در اختیار املاک', 'کلید در دفتر', 'کلید نزد دفتر',
        'پاسخگویی ۲۴ ساعته', 'تماس تا ۱۲ شب', 'تماس تا ۲۴', 'پاسخگویی تا ۲۴',
        'بازدید با هماهنگی دفتر', 'بازدید با هماهنگی املاک'
    ]

    # کلیدواژه‌های منفی اسکان اشتراکی، همخونه، هم‌اتاقی و اجاره اتاق (ممنوعیت قطعی)
    SHARED_HOUSING_NEGATIVE_KEYWORDS = [
        'همخونه', 'همخانه', 'هم‌خونه', 'هم‌خانه', 'هم خانه', 'هم خونه',
        'هم اتاقی', 'هماتاقی', 'هم‌اتاقی', 'هم اتاق',
        'اجاره اتاق', 'کرایه اتاق', 'پذیرش همخونه', 'پذیرش همخانه', 'نیازمند همخونه',
        'نیازمند همخانه', 'نیاز به همخانه', 'نیاز به همخونه', 'نیازمند هم اتاقی',
        'خوابگاه', 'پانسیون', 'اسکان اشتراکی', 'اتاق اشتراکی', 'همزیستی', 'هم منزل',
        'هم‌منزل', 'سوئیت اشتراکی'
    ]

    # الگوهای ترکیبی مشاوران در متن
    EXTRA_TEXT_PATTERNS = [
        (r'مهندس\s+[آ-ی]{3,}', 'مهندس/کارشناس دپارتمانی'),
        (r'پاسخگویی\s+تا\s+(?:۲۴|۱۲\s+شب|۲\s+بامداد|ساعت\s+۱۲|۲۴\s*ساعته)', 'پاسخگویی ۲۴ ساعته مشاور'),
        (r'تماس\s+تا\s+(?:۱۲\s+شب|ساعت\s+۱۲|۲۴)', 'تماس تا ۱۲ شب مشاور'),
        (r'بازدید\s+(?:فقط\s+)?با\s+هماهنگی\s+(?:دفتر|املاک|مشاور)', 'بازدید با هماهنگی دفتر'),
        (r'تیم\s+(?:فروش|تخصصی|معاملاتی)', 'تیم معاملات دپارتمان'),
        (r'املاک\s+[آ-ی]{3,}', 'عنوان یا برند املاک'),
        (r'مشاور\s+[آ-ی]{3,}', 'مشاور املاک فردی'),
        (r'مدیر\s+(?:قرارداد|فروش|معاملات)', 'مدیر قرارداد دپارتمان'),
        (r'اتاق\s+قرارداد', 'اتاق قرارداد آژانس'),
        (r'فایل\s+(?:انحصاری|شخصی\s+دفتر|تخصصی)', 'فایلینگ دپارتمانی'),
        (r'تک\s*بازدید', 'اصطلاح بازاریابی تک بازدید')
    ]

    @classmethod
    def evaluate(cls, 
                  platform: str, 
                  title: str, 
                  description: str = "", 
                  widget_data: Optional[Dict[str, Any]] = None,
                  raw_text: str = "") -> FilterResult:
        """
        ارزیابی دومرحله‌ای دقیق به همراه فیلتر سخت‌گیرانه اسکان اشتراکی:
        ۰. بررسی کلیدواژه‌های منفی همخونه/اجاره اتاق (رد فوری)
        ۱. بررسی نوع آگهی‌دهنده (حساب شخصی در برابر پنل املاک)
        ۲. بررسی متن و عنوان برای حذف قطعی اصطلاحات املاکی و بازاریابی
        """
        widget_data = widget_data or {}

        # =========================================================================
        # مرحله صفر: فیلتر سخت‌گیرانه حذف قطعی هرگونه آگهی همخونه و اسکان اشتراکی
        # =========================================================================
        combined_text_norm = clean_persian_text(f"{title} {description} {raw_text}")
        combined_no_space = combined_text_norm.replace(' ', '')
        for term in cls.SHARED_HOUSING_NEGATIVE_KEYWORDS:
            clean_term = clean_persian_text(term)
            term_no_space = clean_term.replace(' ', '')
            if clean_term in combined_text_norm or term_no_space in combined_no_space:
                return FilterResult(
                    is_personal=False,
                    status='rejected_shared_housing',
                    reason=f"آگهی اشتراکی/همخونه رد شد (کلیدواژه منفی: '{term}')",
                    detected_terms=[term],
                    owner_type='shared_housing'
                )

        # =========================================================================
        # مرحله اول: بررسی نوع آگهی‌دهنده (Account / Advertiser Type Check)
        # =========================================================================
        account_is_personal, account_reason, detected_account_terms = cls._check_advertiser_account_type(
            platform=platform,
            widget_data=widget_data,
            raw_text=raw_text,
            title=title
        )

        if not account_is_personal:
            return FilterResult(
                is_personal=False,
                status='rejected_account_type',
                reason=account_reason,
                detected_terms=detected_account_terms,
                owner_type='agency',
                confidence_score=0,
                risk_level='high',
                metadata={'stage': 1, 'platform': platform}
            )

        # =========================================================================
        # مرحله دوم: بررسی عنوان و متن آگهی شخصی (Title & Description Content Check)
        # =========================================================================
        text_is_clean, text_reason, detected_text_terms = cls._check_forbidden_words_in_content(
            title=title,
            description=f"{description} {raw_text}".strip()
        )

        if not text_is_clean:
            conf = max(0, 35 - len(detected_text_terms) * 10)
            return FilterResult(
                is_personal=False,
                status='rejected_forbidden_words',
                reason=text_reason,
                detected_terms=detected_text_terms,
                owner_type='agency',
                confidence_score=conf,
                risk_level='high',
                metadata={'stage': 2, 'platform': platform}
            )

        # =========================================================================
        # تأیید نهایی: آگهی‌دهنده شخصی + بدون کلمات املاکی در عنوان و متن
        # =========================================================================
        combined_text = clean_persian_text(f"{title} {description} {raw_text}")
        confidence = 85
        personal_markers = ['سند تک برگ', 'مالک هستم', 'شخصی ساز', 'فروشنده واقعی', 'بدون واسطه', 'تخفیف پای معامله']
        found_markers = []
        for marker in personal_markers:
            if marker in combined_text:
                confidence = min(100, confidence + 3)
                found_markers.append(marker)

        return FilterResult(
            is_personal=True,
            status='approved_personal',
            reason="تأییدشده: حساب کاربری شخصی و فاقد کلمات فیلتر در عنوان و متن",
            detected_terms=[],
            owner_type='personal',
            confidence_score=confidence,
            risk_level='low' if confidence >= 80 else 'medium',
            metadata={'stage': 'approved', 'platform': platform, 'positive_markers': found_markers}
        )

    @classmethod
    def is_direct_owner_declared(cls, title: str, description: str = "") -> bool:
        """
        تشخیص صریح این که آگهی‌دهنده نوشته: من مالک هستم، مالک ملک، شخصی، بی‌واسطه
        این آگهی‌ها اولویت حداکثری و امتیاز VIP دریافت می‌کنند
        """
        text = clean_persian_text(f"{title} {description}")
        owner_markers = [
            'مالک هستم', 'مالک می باشم', 'مالکم', 'من مالک', 'مالک اصلی', 
            'شخصی و بی واسطه', 'بی واسطه', 'بی‌واسطه', 'بدون واسطه', 
            'مستقیم از مالک', 'تماس با مالک', 'تماس مستقیم با مالک', 
            'آگهی دهنده شخصی', 'شخصی ساز و مالک', 'واگذاری توسط مالک',
            'مالک واحد هستم', 'مالک آپارتمان'
        ]
        return any(m in text for m in owner_markers)

    @classmethod
    def _check_advertiser_account_type(cls, platform: str, widget_data: Dict[str, Any], raw_text: str, title: str = "") -> Tuple[bool, str, List[str]]:
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

            # بررسی ویجت بیزینس اختصاصی
            if widget_data.get('has_business_widget'):
                detected.append("divar:has_business_widget")

            # ۲. بررسی تگ‌های پنل/آژانس (image_top_left_tag / red_text)
            tag_obj = widget_data.get('image_top_left_tag') or widget_data.get('red_text') or ''
            if isinstance(tag_obj, dict):
                tag_text = clean_persian_text(tag_obj.get('text', ''))
                if any(t in tag_text for t in ['آژانس', 'املاک', 'مشاور', 'تجاری', 'مسکن']):
                    detected.append(f"tag:{tag_text}")
            elif isinstance(tag_obj, str) and any(t in clean_persian_text(tag_obj) for t in ['آژانس', 'املاک', 'تجاری', 'مسکن']):
                detected.append(f"tag:{tag_obj}")

            # ۳. در دیوار، نام آژانس و دفتر املاک در bottom_description_text، عنوان یا top_description_text درج می‌شود
            # برای کاربران شخصی، همواره زمان ثبت (مانند «دقایقی پیش در ...») درج می‌شود نه نام آژانس
            bottom_desc = clean_persian_text(widget_data.get('bottom_description_text', ''))
            top_desc = clean_persian_text(widget_data.get('top_description_text', ''))
            mid_desc = clean_persian_text(widget_data.get('middle_description_text', ''))
            meta_combined = f"{bottom_desc} {top_desc} {mid_desc} {raw_text}"

            for term in cls.NON_PERSONAL_ACCOUNT_TERMS:
                if term in meta_combined:
                    detected.append(f"account_name_has:{term}")

        elif platform == 'sheypoor':
            cleaned_raw = clean_persian_text(f"{raw_text} {title}")
            # شیپور: برچسب Ad یا تابلو شده یا نام آژانس نشان‌دهنده حساب تجاری/دفتر است
            if 'ad تابلو شده' in cleaned_raw or 'تابلو شده' in cleaned_raw or 'ad' in raw_text.split():
                detected.append("sheypoor:sponsored_ad_account")

            for term in ['آژانس', 'املاک', 'دپارتمان', 'مشاورین', 'مسکن', 'فروشگاه', 'مشاور', 'مشاوره', 'آرتا']:
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

        # عبارات طبیعی که کلمه خانه در آنها به عنوان محل یا صنف املاکی نیست
        SAFE_KHANEH_PHRASES = [
            'صاحب خانه', 'صاحبخانه', 'آشپز خانه', 'آشپزخانه', 'هم خانه', 'همخانه',
            'تحویل خانه', 'تخلیه خانه', 'پشت قباله خانه', 'خانه به دوش', 'خانه سالمندان',
            'چای خانه', 'چایخانه', 'گرمابه و خانه', 'خانه فرهنگ'
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

        # ۳. بررسی پنهان‌سازی‌های نویسه‌ای و فاصله‌دار (Stealth Obfuscation)
        # شناسایی کلماتی نظیر «ا م ل ا ک»، «ا*م*ل*ا*ک»، «م.ش.ا.و.ر»
        de_punct = re.sub(r'[\s\.\-\_\*\#\/\\]+', '', combined)
        STEALTH_CRITICAL = ['املاک', 'مشاور', 'مسکن', 'دپارتمان', 'کمیسیون', 'کارشناس']
        for s_word in STEALTH_CRITICAL:
            if s_word in de_punct and s_word not in text_to_check:
                if not any(sw in combined for sw in ['کارخانه', 'صاحبخانه', 'آشپزخانه', 'داروخانه']):
                    detected.append(f"پنهان‌سازی نویسه‌ای: {s_word}")

        if detected:
            terms_str = "، ".join(detected)
            return (False, f"وجود کلمات فیلتر در عنوان یا متن آگهی: [{terms_str}]", detected)

        return (True, "عنوان و متن فاقد هرگونه کلمات فیلتر است", [])

def convert_persian_words_to_digits(text: str) -> str:
    """تبدیل اعداد حروفی فارسی به ارقام جهت استخراج شماره‌های نوشته‌شده به حروف"""
    from crawler.contact_extractor import ContactExtractor
    return ContactExtractor.convert_persian_words_to_digits(text)

def extract_phone_number(text: Optional[str], filter_dummy: bool = False) -> Optional[str]:
    """
    استخراج شماره موبایل واقعی (ایران: 09xxxxxxxxx) از متن آگهی یا بافت ورودی
    متصل به موتور متمرکز و هوشمند ContactExtractor با پشتیبانی از دیکودر ارقام حروفی،
    پیش‌شماره‌های بین‌المللی و فیلتر شماره‌های جعلی/اسپم
    """
    from crawler.contact_extractor import ContactExtractor
    return ContactExtractor.extract_primary_phone(text, filter_dummy=filter_dummy)


