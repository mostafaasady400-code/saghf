"""
ماژول پارسر تخصصی BeautifulSoup برای استخراج مشخصات آگهی‌های دیوار
ترکیب هوشمند کلاس‌های DOM دیوار، متادیتاهای JSON-LD و اعمال گیت اعتبارسنجی ۱۰۰٪ مالک شخصی سقف
"""

import re
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from bs4 import BeautifulSoup

from crawler.schemas import (
    NormalizedPropertySchema,
    parse_price,
    parse_area,
    persian_to_english_numbers
)
from crawler.owner_filter import OwnerFilter, extract_phone_number
from crawler.contact_extractor import ContactExtractor


class BeautifulSoupDivarParser:
    """
    پارسر سریع BeautifulSoup با استخراج چندلایه (DOM + JSON-LD Schema)
    مجهز به فیلتر اصالت مالک شخصی سقف و رد قاطع مشاوران املاک
    """

    @classmethod
    def parse_listing_page(
        cls,
        html_content: str,
        page_url: str,
        city: str = "tehran",
        default_deal_type: str = "sale",
        default_property_type: str = "apartment"
    ) -> Optional[NormalizedPropertySchema]:
        """
        پارس یک صفحه آگهی و تبدیل به NormalizedPropertySchema معتبر
        در صورت شناسایی به عنوان مشاور املاک یا عدم اصالت، None برگردانده می‌شود.
        """
        if not html_content or len(html_content) < 100:
            return None

        soup = BeautifulSoup(html_content, "html.parser")

        # ۱. استخراج اطلاعات اولیه از JSON-LD در صورت وجود
        json_ld_data = cls._extract_json_ld(soup)

        # ۲. استخراج عنوان آگهی
        title = ""
        title_elem = soup.find("h1", class_=lambda c: c and "kt-page-title__title" in c)
        if title_elem:
            title = title_elem.get_text(strip=True)
        elif json_ld_data and json_ld_data.get("name"):
            title = json_ld_data.get("name")
        else:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].split("|")[0].split("-")[0].strip()

        if not title:
            return None

        # ۳. استخراج متن توضیحات
        description = ""
        desc_elem = soup.find("p", class_=lambda c: c and "kt-description-row__text" in c)
        if desc_elem:
            description = desc_elem.get_text(strip=True)
        elif json_ld_data and json_ld_data.get("description"):
            description = json_ld_data.get("description")
        else:
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                description = og_desc["content"].strip()

        # ۴. فیلتر قطعی واسطه‌ها و مشاوران املاک طبق بند ۲ اساسنامه سقف
        seller_context = cls._extract_seller_context(soup)
        owner_eval = OwnerFilter.evaluate(
            platform="divar",
            title=title,
            description=description,
            raw_text=seller_context
        )

        if not owner_eval.is_personal:
            # رد قطعی آگهی‌های بنگاهی و مشاور
            return None

        # گیت نهایی بررسی کلیدواژه‌های ممنوعه
        combined_text = f"{title} {description} {seller_context}"
        for forbidden in [
            'املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوران', 'مشاورین',
            'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس', 'کارشناسان', 'کمیسیون',
            'حق الزحمه', 'فایلینگ', 'موارد مشابه', 'همکار تماس نگیرد'
        ]:
            if forbidden in combined_text:
                return None

        # ۵. استخراج مشخصات ساختاری (متراژ، سال ساخت، تعداد اتاق)
        area_val = None
        build_year_val = None
        rooms_val = None

        if json_ld_data:
            floor_size = json_ld_data.get("floorSize", {})
            if isinstance(floor_size, dict) and floor_size.get("value"):
                area_val = parse_area(floor_size.get("value"))
            rooms_raw = json_ld_data.get("numberOfRooms")
            if rooms_raw:
                rooms_val = cls._parse_rooms_text(str(rooms_raw))

        info_rows = soup.find_all("tr", class_=lambda c: c and "kt-group-row__data-row" in c)
        for row in info_rows:
            labels = row.find_all("span", class_=lambda c: c and "kt-group-row-item__title" in c)
            values = row.find_all("td", class_=lambda c: c and "kt-group-row-item" in c)
            for lbl, val in zip(labels, values):
                l_txt = lbl.get_text(strip=True)
                v_txt = val.get_text(strip=True)
                if "متراژ" in l_txt and not area_val:
                    area_val = parse_area(v_txt)
                elif "ساخت" in l_txt and not build_year_val:
                    build_year_val = cls._parse_year(v_txt)
                elif "اتاق" in l_txt and not rooms_val:
                    rooms_val = cls._parse_rooms_text(v_txt)

        # در صورت نبود در جدول، جستجو در کل سطرها
        if not area_val:
            area_match = re.search(r'(\d+)\s*(?:متر|متری)', title + " " + description)
            if area_match:
                area_val = parse_area(area_match.group(1))

        if not area_val or area_val < 10:
            # املاک بدون متراژ معتبر نادیده گرفته می‌شوند
            return None

        # ۶. استخراج قیمت‌ها و طبقه
        total_price = 0
        deposit = 0
        monthly_rent = 0
        meter_price = 0
        floor_val = None
        total_floors_val = None
        deal_type = default_deal_type

        unexpandable_rows = soup.find_all("div", class_=lambda c: c and "kt-unexpandable-row" in c)
        for row in unexpandable_rows:
            title_p = row.find("p", class_=lambda c: c and "kt-unexpandable-row__title" in c)
            val_p = row.find("p", class_=lambda c: c and "kt-unexpandable-row__value" in c)
            if not title_p or not val_p:
                continue
            t_str = title_p.get_text(strip=True)
            v_str = val_p.get_text(strip=True)

            if "قیمت کل" in t_str:
                total_price = parse_price(v_str)
                deal_type = "sale"
            elif "ودیعه" in t_str or "رهن" in t_str:
                deposit = parse_price(v_str)
                deal_type = "rent"
            elif "اجاره" in t_str:
                monthly_rent = parse_price(v_str)
                deal_type = "rent"
            elif "قیمت هر متر" in t_str:
                meter_price = parse_price(v_str)
            elif "طبقه" in t_str:
                floor_val, total_floors_val = cls._parse_floor(v_str)

        # ۷. امکانات (آسانسور، پارکینگ، انباری، بالکن)
        has_elevator = False
        has_parking = False
        has_warehouse = False
        has_balcony = False
        features_list = []

        feature_items = soup.find_all("div", class_=lambda c: c and "kt-group-feature-row__item" in c)
        for item in feature_items:
            f_text = item.get_text(strip=True)
            if "آسانسور" in f_text:
                has_elevator = "ندارد" not in f_text
                if has_elevator:
                    features_list.append("آسانسور")
            elif "پارکینگ" in f_text:
                has_parking = "ندارد" not in f_text
                if has_parking:
                    features_list.append("پارکینگ")
            elif "انباری" in f_text:
                has_warehouse = "ندارد" not in f_text
                if has_warehouse:
                    features_list.append("انباری")
            elif "بالکن" in f_text:
                has_balcony = "ندارد" not in f_text
                if has_balcony:
                    features_list.append("بالکن")

        # بررسی امکانات از متن در صورت خالی بودن
        if "آسانسور" in combined_text and not has_elevator:
            has_elevator = "بدون آسانسور" not in combined_text and "فاقد آسانسور" not in combined_text
        if "پارکینگ" in combined_text and not has_parking:
            has_parking = "بدون پارکینگ" not in combined_text and "فاقد پارکینگ" not in combined_text
        if "انباری" in combined_text and not has_warehouse:
            has_warehouse = "بدون انباری" not in combined_text and "فاقد انباری" not in combined_text
        if "بالکن" in combined_text and not has_balcony:
            has_balcony = "بدون بالکن" not in combined_text and "فاقد بالکن" not in combined_text

        # ۸. استخراج تصاویر
        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src and ("divarcdn.com" in src or "postimage" in src):
                if src not in images and "thumbnail" not in src and "icon" not in src:
                    images.append(src)

        # ۹. استخراج محله
        district = cls._extract_district(soup, combined_text)

        # ۱۰. استخراج شماره تماس مالک از متن یا المان‌ها
        contact_phone = extract_phone_number(combined_text) or ContactExtractor.extract_primary_phone(combined_text, filter_dummy=False)
        if not contact_phone:
            # جستجو در کدهای اسکریپت یا دیتای پنهان
            contact_phone = cls._extract_phone_from_scripts(soup)

        token = page_url.rstrip("/").split("/")[-1]
        source_id = f"divar_{token}"

        # ساخت اسکیما با رعایت فیلدهای الزامی و لینک مستقیم
        schema_dict = {
            "source": "divar",
            "source_id": source_id,
            "source_url": page_url,
            "title": title,
            "deal_type": deal_type,
            "transaction_type": "rent" if deal_type in ("rent", "رهن", "اجاره") else "buy",
            "property_type": default_property_type,
            "city": city,
            "district": district or "تهران",
            "address": f"{city}، {district or 'تهران'}",
            "total_price": total_price,
            "meter_price": meter_price,
            "deposit": deposit,
            "monthly_rent": monthly_rent,
            "area": area_val,
            "rooms": rooms_val or 0,
            "floor": floor_val,
            "total_floors": total_floors_val,
            "build_year": build_year_val,
            "has_elevator": has_elevator,
            "has_parking": has_parking,
            "has_warehouse": has_warehouse,
            "has_balcony": has_balcony,
            "features": features_list,
            "description": description,
            "images": images[:8],
            "status": "raw_crawled",
            "score": 90 if contact_phone else 80,
            "is_personal_owner": True,
            "owner_type": "personal",
            "filter_log": f"استخراج چندترده سلنیوم و بیوتیفول‌سوپ ({owner_eval.status})",
            "owner_info": {
                "name": f"مالک آگهی ({district or city})",
                "phone": contact_phone or "",
                "urgency": "high",
                "flexibility": "معمولی",
                "notes": f'<a href="{page_url}" target="_blank">لینک آگهی</a>'
            }
        }

        return NormalizedPropertySchema(**schema_dict)

    @classmethod
    def _extract_json_ld(cls, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
                if isinstance(data, dict) and data.get("@type") in ("Apartment", "SingleFamilyResidence", "Place", "Product"):
                    return data
            except Exception:
                continue
        return None

    @classmethod
    def _extract_seller_context(cls, soup: BeautifulSoup) -> str:
        parts = []
        for el in soup.find_all(["div", "section", "p", "span"], class_=lambda c: c and any(w in c for w in ["seller", "agent", "agency", "contact"])):
            text = el.get_text(strip=True)
            if text:
                parts.append(text)
        return " ".join(parts)

    @classmethod
    def _extract_district(cls, soup: BeautifulSoup, combined_text: str) -> str:
        # جستجو در بردکرامب
        crumbs = soup.find_all("a", class_=lambda c: c and "kt-breadcrumbs" in c)
        for crumb in reversed(crumbs):
            c_text = crumb.get_text(strip=True)
            if c_text and c_text not in ["دیوار", "تهران", "املاک", "فروش مسکونی", "اجاره مسکونی", "فروش آپارتمان", "اجاره آپارتمان"]:
                return c_text

        # جستجو در متادیتا
        meta_loc = soup.find("meta", property="og:locality")
        if meta_loc and meta_loc.get("content"):
            return meta_loc["content"].strip()

        return "تهران"

    @classmethod
    def _parse_rooms_text(cls, text: str) -> int:
        norm = persian_to_english_numbers(text).lower()
        if "بدون" in norm or "صفر" in norm or "سوئیت" in norm:
            return 0
        if "یک" in norm:
            return 1
        if "دو" in norm:
            return 2
        if "سه" in norm:
            return 3
        if "چهار" in norm:
            return 4
        nums = re.findall(r'\d+', norm)
        return int(nums[0]) if nums else 1

    @classmethod
    def _parse_year(cls, text: str) -> Optional[int]:
        norm = persian_to_english_numbers(text)
        nums = re.findall(r'\d{4}', norm)
        if nums:
            return int(nums[0])
        nums_2 = re.findall(r'\d{1,2}', norm)
        if nums_2:
            return 1403 - int(nums_2[0])
        return None

    @classmethod
    def _parse_floor(cls, text: str) -> Tuple[Optional[int], Optional[int]]:
        norm = persian_to_english_numbers(text)
        if "همکف" in norm:
            return 0, None
        if "زیرهمکف" in norm or "زیرزمین" in norm:
            return -1, None
        parts = re.findall(r'\d+', norm)
        if len(parts) >= 2:
            return int(parts[0]), int(parts[1])
        if len(parts) == 1:
            return int(parts[0]), None
        return None, None

    @classmethod
    def _extract_phone_from_scripts(cls, soup: BeautifulSoup) -> Optional[str]:
        for script in soup.find_all("script"):
            content = script.string or ""
            if "09" in content or "phone" in content:
                match = re.search(r'(09[0-9]{9})', persian_to_english_numbers(content))
                if match:
                    return match.group(1)
        return None
