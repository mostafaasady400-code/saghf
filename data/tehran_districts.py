"""
کاتالوگ جامع مناطق ۲۲گانه و محله‌های شهر تهران
متصل به tehran_districts.json جهت فیلترینگ چندانتخابی دقیق، تطابق با API دیوار و شیپور و استخراج NLP
"""

import os
import json
from typing import Dict, List, Any, Optional

JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tehran_districts.json')

_CACHE_REGIONS: Optional[Dict[str, Dict[str, Any]]] = None
_CACHE_SLUG_MAP: Optional[Dict[str, str]] = None
_CACHE_NAME_TO_SLUG: Optional[Dict[str, str]] = None

def _load_data():
    global _CACHE_REGIONS, _CACHE_SLUG_MAP, _CACHE_NAME_TO_SLUG
    if _CACHE_REGIONS is not None and len(_CACHE_REGIONS) > 0:
        return

    _CACHE_REGIONS = {}
    _CACHE_SLUG_MAP = {}
    _CACHE_NAME_TO_SLUG = {}

    if os.path.exists(JSON_PATH):
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                for reg in raw_data.get('regions', []):
                    reg_id = str(reg.get('id'))
                    districts_list = reg.get('districts', [])
                    _CACHE_REGIONS[reg_id] = {
                        'id': reg_id,
                        'region_id': int(reg_id) if reg_id.isdigit() else reg_id,
                        'name': reg.get('name'),
                        'districts': districts_list,
                        'sub_districts': districts_list
                    }
                    for d in districts_list:
                        d_name = d.get('name')
                        d_slug = d.get('divar_slug')
                        if d_name and d_slug:
                            _CACHE_SLUG_MAP[d_slug] = d_name
                            _CACHE_NAME_TO_SLUG[d_name] = d_slug
        except Exception as e:
            print(f"[TehranDistricts] خطا در بارگذاری {JSON_PATH}: {e}")

_load_data()

# دیکشنری سازگار با نسخه‌های قبلی
TEHRAN_REGIONS: Dict[str, Dict[str, Any]] = _CACHE_REGIONS or {}

def get_all_tehran_regions() -> List[Dict[str, Any]]:
    """دریافت ساختار کامل تمام مناطق ۲۲گانه و محله‌های زیرمجموعه"""
    _load_data()
    return list(_CACHE_REGIONS.values()) if _CACHE_REGIONS else []

def get_region_districts(region_id: str = '5') -> List[Dict[str, Any]]:
    """لیست محله‌های یک منطقه خاص"""
    _load_data()
    reg = _CACHE_REGIONS.get(str(region_id))
    return reg['districts'] if reg else []

def get_district_names(region_id: Optional[str] = None) -> List[str]:
    """دریافت نام محله‌ها به صورت لیست رشته‌ای"""
    _load_data()
    if region_id and str(region_id) in _CACHE_REGIONS:
        return [d['name'] for d in _CACHE_REGIONS[str(region_id)]['districts']]
    all_names = []
    for reg in _CACHE_REGIONS.values():
        for d in reg['districts']:
            all_names.append(d['name'])
    return all_names

def _clean_persian_str(s: str) -> str:
    if not s:
        return ""
    return s.replace('\u200c', ' ').replace('ي', 'ی').replace('ك', 'ک').strip()

def _clean_compact_str(s: str) -> str:
    return _clean_persian_str(s).replace(' ', '')

# محله‌های رسمی و شاخص منطقه ۲ تهران
REGION_2_DISTRICT_NAMES = [
    'سعادت آباد', 'سعادت‌آباد', 'شهرک غرب', 'گیشا', 'کوی نصر', 'مرزداران', 
    'ستارخان', 'طرشت', 'شهرک ژاندارمری', 'ژاندارمری', 'فرحزاد', 'شهرآرا', 
    'بهبودی', 'توحید', 'دریان نو', 'همایون شهر', 'ایوانک', 'کوی فراز', 
    'پرواز', 'صادقیه', 'بلوار پاکنژاد', 'بلوار دادمان', 'بلوار شهرداری', 
    'شهرک مخابرات', 'آسمان'
]

