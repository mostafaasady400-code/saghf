"""
موتور تطبیق منطقه‌ای — فاز ۲: Wrapper برای UnifiedMatcher
match_lead به UnifiedMatcher.match delegate می‌کند (یک scorer یکتا).
format_recommendation_text برای فرمت‌بندی پیام پیام‌رسان‌ها باقی می‌ماند.
"""

import logging
from typing import List, Dict, Any
from database.models import CustomerLead
from services.unified_matcher import UnifiedMatcher

logger = logging.getLogger(__name__)

class RegionalPropertyMatcher:
    """
    موتور تطبیق فایل‌های منطقه‌ای با پروفایل نیازمندی متقاضی
    """

    @classmethod
    def match_lead(cls, lead: CustomerLead, limit: int = 3) -> List[Dict[str, Any]]:
        """
        جستجو و امتیازدهی بهترین املاک منطقه‌ای برای متقاضی — مبتنی بر UnifiedMatcher
        """
        client = lead.crm_client if lead.client_id else None
        candidates = UnifiedMatcher.match(client or lead, limit=max(limit, 60))
        items = [c.to_dict() for c in candidates]
        if client:
            def fits(item):
                if 'رهن کامل' in (lead.preferred_features or []) and item.get('monthly_rent') != 0:
                    return False
                for key, minimum in [('rooms', client.min_rooms), ('area', getattr(client, 'min_area', 0))]:
                    if minimum and (item.get(key) is None or item[key] < minimum):
                        return False
                for key, maximum in [('area', client.max_area), ('total_price', getattr(client, 'max_budget', 0)),
                                     ('deposit', getattr(client, 'max_deposit', 0)), ('monthly_rent', getattr(client, 'max_rent', 0))]:
                    if maximum and (item.get(key) is None or item[key] > maximum):
                        return False
                for required, key in [('must_have_parking', 'has_parking'), ('must_have_elevator', 'has_elevator'), ('must_have_warehouse', 'has_warehouse')]:
                    if getattr(client, required, False) and not item.get(key):
                        return False
                return True
            items = [item for item in items if fits(item)]
        return items[:limit]

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
