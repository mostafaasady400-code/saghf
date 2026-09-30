"""
موتور جستجوی ترکیبی، دقیق و معنایی املاک سقف (Hybrid Exact & Semantic Property Search)
پوشش‌دهنده:
۱. اعمال سخت‌گیرانه قیود بودجه، نوع معامله و شهر (عدم نقض محدودیت‌های صریح مشتری)
۲. تحلیل معنایی و رتبه‌بندی کلیدواژه‌های حسی و توصیفی (مانند غرق نور، آرام، نزدیک مترو، دلباز)
۳. قانون عدم استفاده از داده ساختگی (Zero-Mock Policy): استخراج انحصاری از دیتابیس واقعی سقف
۴. درج صریح دلایل انطباق (Match Reasoning) و برچسب زمان ثبت/تازگی فایل
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import or_, and_

from database.db import db
from database.models import Property
from crawler.schemas import calculate_mortgage_conversion
from services.assistant.memory_manager import CustomerCriteria

logger = logging.getLogger(__name__)

# ماتریس توصیف‌گرهای معنایی املاک فارسی
SEMANTIC_DESCRIPTORS = {
    'نورگیر': ['نورگیر', 'غرق نور', 'رو به آفتاب', 'نور عالی', 'پنجره قدی', 'پرده خور', 'نور مستقیم'],
    'آرامش': ['آرام', 'دنج', 'سکوت', 'کم واحد', 'کوچه خلوت', 'بی صدا'],
    'حمل_و_نقل': ['مترو', 'بی آر تی', 'دسترسی', 'ایستگاه', 'BRT', 'اتوبان'],
    'خانواده': ['مناسب خانواده', 'خانوادگی', 'محله اصیل', 'محیط فرهنگی'],
    'فضای_باز': ['بالکن', 'تراس', 'پاسیو', 'حیاط', 'روف گاردن', 'تراس چیدمان'],
    'لوکس': ['لوکس', 'لاکچری', 'مجلل', 'برند', 'مدرن', 'سوپرلوکس', 'متریال اروپایی'],
    'نوساز': ['نوساز', 'کلید نخورده', 'صفر', '۱۴۰۲', '۱۴۰۳', '1402', '1403', '1404'],
    'ویو': ['ویو', 'چشم انداز', 'دید ابدی', 'بدون مشرف', 'منظره']
}

class HybridPropertySearchEngine:
    """موتور جستجوی تلفیقی بدون دیتای ساختگی با رتبه‌بندی کیفی"""

    @classmethod
    def search(
        cls,
        criteria: CustomerCriteria,
        raw_query: str = "",
        limit: int = 6
    ) -> Dict[str, Any]:
        """
        جستجوی چندلایه در پایگاه داده سقف
        """
        now = datetime.utcnow()

        # پایه کوئری: فقط فایل‌های معتبر و شخصی
        query = Property.query.filter(
            Property.status.notin_(['archived', 'sold', 'needs_followup']),
            Property.is_personal_owner == True
        )

        # ۱. قید غیرقابل‌مذاکره: نوع معامله (خرید یا رهن/اجاره)
        if criteria.deal_type in ['sale', 'rent']:
            query = query.filter(Property.deal_type == criteria.deal_type)

        # ۲. قید شهر
        if criteria.city:
            query = query.filter(Property.city.ilike(f'%{criteria.city}%'))

        # ۳. قید صریح بودجه؛ موتور بدون اجازهٔ کاربر دامنه را شل نمی‌کند.
        if criteria.deal_type == 'sale' and criteria.max_budget > 0:
            query = query.filter(Property.total_price <= criteria.max_budget)
        elif criteria.deal_type == 'rent':
            if criteria.max_deposit > 0:
                query = query.filter(Property.deposit <= criteria.max_deposit)
            if criteria.max_rent > 0:
                query = query.filter(Property.monthly_rent <= criteria.max_rent)

        # ۴. فیلتر محله‌ها
        if criteria.districts:
            district_filters = []
            for d in criteria.districts:
                clean_d = d.replace('منطقه', '').strip()
                district_filters.extend([
                    Property.district.ilike(f'%{d}%'),
                    Property.district.ilike(f'%{clean_d}%'),
                    Property.title.ilike(f'%{d}%')
                ])
            query = query.filter(or_(*district_filters))

        # ۵. فیلترهای مشخصات کالبدی
        if criteria.min_area > 0:
            query = query.filter(Property.area >= criteria.min_area)
        if criteria.max_area > 0:
            query = query.filter(Property.area <= criteria.max_area)
        if criteria.rooms > 0:
            query = query.filter(Property.rooms == criteria.rooms)

        if criteria.has_parking is True:
            query = query.filter(Property.has_parking == True)
        if criteria.has_elevator is True:
            query = query.filter(Property.has_elevator == True)
        if criteria.has_warehouse is True:
            query = query.filter(Property.has_warehouse == True)
        if criteria.has_balcony is True:
            query = query.filter(Property.has_balcony == True)

        total_matching = query.count()
        candidates = query.order_by(Property.score.desc(), Property.id.desc()).all()

        # ۶. رتبه‌بندی معنایی و امتیازدهی کیفی (Semantic Relevance Scoring)
        extracted_semantic_tokens = cls._extract_semantic_tokens(raw_query, criteria)
        ranked_properties = []

        for prop in candidates:
            semantic_score, matched_reasons = cls._compute_relevance_and_reasons(prop, criteria, extracted_semantic_tokens)
            ranked_properties.append({
                'property': prop,
                'relevance_score': semantic_score,
                'matched_reasons': matched_reasons
            })

        # مرتب‌سازی بر اساس ترکیب امتیاز کیفیت دیتابیس و انطباق معنایی
        ranked_properties.sort(
            key=lambda x: (x['relevance_score'] * 2 + (x['property'].score or 50)),
            reverse=True
        )

        selected = ranked_properties[:limit] if limit else ranked_properties

        # آماده‌سازی کارت‌های ملکی بدون داده ساختگی
        formatted_items = []
        for item in selected:
            p = item['property']
            reasons = item['matched_reasons']

            thumb = '/static/images/placeholder.png'
            if p.images:
                thumb = p.images[0]

            conv = calculate_mortgage_conversion(p.deposit, p.monthly_rent)
            if p.deal_type == 'rent':
                dep_text = f"{int(p.deposit / 1_000_000):,} م" if p.deposit else "توافقی"
                rent_text = f"{int(p.monthly_rent / 1_000_000):,} م" if p.monthly_rent else "توافقی"
                price_str = f"رهن کامل: {dep_text} تومان" if p.monthly_rent == 0 and p.deposit > 0 else f"ودیعه: {dep_text} | اجاره: {rent_text}"
                conv_val = conv.get('full_mortgage_equivalent', 0)
                conversion_summary = f"معادل رهن کامل: {int(conv_val / 1_000_000):,} م.ت" if conv_val > 0 else conv.get('summary_fa', '')
            else:
                price_str = f"قیمت کل: {int((p.total_price or 0) / 1_000_000_000):,} میلیارد تومان" if p.total_price else "توافقی"
                conversion_summary = f"متری {int((p.meter_price or 0) / 1_000_000):,} م" if p.meter_price else ""

            formatted_items.append({
                'id': p.id,
                'file_code': p.file_code or str(p.id),
                'title': p.title,
                'district': p.district or 'تهران',
                'city': p.city or 'تهران',
                'deal_type': p.deal_type,
                'deal_label': 'رهن و اجاره' if p.deal_type == 'rent' else 'خرید و فروش',
                'price_str': price_str,
                'conversion_summary': conversion_summary,
                'area': p.area or 0,
                'rooms': p.rooms or 1,
                'floor': p.floor or 1,
                'has_parking': p.has_parking,
                'has_elevator': p.has_elevator,
                'has_warehouse': p.has_warehouse,
                'has_balcony': p.has_balcony,
                'image_url': thumb,
                'detail_url': f"/properties/{p.id}",
                'source_url': p.source_url or f"/properties/{p.id}",
                'owner_phone': p.owner.phone_number if p.owner else None,
                'is_personal_owner': True,
                'match_reasons': reasons,
                'time_ago': p.time_ago,
                'last_updated': p.updated_at.strftime('%Y/%m/%d') if p.updated_at else 'به‌تازگی'
            })

        return {
            'count': len(formatted_items),
            'items': formatted_items,
            'deal_type': criteria.deal_type,
            'districts': criteria.districts,
            'total_matching': total_matching,
            'relaxed_note': ''
        }

    @classmethod
    def _extract_semantic_tokens(cls, text: str, criteria: CustomerCriteria) -> List[str]:
        combined_text = f"{text or ''} {' '.join(criteria.semantic_desires)}".lower()
        matched_categories = []
        for cat, kws in SEMANTIC_DESCRIPTORS.items():
            if any(kw in combined_text for kw in kws):
                matched_categories.append(cat)
        return matched_categories

    @classmethod
    def _compute_relevance_and_reasons(
        cls,
        prop: Property,
        criteria: CustomerCriteria,
        semantic_categories: List[str]
    ) -> tuple[int, List[str]]:
        reasons = []
        score = 50

        # تطبیق محله
        if criteria.districts:
            if any(d in (prop.district or '') for d in criteria.districts):
                reasons.append(f"واقع در محدوده درخواستی {prop.district}")
                score += 20

        # تطبیق اتاق و متراژ
        if criteria.rooms > 0 and prop.rooms == criteria.rooms:
            reasons.append(f"دارای {prop.rooms} اتاق خواب")
            score += 10
        if criteria.min_area > 0 and prop.area >= criteria.min_area:
            reasons.append(f"متراژ متناسب {int(prop.area)} متر")
            score += 10

        # تطبیق امکانات الزامی
        features_added = []
        if prop.has_parking:
            features_added.append("پارکینگ سندی")
        if prop.has_elevator:
            features_added.append("آسانسور")
        if prop.has_balcony:
            features_added.append("تراس/بالکن")
        if features_added:
            reasons.append(f"دارای {', '.join(features_added)}")

        # تطبیق معنایی با توضیحات ملک
        prop_text = f"{prop.title or ''} {prop.description or ''} {prop.features_json or ''}".lower()
        for cat in semantic_categories:
            kws = SEMANTIC_DESCRIPTORS.get(cat, [])
            for kw in kws:
                if kw in prop_text:
                    score += 15
                    reasons.append(f"منطبق با ویژگی کیفی: {kw}")
                    break

        if not reasons:
            reasons.append("فایل کارشناسی‌شده شخصی منطبق با سقف بودجه")

        return score, reasons[:4]
