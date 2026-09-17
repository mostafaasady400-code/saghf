"""
موتور تطبیق هوشمند منطقه‌ای با تلورانس ۱۰٪ (Regional Property Matching Engine)
جهت غربال‌گری، رتبه‌بندی و گزینش ۳ فایل برتر ملکی متناسب با تقاضای مشتری با رعایت تلورانس ۱۰٪ بودجه و خط‌مشی AGENTS.md
"""

import logging
from typing import List, Dict, Any, Optional
from database.models import PropertyListing, Property, CustomerLead

logger = logging.getLogger(__name__)

class RegionalPropertyMatcher:
    """
    موتور تطبیق فایل‌های منطقه‌ای با پروفایل نیازمندی متقاضی
    """

    @classmethod
    def match_lead(cls, lead: CustomerLead, limit: int = 3) -> List[Dict[str, Any]]:
        """
        جستجو و امتیازدهی بهترین املاک منطقه‌ای برای متقاضی
        """
        deal_type = lead.deal_type or 'rent'
        districts = lead.preferred_districts or []
        max_deposit = lead.max_deposit or 0
        max_rent = lead.max_rent or 0
        max_budget = lead.max_budget or 0
        min_area = lead.min_area or 0
        features = lead.preferred_features or []

        # ۱. استخراج کاندیداها از هر دو جدول PropertyListing و Property
        candidates = []

        # استعلام از PropertyListing
        query_pl = PropertyListing.query.filter_by(deal_type=deal_type)
        listings = query_pl.all()
        for item in listings:
            candidates.append({
                'source_type': 'listing',
                'id': item.id,
                'ad_code': item.ad_code,
                'title': item.title,
                'district': item.district,
                'city': item.city,
                'deposit': item.deposit or 0,
                'monthly_rent': item.monthly_rent or 0,
                'total_price': item.total_price or 0,
                'area': item.area or 0,
                'build_year': item.build_year or 1400,
                'has_elevator': item.has_elevator,
                'has_parking': item.has_parking,
                'has_warehouse': item.has_warehouse,
                'has_balcony': item.has_balcony,
                'phone_number': item.phone_number,
                'images': item.images,
                'source_url': item.source_url or 'https://divar.ir'
            })

        # استعلام از Property (فایلینگ و کراول عمومی)
        query_p = Property.query.filter_by(deal_type=deal_type)
        properties = query_p.all()
        for p in properties:
            candidates.append({
                'source_type': 'property',
                'id': p.id,
                'ad_code': str(p.file_code or p.id),
                'title': p.title,
                'district': p.district,
                'city': p.city,
                'deposit': p.deposit or 0,
                'monthly_rent': p.monthly_rent or 0,
                'total_price': p.total_price or 0,
                'area': p.area or 0,
                'build_year': p.build_year or 1400,
                'has_elevator': p.has_elevator,
                'has_parking': p.has_parking,
                'has_warehouse': p.has_warehouse,
                'has_balcony': p.has_balcony,
                'phone_number': p.owner.phone_number if p.owner else None,
                'images': p.images,
                'source_url': p.source_url or 'https://divar.ir'
            })

        scored_items = []

        # ۲. ارزیابی و اعمال فیلتر تلورانس ۱۰٪ بودجه و ۵٪ متراژ
        for c in candidates:
            # بررسی تلورانس بودجه ۱۰٪
            if deal_type == 'rent':
                if max_deposit > 0 and c['deposit'] > (max_deposit * 1.10):
                    continue
                if max_rent > 0 and c['monthly_rent'] > (max_rent * 1.10):
                    continue
            elif deal_type == 'sale':
                if max_budget > 0 and c['total_price'] > (max_budget * 1.10):
                    continue

            # بررسی تلورانس متراژ ۵٪
            if min_area > 0 and c['area'] < (min_area * 0.95):
                continue

            # ۳. محاسبه امتیاز تطابق (تا ۱۰۰ امتیاز)
            score = 0
            match_reasons = []

            # الف) تطابق محله (تا ۴۰ امتیاز)
            if districts:
                matched_district = False
                for d in districts:
                    if d in (c['district'] or ''):
                        score += 40
                        match_reasons.append(f"انطباق کامل با محله {d}")
                        matched_district = True
                        break
                if not matched_district:
                    score += 5
                    match_reasons.append(f"محدوده مجاور ({c['district']})")
            else:
                score += 25
                match_reasons.append(f"واقع در محدوده {c['district']}")

            # ب) تطابق بودجه (تا ۳۰ امتیاز)
            if deal_type == 'rent':
                if max_deposit > 0 and c['deposit'] <= max_deposit:
                    score += 15
                elif max_deposit > 0:
                    score += 8  # در محدوده تلورانس ۱۰٪
                
                if max_rent > 0 and c['monthly_rent'] <= max_rent:
                    score += 15
                elif max_rent > 0:
                    score += 8
            else:
                if max_budget > 0 and c['total_price'] <= max_budget:
                    score += 30
                elif max_budget > 0:
                    score += 15

            # ج) امکانات الزامی (تا ۲۰ امتیاز)
            features_score = 0
            if 'پارکینگ' in features:
                if c['has_parking']:
                    features_score += 10
                    match_reasons.append("دارای پارکینگ سندی")
            else:
                if c['has_parking']:
                    features_score += 5

            if 'آسانسور' in features:
                if c['has_elevator']:
                    features_score += 10
                    match_reasons.append("دارای آسانسور")
            else:
                if c['has_elevator']:
                    features_score += 5

            score += min(20, features_score)

            # د) نوساز بودن و سال ساخت (تا ۱۰ امتیاز)
            if c['build_year'] and c['build_year'] >= 1400:
                score += 10
                match_reasons.append("نوساز / زیر ۵ سال")
            elif c['build_year'] and c['build_year'] >= 1395:
                score += 6

            c['match_score'] = min(100, score)
            c['match_reasons'] = match_reasons

            # آماده‌سازی لینک معتبر آگهی مطابق قانون AGENTS.md
            raw_url = c['source_url'] or 'https://divar.ir'
            c['ad_link_html'] = f'<a href="{raw_url}" target="_blank" rel="noopener noreferrer" style="color: #fbbf24; font-weight: bold; text-decoration: underline;">لینک آگهی</a>'

            scored_items.append(c)

        # مرتب‌سازی نزولی بر اساس بیشترین امتیاز تطابق
        scored_items.sort(key=lambda x: x['match_score'], reverse=True)

        return scored_items[:limit]

    @classmethod
    def format_recommendation_text(cls, property_item: Dict[str, Any], rank: int = 1) -> str:
        """
        تولید متن تلگرامی و پیام‌رسانی ساختاریافته همراه با برچسب لینک آگهی طبق دستورالعمل
        """
        title = property_item.get('title', 'ملک کارشناسی‌شده')
        ad_code = property_item.get('ad_code', '---')
        district = property_item.get('district', 'منطقه ۵')
        area = property_item.get('area', 0)
        score = property_item.get('match_score', 90)

        dep = property_item.get('deposit', 0)
        rent = property_item.get('monthly_rent', 0)
        price = property_item.get('total_price', 0)

        amenities = []
        if property_item.get('has_parking'): amenities.append('پارکینگ')
        if property_item.get('has_elevator'): amenities.append('آسانسور')
        if property_item.get('has_warehouse'): amenities.append('انباری')
        if property_item.get('has_balcony'): amenities.append('بالکن')

        amenities_str = '، '.join(amenities) if amenities else 'استاندارد'

        # برچسب قیمت
        if price and price > 0:
            price_str = f"💰 قیمت کل: {price / 1_000_000_000:.2f} میلیارد تومان"
        else:
            dep_str = f"{dep // 1_000_000} م.ت" if dep >= 1_000_000 else f"{dep:,}"
            rent_str = f"{rent // 1_000_000} م.ت" if rent >= 1_000_000 else f"{rent:,}"
            price_str = f"💳 ودیعه: {dep_str} | اجاره: {rent_str}"

        contact = property_item.get('phone_number') or 'تماس از طریق دفتر سقف'
        source_url = property_item.get('source_url', 'https://divar.ir')

        msg = (
            f"🏛️ پیشنهاد برتر شماره {rank} (تطابق: {score}٪)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ {title}\n"
            f"🔢 کد فایل: {ad_code}\n"
            f"📍 محدوده: {district}\n"
            f"📐 متراژ: {area} متر | امکانات: {amenities_str}\n"
            f"{price_str}\n"
            f"📞 تماس: {contact}\n"
            f"🌐 <a href=\"{source_url}\" target=\"_blank\">لینک آگهی</a>\n"
        )
        return msg
