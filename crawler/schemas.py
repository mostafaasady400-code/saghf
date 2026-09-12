import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator

PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
ENGLISH_DIGITS = '0123456789'
DIGIT_TRANS = str.maketrans(PERSIAN_DIGITS, ENGLISH_DIGITS)

def persian_to_english_numbers(text: Any) -> str:
    if not text:
        return ''
    return str(text).translate(DIGIT_TRANS)

def parse_price(val: Any) -> int:
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return min(int(val), 500_000_000_000)
    text = persian_to_english_numbers(str(val))
    # 1. Comma-separated currency formatting (e.g. 22,000,000,000)
    m = re.search(r'(\d{1,3}(?:[,\،]\d{3})+)', text)
    if m:
        cleaned = m.group(1).replace(',', '').replace('،', '')
        return min(int(cleaned), 500_000_000_000)

    # 2. Text words like میلیارد or میلیون
    m2 = re.search(r'(\d+)\s*(?:میلیارد|همت)', text)
    if m2:
        return min(int(m2.group(1)) * 1_000_000_000, 500_000_000_000)
    m3 = re.search(r'(\d+)\s*(?:میلیون)', text)
    if m3:
        return min(int(m3.group(1)) * 1_000_000, 500_000_000_000)

    # 3. Discrete numbers
    digits = re.findall(r'\b\d{5,13}\b', text.replace(',', '').replace('،', ''))
    if digits:
        return min(int(digits[0]), 500_000_000_000)
    return 0

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
    
    # Financials
    total_price: int = Field(default=0, ge=0)
    meter_price: int = Field(default=0, ge=0)
    deposit: int = Field(default=0, ge=0)
    monthly_rent: int = Field(default=0, ge=0)
    
    # Dimensions & Features
    area: int = Field(default=100, ge=10, le=50000)
    rooms: int = Field(default=1, ge=0, le=20)
    floor: int = Field(default=1, ge=-5, le=100)
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
    
    owner_info: Optional[OwnerSchema] = None

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