# محله‌های رسمی و شاخص منطقه ۵ تهران
REGION_5_DISTRICT_NAMES = [
    'پونک', 'جنت آباد', 'جنت‌آباد', 'جنت آباد مرکزی', 'جنت‌آباد مرکزی', 
    'جنت آباد جنوبی', 'جنت‌آباد جنوبی', 'جنت آباد شمالی', 'جنت‌آباد شمالی', 
    'صادقیه', 'آریاشهر', 'شهران', 'شهران شمالی', 'شهران جنوبی', 'باغ فیض', 
    'باغ‌فیض', 'بلوار فردوس', 'فردوس', 'فردوس شرق', 'فردوس غرب', 'اباذر', 
    'ابوذر', 'بلوار اباذر', 'اکباتان', 'شهرک اکباتان', 'شاهین', 'شاهین شمالی', 
    'شاهین جنوبی', 'سازمان برنامه', 'سازمان برنامه شمالی', 'سازمان برنامه جنوبی', 
    'شهرزیبا', 'شهر زیبا', 'کوهسار', 'کن', 'آیت الله کاشانی', 'کاشانی', 
    'بلوار کاشانی', 'مهران', 'ارم', 'شهرک ارم', 'بیمه', 'شهرک بیمه', 
    'آپادانا', 'شهرک آپادانا', 'المهدی', 'حصارک', 'سازمان آب'
]

# تلفیق مناطق هدف ۲ و ۵
DISTRICTS_2_AND_5_NAMES = REGION_2_DISTRICT_NAMES + REGION_5_DISTRICT_NAMES

DISTRICTS_2_AND_5_SLUGS = [
    'saadat-abad', 'shahrak-e-gharb', 'gisha', 'marzdaran', 'sattarkhan', 
    'tarasht', 'zhandarmari', 'farahzad', 'shahrara', 'punak', 
    'central-jannat-abad', 'south-jannat-abad', 'north-jannat-abad', 
    'sadeghiyeh', 'shahran', 'bagh-feyz', 'ferdows', 'abazar', 
    'ekbatan', 'shahin', 'sazman-barnameh', 'shahr-e-ziba', 'koohsar', 'kan'
]

def is_in_region_2_or_5(district_name: Optional[str], text: Optional[str] = "") -> bool:
    """
    بررسی دقیق و قطعی اینکه آیا یک محله یا ملک در منطقه ۲ یا ۵ تهران واقع شده است یا خیر.
    تمرکز ۱۰۰ درصدی بر تفکیک مناطق ۲ و ۵ پایتخت.
    """
    if not district_name and not text:
        return False
    clean_d = _clean_persian_str(district_name or '')
    clean_t = _clean_persian_str(text or '')
    compact_d = _clean_compact_str(clean_d)
    compact_t = _clean_compact_str(clean_t)

    # بررسی تطابق با نام‌های مناطق ۲ و ۵
    for name in DISTRICTS_2_AND_5_NAMES:
        c_name = _clean_compact_str(name)
        if len(c_name) < 2:
            continue
        if c_name in compact_d or compact_d in c_name:
            return True
        if len(c_name) >= 4 and c_name in compact_t:
            return True

    # بررسی عبارات کلیدی منطقه ۲ و منطقه ۵
    if 'منطقه۲' in compact_d or 'منطقه2' in compact_d or 'منطقه۵' in compact_d or 'منطقه5' in compact_d:
        return True
    if 'منطقه۲' in compact_t or 'منطقه2' in compact_t or 'منطقه۵' in compact_t or 'منطقه5' in compact_t:
        return True

    return False

