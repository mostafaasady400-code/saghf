import re
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator

PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
ENGLISH_DIGITS = '0123456789'
ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩'
DIGIT_TRANS = str.maketrans(PERSIAN_DIGITS + ARABIC_DIGITS, ENGLISH_DIGITS * 2)

def persian_to_english_numbers(text: Any) -> str:
    if not text:
        return ''
    return str(text).translate(DIGIT_TRANS)

def parse_price(val: Any) -> int:
    """
    پارس دقیق و هوشمند انواع مبالغ متنی و عددی فارسی، ریال و تومان
    پشتیبانی از مبالغ ترکیبی مانند: «۵ میلیارد و ۳۰۰ میلیون تومان»، «۵.۵ میلیارد» و تبدیل به عدد صحیح تمیز (Clean Integer)
    """
    if val is None or val == '':
        return 0
    if isinstance(val, (int, float)):
        return min(int(round(float(val))), 500_000_000_000)

    text = persian_to_english_numbers(str(val)).lower()
    text = text.replace('\u200c', ' ').replace('/', '.').replace('،', ',').strip()

    # عبارات بدون قیمت عددی
    if any(k in text for k in ['توافقی', 'رایگان', 'معاوضه', 'نیاز به هماهنگی', 'تماس بگیرید']):
        return 0

    is_rial = 'ریال' in text

    # ۱. استخراج عبارات ترکیبی میلیارد/همت و میلیون (مانند ۵ میلیارد و ۵۰۰ میلیون)
    billions = 0.0
    millions = 0.0
    thousands = 0.0

    m_b = re.search(r'(\d+(?:\.\d+)?)\s*(?:میلیارد|همت)', text)
    if m_b:
        try:
            billions = float(m_b.group(1))
        except ValueError:
            pass

    m_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:میلیون)', text)
    if m_m:
        try:
            millions = float(m_m.group(1))
        except ValueError:
            pass

    m_k = re.search(r'(\d+(?:\.\d+)?)\s*(?:هزار)', text)
    if m_k:
        try:
            thousands = float(m_k.group(1))
        except ValueError:
            pass

    if billions > 0 or millions > 0 or thousands > 0:
        total = int(round(billions * 1_000_000_000 + millions * 1_000_000 + thousands * 1_000))
        return min(int(total // 10 if is_rial else total), 500_000_000_000)

    # ۲. استخراج اعداد با جداکننده کاما یا خط تیره (مانند ۲۲,۰۰۰,۰۰۰,۰۰۰)
    m_comma = re.search(r'(\d{1,3}(?:,\d{3})+)', text)
    if m_comma:
        digits_val = int(m_comma.group(1).replace(',', ''))
        return min(int(digits_val // 10 if is_rial else digits_val), 500_000_000_000)

    # ۳. استخراج سایر اعداد پیوسته (مثلاً 5000000)
    raw_digits = re.findall(r'\b\d{4,14}\b', text.replace(',', ''))
    if raw_digits:
        v = int(raw_digits[0])
        return min(int(v // 10 if is_rial else v), 500_000_000_000)
    return 0

def sanitize_property_financials(
    deal_type: str,
    total_price: int = 0,
    deposit: int = 0,
    monthly_rent: int = 0,
    property_type: str = 'apartment'
) -> Tuple[int, int, int]:
    """
    اعمال قوانین اعتبارسنجی (Sanity Check) روی ارقام مالی املاک مسکونی:
    - رفع باگ ضرب اضافه در ۱,۰۰۰,۰۰۰ و ارقام نجومی
    - تفکیک نوع معامله (در رهن/اجاره total_price=0 و در فروش deposit=monthly_rent=0)
    - اعتبارسنجی نسبت ودیعه و اجاره (اجاره معمولاً کمتر از ودیعه است؛ تصحیح جابجایی احتمالی)
    - اعمال سقف منطقی اجاره ماهانه (حداکثر ۳۰۰ میلیون مسکونی) و ودیعه (حداکثر ۵۰ میلیارد)
    - حذف اعداد ساختگی و کم‌ارزش (زیر ۱۰۰ هزار تومان مانند ۱، ۱۰۰۰ و ...)
    """
    total_price = int(total_price or 0)
    deposit = int(deposit or 0)
    monthly_rent = int(monthly_rent or 0)
    deal_type = (deal_type or 'sale').lower().strip()

    if deal_type == 'sale':
        deposit = 0
        monthly_rent = 0
        # حذف ارقام ساختگی/پلیس‌هولدر
        if 0 < total_price < 50_000_000:
            total_price = 0
        # تصحیح ارقام نجومی ضرب‌شده در یک میلیون
        elif total_price > 1_000_000_000_000:
            total_price //= 1_000_000
        total_price = min(total_price, 500_000_000_000)
    else:
        # رهن و اجاره
        total_price = 0

        # ۱. تصحیح ارقام نجومی ناشی از ضرب قبلی در یک میلیون
        if deposit > 100_000_000_000:
            deposit //= 1_000_000
        if monthly_rent > 10_000_000_000:
            monthly_rent //= 1_000_000

        # ۲. بررسی جابجایی احتمالی ودیعه و اجاره توسط آگهی‌دهنده:
        # در رهن و اجاره، مبلغ اجاره ماهانه معمولاً کمتر از مبلغ ودیعه است.
        if deposit > 0 and monthly_rent > deposit and monthly_rent >= 100_000_000 and deposit <= 50_000_000:
            deposit, monthly_rent = monthly_rent, deposit

        # ۳. اعتبارسنجی سقف اجاره مسکونی و تصحیح ضرب مضاعف
        if monthly_rent > 300_000_000:
            if monthly_rent % 1_000_000 == 0 and (monthly_rent // 1_000_000) <= 300_000_000:
                monthly_rent //= 1_000_000
            else:
                monthly_rent = min(monthly_rent, 300_000_000)

        # ۴. حذف ارقام صوری یا ناچیز (مانند ۱ تومان یا ۱۰۰۰ تومان)
        if 0 < deposit < 100_000:
            deposit = 0
        if 0 < monthly_rent < 100_000:
            monthly_rent = 0

        # ۵. سقف منطقی ودیعه مسکونی (حداکثر ۵۰ میلیارد تومان)
        if deposit > 50_000_000_000:
            deposit = 50_000_000_000

    return int(total_price), int(deposit), int(monthly_rent)

class OwnerSchema(BaseModel):
    name: str = Field(default="مالک آگهی", min_length=1)
    phone: str = Field(default="", description="شماره تماس معتبر")
    urgency: str = Field(default="medium")
    flexibility: str = Field(default="معمولی")
    notes: Optional[str] = None

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        clean = persian_to_english_numbers(v).strip().replace(" ", "").replace("-", "")
        if clean.startswith("+98"):
            clean = "0" + clean[3:]
        elif clean.startswith("98"):
            clean = "0" + clean[2:]
        return clean

class NormalizedPropertySchema(BaseModel):
    source: str = Field(..., description="پلتفرم مبدا مانند divar یا sheypoor")
    source_id: str = Field(..., min_length=3, description="شناسه یکتا در پلتفرم مبدا")
    source_url: str = Field(..., description="لینک مستقیم آگهی")
    title: str = Field(..., min_length=3, max_length=300)
    deal_type: str = Field(..., description="sale یا rent")
    property_type: str = Field(default="apartment")
    city: str = Field(default="تهران")
    district: str = Field(default="نامشخص")
    address: Optional[str] = None
    
    # Financials (Clean Integers)
    total_price: int = Field(default=0, ge=0)
    meter_price: int = Field(default=0, ge=0)
    deposit: int = Field(default=0, ge=0)
    monthly_rent: int = Field(default=0, ge=0)
    
    # Dimensions & Features
    area: int = Field(default=100, ge=10, le=50000)
    rooms: int = Field(default=1, ge=0, le=20)
    floor: int = Field(default=1, ge=-5, le=100)
    total_floors: Optional[int] = Field(default=None)
    build_year: Optional[int] = Field(default=1400)
    
    # Amenities
    has_elevator: bool = False
    has_parking: bool = False
    has_warehouse: bool = False
    has_balcony: bool = False
    
    features: List[str] = Field(default_factory=list)
    description: Optional[str] = ""
    images: List[str] = Field(default_factory=list)
    status: str = Field(default="raw_crawled")
    score: int = Field(default=75, ge=0, le=100)
    
    # Owner & Filter Information
    owner_type: str = Field(default="personal", description="personal یا agency")
    is_personal_owner: bool = Field(default=True, description="آیا آگهی شخصی است")
    filter_log: Optional[str] = Field(default="", description="علت و توضیحات نتیجه فیلتر")
    
    owner_info: Optional[OwnerSchema] = None

    @field_validator('total_price', 'meter_price', 'deposit', 'monthly_rent', mode='before')
    @classmethod
    def clean_integer_price(cls, v: Any) -> int:
        if v is None or v == '':
            return 0
        if isinstance(v, (int, float)):
            return int(round(float(v)))
        return parse_price(v)

    @model_validator(mode='after')
    def validate_and_sanitize_financials(self) -> 'NormalizedPropertySchema':
        s_price, s_dep, s_rent = sanitize_property_financials(
            deal_type=self.deal_type,
            total_price=self.total_price,
            deposit=self.deposit,
            monthly_rent=self.monthly_rent,
            property_type=self.property_type
        )
        self.total_price = s_price
        self.deposit = s_dep
        self.monthly_rent = s_rent
        if self.area > 0 and self.total_price > 0 and self.meter_price == 0:
            self.meter_price = int(self.total_price // self.area)
        return self

    @field_validator('district')
    @classmethod
    def clean_district(cls, v: str) -> str:
        if not v:
            return "تهران"
        clean = v.replace("در ", "").strip()
        return clean or "تهران"

    @field_validator('title')
    @classmethod
    def clean_title(cls, v: str) -> str:
        return re.sub(r'\s+', ' ', v).strip()

    @field_validator('images')
    @classmethod
    def clean_images(cls, v: List[str]) -> List[str]:
        """فیلتر و تضمین عدم ذخیره داده باینری، Base64 یا محتوای فیزیکی در دیتابیس"""
        if not v:
            return []
        cleaned = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s.startswith(('http://', 'https://')) and not s.startswith('data:') and ';base64,' not in s:
                    cleaned.append(s)
        return cleaned
