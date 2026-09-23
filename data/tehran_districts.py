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