def get_region_2_and_5_districts() -> List[str]:
    """دریافت لیست تمام محله‌های مناطق ۲ و ۵ تهران به صورت یکجا"""
    return list(set(DISTRICTS_2_AND_5_NAMES))

def get_region_for_district(district_name: Optional[str]) -> Optional[str]:
    """یافتن شماره منطقه شهرداری تهران بر اساس نام محله"""
    if not district_name:
        return None
    _load_data()
    clean_d = _clean_persian_str(district_name)
    compact_d = _clean_compact_str(clean_d)

    # اولویت جستجو با مناطق ۲ و ۵
    if is_in_region_2_or_5(district_name, ""):
        for name in REGION_5_DISTRICT_NAMES:
            c = _clean_compact_str(name)
            if len(c) >= 2 and (c in compact_d or compact_d in c):
                return '5'
        for name in REGION_2_DISTRICT_NAMES:
            c = _clean_compact_str(name)
            if len(c) >= 2 and (c in compact_d or compact_d in c):
                return '2'

    # جستجو در تمام مناطق ۲۲ گانه
    for reg_id, reg in _CACHE_REGIONS.items():
        for d in reg.get('districts', []):
            d_name = d.get('name', '')
            c_name = _clean_compact_str(d_name)
            if len(c_name) >= 2 and (c_name in compact_d or compact_d in c_name):
                return str(reg_id)
            for kw in d.get('keywords', []):
                c_kw = _clean_compact_str(kw)
                if len(c_kw) >= 3 and (c_kw in compact_d or compact_d in c_kw):
                    return str(reg_id)
    return None

def is_in_target_districts(district_name: Optional[str], text: Optional[str] = "", target_districts: Optional[List[str]] = None) -> bool:
    """
    بررسی انطباق محله یا متن آگهی با لیست محله‌های هدف دفتر املاک.
    اگر target_districts مشخص نشده یا خالی باشد، به عنوان رفتار پیش‌فرض منطقه ۲ و ۵ تهران بررسی می‌شود.
    """
    if not target_districts:
        return is_in_region_2_or_5(district_name, text)

    clean_d = _clean_persian_str(district_name or '')
    clean_t = _clean_persian_str(text or '')
    compact_d = _clean_compact_str(clean_d)
    compact_t = _clean_compact_str(clean_t)

    for target in target_districts:
        c_target = _clean_compact_str(target)
        if len(c_target) < 2:
            continue
        if compact_d and (c_target in compact_d or compact_d in c_target):
            return True
        if compact_t and len(c_target) >= 3 and c_target in compact_t:
            return True

    return False

def get_divar_slug_for_district(district_name: str) -> Optional[str]:
    """تبدیل نام محله فارسی به slug معادل در دیوار"""
    if not district_name:
        return None
    _load_data()
    name = district_name.strip()
    if name in _CACHE_NAME_TO_SLUG:
        return _CACHE_NAME_TO_SLUG[name]

    name_clean = _clean_persian_str(name)
    name_compact = _clean_compact_str(name)

    # تطابق مستقیم با نام‌های نرمال‌شده
    for d_name, d_slug in _CACHE_NAME_TO_SLUG.items():
        if _clean_persian_str(d_name) == name_clean or _clean_compact_str(d_name) == name_compact:
            return d_slug

    # جستجو در کلیدواژه‌ها
    for reg in _CACHE_REGIONS.values():
        for d in reg['districts']:
            for kw in d.get('keywords', []):
                kw_clean = _clean_persian_str(kw)
                kw_compact = _clean_compact_str(kw)
                if kw_clean == name_clean or kw_compact == name_compact:
                    return d['divar_slug']
                if len(kw_compact) >= 3 and (kw_compact in name_compact or name_compact in kw_compact):
                    return d['divar_slug']
    return None

