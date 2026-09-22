"""
Sheypoor Structured Data Parser for Saghf Platform.
Extracts normalized real estate listings from Sheypoor Schema.org (JSON-LD),
HTML listing cards, and high-resolution CDN images.
Zero-Mock Implementation.
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup
from crawler.schemas import parse_price, persian_to_english_numbers

class SheypoorStructuredParser:
    """
    موتور استخراج ساختاریافته داده‌های آگهی شیپور
    پارس Schema.org / JSON-LD، مشخصات فنی، کارت‌های لیستینگ و ارتقای کیفیت تصاویر CDN
    """

    @staticmethod
    def parse_json_ld(soup_or_html: Any) -> Dict[str, Any]:
        """
        استخراج مشخصات ملکی از اسکریپت‌های استاندارد JSON-LD (Schema.org)
        """
        parsed: Dict[str, Any] = {
            'area': None,
            'rooms': None,
            'district': None,
            'price': 0,
            'meter_price': 0,
            'deposit': 0,
            'monthly_rent': 0,
            'has_parking': False,
            'has_elevator': False,
            'has_warehouse': False,
            'has_balcony': False,
            'title': '',
            'description': ''
        }

        soup = soup_or_html if isinstance(soup_or_html, BeautifulSoup) else BeautifulSoup(str(soup_or_html), 'html.parser')
        scripts = soup.find_all('script', type='application/ld+json')

        for script in scripts:
            try:
                raw_text = script.string or script.text
                if not raw_text:
                    continue
                data = json.loads(raw_text)
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and '@graph' in data:
                    items = data['@graph']
                else:
                    items = [data]

                for item in items:
                    item_type = item.get('@type', '')
                    if any(t in str(item_type) for t in ['Offer', 'Product', 'RealEstateListing', 'SingleFamilyResidence', 'Apartment', 'Place']):
                        # عنوان و توضیحات
                        if item.get('name') and not parsed['title']:
                            parsed['title'] = str(item['name']).strip()
                        if item.get('description') and not parsed['description']:
                            parsed['description'] = str(item['description']).strip()

                        # قیمت کل
                        p_val = item.get('price') or item.get('offers', {}).get('price')
                        if p_val:
                            parsed['price'] = parse_price(p_val)

                        # مشخصات داخلی (itemOffered)
                        item_offered = item.get('itemOffered', {}) or item

                        # متراژ (floorSize)
                        floor_size = item_offered.get('floorSize', {})
                        if isinstance(floor_size, dict):
                            val = floor_size.get('value')
                            if val:
                                m = re.search(r'\d+', persian_to_english_numbers(val))
                                if m:
                                    parsed['area'] = int(m.group(0))
                        elif isinstance(floor_size, (int, float, str)):
                            m = re.search(r'\d+', persian_to_english_numbers(str(floor_size)))
                            if m:
                                parsed['area'] = int(m.group(0))

                        # تعداد اتاق (numberOfRooms)
                        rooms_val = item_offered.get('numberOfRooms')
                        if rooms_val is not None:
                            val_str = persian_to_english_numbers(str(rooms_val))
                            if 'بدون' in str(rooms_val):
                                parsed['rooms'] = 0
                            else:
                                m = re.search(r'\d+', val_str)
                                if m:
                                    parsed['rooms'] = int(m.group(0))

                        # محله و منطقه
                        addr = item_offered.get('address', {})
                        if isinstance(addr, dict):
                            locality = addr.get('addressLocality')
                            if locality:
                                parsed['district'] = locality.strip()

                        # امکانات رفاهی (amenityFeature)
                        amenities = item_offered.get('amenityFeature', [])
                        if isinstance(amenities, list):
                            for am in amenities:
                                name = str(am.get('name', '')).lower()
                                value = am.get('value', True)
                                if value:
                                    if 'parking' in name or 'پارکینگ' in name:
                                        parsed['has_parking'] = True
                                    elif 'elevator' in name or 'آسانسور' in name:
                                        parsed['has_elevator'] = True
                                    elif 'storage' in name or 'انباری' in name:
                                        parsed['has_warehouse'] = True
                                    elif 'balcony' in name or 'بالکن' in name or 'تراس' in name:
                                        parsed['has_balcony'] = True

                        # قیمت هر متر یا ودیعه و اجاره (additionalProperty)
                        add_props = item_offered.get('additionalProperty', [])
                        if isinstance(add_props, list):
                            for prop in add_props:
                                p_name = str(prop.get('name', ''))
                                p_val_sub = prop.get('value', '')
                                if 'Price per' in p_name or 'قیمت هر متر' in p_name:
                                    parsed['meter_price'] = parse_price(p_val_sub)
                                elif 'ودیعه' in p_name or 'رهن' in p_name:
                                    parsed['deposit'] = parse_price(p_val_sub)
                                elif 'اجاره' in p_name:
                                    parsed['monthly_rent'] = parse_price(p_val_sub)

            except Exception:
                continue

        return parsed

    @staticmethod
    def extract_and_upscale_images(soup_or_html: Any) -> List[str]:
        """
        استخراج تمامی تصاویر معتبر آگهی از CDN شیپور و تبدیل به کیفیت ماکسیمم (۸۰۰x۸۰۰ یا اصلی)
        """
        soup = soup_or_html if isinstance(soup_or_html, BeautifulSoup) else BeautifulSoup(str(soup_or_html), 'html.parser')
        images: List[str] = []

        for img in soup.find_all('img'):
            for attr in ['src', 'data-src', 'data-srcset']:
                val = img.get(attr) or ''
                for u in str(val).split():
                    if 'sheypoor.com' in u and any(ext in u.lower() for ext in ['.jpg', '.jpeg', '.webp', '.png']):
                        # حذف بنرها، آواتارها و لوگوهای سیستمی
                        if any(term in u.lower() for term in ['logo', 'icon', 'banner', 'avatar', 'profile', 'badge']):
                            continue

                        # ارتقای رزولوشن از ریزعکس به ابعاد بزرگ
                        u_large = (
                            u.replace('/small/', '/large/')
                            .replace('/thumb/', '/large/')
                            .replace('/medium/', '/large/')
                            .replace('225x225_af', '800x800_af')
                            .replace('100x100_af', '800x800_af')
                        )
                        if u_large not in images:
                            images.append(u_large)

        return images

    @staticmethod
    def detect_agency(soup_or_html: Any, full_text: str = "") -> Tuple[bool, str]:
        """
        تشخیص دقیق هویت بنگاه یا مشاور در شیپور
        """
        soup = soup_or_html if isinstance(soup_or_html, BeautifulSoup) else BeautifulSoup(str(soup_or_html), 'html.parser')
        reasons = []

        seller_box = soup.find(class_=re.compile(r'seller|shop|consultant|agency', re.I))
        seller_text = seller_box.get_text(' ', strip=True) if seller_box else ""
        combined = f"{seller_text} {full_text}"

        # پیوندهای اختصاصی پنل‌های فروشگاهی و مشاورین شیپور
        if seller_box and seller_box.find('a', href=re.compile(r'/shops/|/consultant/|/real-estate-agencies/')):
            reasons.append("لینک رسمی آژانس در باکس فروشنده")

        # واژه‌های صنفی در باکس فروشنده یا متن
        for term in ['آژانس املاک', 'دپارتمان املاک', 'دفتر املاک', 'بانک اطلاعات مسکن', 'مشاور املاک', 'مشاورین املاک']:
            if term in combined:
                reasons.append(f"کلیدواژه '{term}'")

        is_agency = len(reasons) > 0
        return is_agency, " / ".join(reasons) if reasons else ""
