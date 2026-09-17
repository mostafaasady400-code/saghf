"""
کاتالوگ جامع مناطق و محله‌های شهر تهران با تمرکز ویژه بر منطقه ۵ و مناطق پرتقاضا
جهت فیلترینگ چندانتخابی (Multi-Select) در کراولر دیوار و شیپور و استخراج NLP
"""

from typing import Dict, List, Any, Optional

TEHRAN_REGIONS: Dict[str, Dict[str, Any]] = {
    '5': {
        'name': 'منطقه ۵ (غرب تهران)',
        'description': 'شامل پونک، جنت‌آباد، صادقیه، شهران، باغ‌فیض، بلوار فردوس و...',
        'districts': [
            {'name': 'پونک', 'divar_slug': 'poonak', 'sheypoor_id': 'poonak', 'keywords': ['پونک', 'همیلا', 'عدل', 'کمالی', 'سردار جنگل']},
            {'name': 'جنت‌آباد', 'divar_slug': 'jannat-abad', 'sheypoor_id': 'jannat-abad', 'keywords': ['جنت‌آباد', 'جنت اباد', 'جنت‌آباد جنوبی', 'جنت‌آباد مرکزی', 'جنت‌آباد شمالی', 'چهارباغ', 'لاله', 'کبیرزاده']},
            {'name': 'جنت‌آباد مرکزی', 'divar_slug': 'central-jannat-abad', 'sheypoor_id': 'central-jannat-abad', 'keywords': ['جنت‌آباد مرکزی', 'جنت اباد مرکزی', 'مخبری', 'شاهین شمالی']},
            {'name': 'جنت‌آباد جنوبی', 'divar_slug': 'south-jannat-abad', 'sheypoor_id': 'south-jannat-abad', 'keywords': ['جنت‌آباد جنوبی', 'جنت اباد جنوبی', 'چهارباغ', 'لاله شرقی']},
            {'name': 'جنت‌آباد شمالی', 'divar_slug': 'north-jannat-abad', 'sheypoor_id': 'north-jannat-abad', 'keywords': ['جنت‌آباد شمالی', 'جنت اباد شمالی', 'گلزار', 'ایرانپارس']},
            {'name': 'صادقیه', 'divar_slug': 'sadeghiyeh', 'sheypoor_id': 'sadeghiyeh', 'keywords': ['صادقیه', 'آریاشهر', 'فلکه اول صادقیه', 'فلکه دوم صادقیه', 'ستارخان']},
            {'name': 'شهران', 'divar_slug': 'shahran', 'sheypoor_id': 'shahran', 'keywords': ['شهران', 'شهران شمالی', 'شهران جنوبی', 'طوقانی']},
            {'name': 'باغ‌فیض', 'divar_slug': 'bagh-e-feyz', 'sheypoor_id': 'bagh-e-feyz', 'keywords': ['باغ‌فیض', 'باغ فیض', 'تیراژه', 'مهستان', 'ناطق نوری']},
            {'name': 'بلوار فردوس', 'divar_slug': 'ferdows', 'sheypoor_id': 'ferdows', 'keywords': ['بلوار فردوس', 'فردوس شرق', 'فردوس غرب', 'وفا آذر', 'سلیمی جهرمی']},
            {'name': 'اباذر', 'divar_slug': 'abazar', 'sheypoor_id': 'abazar', 'keywords': ['اباذر', 'کاشانی', 'بهنام']},
            {'name': 'اکباتان', 'divar_slug': 'ekbatan', 'sheypoor_id': 'ekbatan', 'keywords': ['اکباتان', 'شهرک اکباتان', 'فاز ۱ اکباتان', 'فاز ۲ اکباتان']},
            {'name': 'شاهین', 'divar_slug': 'shahin', 'sheypoor_id': 'shahin', 'keywords': ['شاهین', 'شاهین جنوبی', 'شاهین شمالی']},
            {'name': 'سازمان برنامه', 'divar_slug': 'sazman-barnameh', 'sheypoor_id': 'sazman-barnameh', 'keywords': ['سازمان برنامه', 'برنامه شمالی', 'برنامه جنوبی', 'شقایق']},
            {'name': 'شهرزیبا', 'divar_slug': 'shahr-e-ziba', 'sheypoor_id': 'shahr-e-ziba', 'keywords': ['شهرزیبا', 'شهر زیبا', 'آلاله', 'نیلوفر']},
            {'name': 'کوهسار', 'divar_slug': 'koohsar', 'sheypoor_id': 'koohsar', 'keywords': ['کوهسار', 'شهدای گمنام']},
            {'name': 'کن', 'divar_slug': 'kan', 'sheypoor_id': 'kan', 'keywords': ['کن', 'محله کن']}
        ]
    },
    '2': {
        'name': 'منطقه ۲ (شمال غرب تهران)',
        'description': 'شامل سعادت‌آباد، شهرک غرب، گیشا، مرزداران، ستارخان و...',
        'districts': [
            {'name': 'سعادت‌آباد', 'divar_slug': 'saadat-abad', 'sheypoor_id': 'saadat-abad', 'keywords': ['سعادت‌آباد', 'سعادت اباد', 'علامه', 'کاج', 'سرو']},
            {'name': 'شهرک غرب', 'divar_slug': 'shahrak-e-gharb', 'sheypoor_id': 'shahrak-e-gharb', 'keywords': ['شهرک غرب', 'شهرک قدس', 'ایران زمین', 'مهستان', 'گلستان']},
            {'name': 'گیشا', 'divar_slug': 'gisha', 'sheypoor_id': 'gisha', 'keywords': ['گیشا', 'کوی نصر', 'فاضل']},
            {'name': 'مرزداران', 'divar_slug': 'marzdaran', 'sheypoor_id': 'marzdaran', 'keywords': ['مرزداران', 'ناهید', 'اشرفی']},
            {'name': 'ستارخان', 'divar_slug': 'sattarkhan', 'sheypoor_id': 'sattarkhan', 'keywords': ['ستارخان', 'باقرخان', 'تهران ویلا']}
        ]
    },
    '1': {
        'name': 'منطقه ۱ (شمال تهران)',
        'description': 'شامل الهیه، زعفرانیه، نیاوران، کامرانیه، ولنجک و...',
        'districts': [
            {'name': 'الهیه', 'divar_slug': 'elahieh', 'sheypoor_id': 'elahieh', 'keywords': ['الهیه', 'فرشته']},
            {'name': 'زعفرانیه', 'divar_slug': 'zafaraniyeh', 'sheypoor_id': 'zafaraniyeh', 'keywords': ['زعفرانیه', 'آصف']},
            {'name': 'نیاوران', 'divar_slug': 'niavaran', 'sheypoor_id': 'niavaran', 'keywords': ['نیاوران', 'جمشیدیه', 'باهنر']},
            {'name': 'ولنجک', 'divar_slug': 'velenjak', 'sheypoor_id': 'velenjak', 'keywords': ['ولنجک', 'دانشجو']},
            {'name': 'کامرانیه', 'divar_slug': 'kamranieh', 'sheypoor_id': 'kamranieh', 'keywords': ['کامرانیه', 'کامرانیه شمالی', 'کامرانیه جنوبی']}
        ]
    }
}

def get_region_districts(region_id: str = '5') -> List[Dict[str, Any]]:
    """لیست محله‌های یک منطقه خاص"""
    reg = TEHRAN_REGIONS.get(str(region_id))
    return reg['districts'] if reg else []

def get_district_names(region_id: Optional[str] = None) -> List[str]:
    """دریافت نام محله‌ها به صورت متنی"""
    if region_id and str(region_id) in TEHRAN_REGIONS:
        return [d['name'] for d in TEHRAN_REGIONS[str(region_id)]['districts']]
    all_names = []
    for reg in TEHRAN_REGIONS.values():
        for d in reg['districts']:
            all_names.append(d['name'])
    return all_names

def find_matched_district(text: str) -> Optional[str]:
    """
    تشخیص هوشمند محله از داخل متن ورودی (توضیحات یا رونوشت مکالمه صوتی)
    """
    if not text:
        return None
    normalized = text.replace('ي', 'ی').replace('ك', 'ک')
    
    # اولویت جستجو با محله‌های منطقه ۵
    for reg_key in ['5', '2', '1']:
        for d in TEHRAN_REGIONS[reg_key]['districts']:
            for kw in d.get('keywords', [d['name']]):
                if kw in normalized:
                    return d['name']
    return None