def find_matched_district(text: str) -> Optional[str]:
    """
    تشخیص هوشمند محله از داخل متن ورودی (توضیحات یا رونوشت مکالمه صوتی)
    """
    if not text:
        return None
    _load_data()
    normalized = _clean_persian_str(text)
    norm_compact = _clean_compact_str(text)
    
    # اولویت جستجو با مناطق پرتقاضا: ۵، ۲، ۱، ۳، ۴
    priority_order = ['5', '2', '1', '3', '4', '6', '7', '8', '22']
    all_keys = priority_order + [k for k in _CACHE_REGIONS.keys() if k not in priority_order]

    for reg_key in all_keys:
        if reg_key in _CACHE_REGIONS:
            for d in _CACHE_REGIONS[reg_key]['districts']:
                keywords = d.get('keywords', []) + [d['name']]
                for kw in keywords:
                    kw_clean = _clean_persian_str(kw)
                    kw_compact = _clean_compact_str(kw)
                    if kw_clean in normalized or (len(kw_compact) >= 4 and kw_compact in norm_compact):
                        return d['name']
    return None


OFFICIAL_DIVAR_JSON = os.path.join(os.path.dirname(__file__), 'divar_official_districts.json')
_OFFICIAL_DISTRICTS = []

def _load_official_districts():
    global _OFFICIAL_DISTRICTS
    if not _OFFICIAL_DISTRICTS and os.path.exists(OFFICIAL_DIVAR_JSON):
        try:
            with open(OFFICIAL_DIVAR_JSON, 'r', encoding='utf-8') as f:
                data = json.load(f)
                _OFFICIAL_DISTRICTS = data.get('districts', [])
        except Exception:
            pass

DISTRICT_ALIASES_TO_IDS = {
    'پونک': [82],
    'شهران': [151, 152],
    'شهران شمالی': [151],
    'شهران جنوبی': [152],
    'سعادت آباد': [76],
    'سعادت‌آباد': [76],
    'شهرک غرب': [78],
    'جنت آباد': [143, 144, 145],
    'جنت‌آباد': [143, 144, 145],
    'جنت آباد مرکزی': [144],
    'جنت‌آباد مرکزی': [144],
    'جنت آباد جنوبی': [145],
    'جنت‌آباد جنوبی': [145],
    'جنت آباد شمالی': [143],
    'جنت‌آباد شمالی': [143],
    'صادقیه': [84],
    'آریاشهر': [84],
    'مرزداران': [139],
    'ستارخان': [205],
    'گیشا': [88],
    'کوی نصر': [88],
    'فردوس': [170],
    'بلوار فردوس': [170],
    'باغ فیض': [83],
    'باغ‌فیض': [83],
    'سازمان برنامه': [171, 172],
    'سازمان برنامه شمالی': [171],
    'سازمان برنامه جنوبی': [172],
    'اکباتان': [177],
    'شهرک اکباتان': [177],
    'شاهین': [150],
    'شاهین شمالی': [150],
    'شهرزیبا': [153],
    'شهر زیبا': [153],
    'اباذر': [170],
    'کوهسار': [151],
    'کن': [154],
}

def get_divar_district_ids(district_name: str) -> list:
    """دریافت شناسه‌های عددی رسمی محله در دیوار جهت جستجوی مستقیم"""
    if not district_name:
        return []
    cleaned = _clean_persian_str(district_name).strip()
    compact = _clean_compact_str(district_name)
    for alias, ids in DISTRICT_ALIASES_TO_IDS.items():
        if _clean_persian_str(alias) == cleaned or _clean_compact_str(alias) == compact:
            return ids
    _load_official_districts()
    matched_ids = []
    for d in _OFFICIAL_DISTRICTS:
        d_name = _clean_persian_str(d.get('name', ''))
        d_compact = _clean_compact_str(d.get('name', ''))
        if d_name == cleaned or d_compact == compact:
            return [int(d['id'])]
        if cleaned and len(cleaned) >= 4 and cleaned in d_name:
            matched_ids.append(int(d['id']))
    return matched_ids
