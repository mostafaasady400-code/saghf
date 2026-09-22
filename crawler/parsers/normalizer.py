"""
Unified Data Normalizer for Saghf Platform.
Converts heterogeneous dictionaries from Divar and Sheypoor into validated,
type-safe NormalizedPropertySchema objects with full error clamping.
Zero-Mock Implementation.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from crawler.schemas import NormalizedPropertySchema, OwnerSchema, parse_price, persian_to_english_numbers

logger = logging.getLogger(__name__)

class UnifiedDataNormalizer:
    """
    موتور نرمال‌سازی و تبدیل داده‌های خام به Schema استاندارد سامانه سقف
    تضمین سلامت فیلدها، پالایش متن‌ها و تطابق کامل با استانداردهای Pydantic V2
    """

    @staticmethod
    def normalize_property(
        raw: Dict[str, Any],
        source: str,
        category_meta: Dict[str, Any],
        city: str = 'تهران'
    ) -> Optional[NormalizedPropertySchema]:
        """
        تبدیل یک رکورد خام استخراج‌شده به ساختار اعتبارسنجی‌شده NormalizedPropertySchema
        """
        try:
            source_id = str(raw.get('source_id') or raw.get('id') or raw.get('token') or '')
            if not source_id:
                return None

            if not source_id.startswith(f"{source}_"):
                source_id = f"{source}_{source_id}"

            title = str(raw.get('title') or '').strip()
            if len(title) < 3:
                return None

            deal_type = raw.get('deal_type') or category_meta.get('deal_type', 'sale')
            prop_type = raw.get('property_type') or category_meta.get('property_type', 'apartment')

            # آدرس و محله
            raw_district = str(raw.get('district') or 'تهران').strip()
            district = raw_district.replace("در ", "").replace("تهران، ", "").strip() or "تهران"
            address = raw.get('address') or f"{city}، {district}"

            # ارقام مالی
            total_price = int(raw.get('total_price') or raw.get('price') or 0)
            meter_price = int(raw.get('meter_price') or 0)
            deposit = int(raw.get('deposit') or 0)
            monthly_rent = int(raw.get('monthly_rent') or 0)

            # ابعاد و مشخصات فیزیکی
            area = int(raw.get('area') or 85)
            area = max(10, min(50000, area))

            rooms = raw.get('rooms')
            if rooms is None:
                rooms = 1
            else:
                rooms = max(0, min(20, int(rooms)))

            floor = int(raw.get('floor') if raw.get('floor') is not None else 1)
            floor = max(-5, min(100, floor))
            total_floors = raw.get('total_floors')
            if total_floors is not None:
                total_floors = max(1, min(150, int(total_floors)))

            build_year = raw.get('build_year')
            if build_year is not None:
                build_year = int(build_year)
                # نرمال‌سازی سال‌های میلادی یا دو رقمی
                if build_year < 100:
                    build_year += 1300
                elif build_year > 1900 and build_year < 2050:
                    build_year -= 621  # تبدیل تخمینی میلادی به شمسی
                build_year = max(1350, min(1405, build_year))
            else:
                build_year = 1400

            # امکانات رفاهی
            has_elevator = bool(raw.get('has_elevator', False))
            has_parking = bool(raw.get('has_parking', False))
            has_warehouse = bool(raw.get('has_warehouse', False))
            has_balcony = bool(raw.get('has_balcony', False))

            features = raw.get('features') or []
            if not isinstance(features, list):
                features = [str(features)]

            description = str(raw.get('description') or '').strip()
            images = raw.get('images') or []
            if not isinstance(images, list):
                images = [str(images)]

            # اطلاعات مالک و فیلتر
            is_personal = bool(raw.get('is_personal_owner', not raw.get('is_agency', False)))
            owner_type = 'personal' if is_personal else 'agency'
            filter_log = str(raw.get('filter_log') or raw.get('agency_reason') or ('شخصی' if is_personal else 'بنگاه')).strip()

            # شماره تماس
            phone_num = str(raw.get('contact_phone') or raw.get('phone') or '').strip()
            owner_info = OwnerSchema(
                name="مالک محترم",
                phone=phone_num,
                urgency="medium",
                flexibility="معمولی"
            )

            source_url = raw.get('source_url') or (
                f"https://divar.ir/v/{source_id.replace('divar_', '')}" if source == 'divar' else
                f"https://www.sheypoor.com/v/{source_id.replace('sheypoor_', '')}.html"
            )

            schema_obj = NormalizedPropertySchema(
                source=source,
                source_id=source_id,
                source_url=source_url,
                title=title,
                deal_type=deal_type,
                property_type=prop_type,
                city=city,
                district=district,
                address=address,
                total_price=total_price,
                meter_price=meter_price,
                deposit=deposit,
                monthly_rent=monthly_rent,
                area=area,
                rooms=rooms,
                floor=floor,
                total_floors=total_floors,
                build_year=build_year,
                has_elevator=has_elevator,
                has_parking=has_parking,
                has_warehouse=has_warehouse,
                has_balcony=has_balcony,
                features=features,
                description=description,
                images=images,
                status=raw.get('status', 'raw_crawled'),
                score=int(raw.get('score', 80)),
                owner_type=owner_type,
                is_personal_owner=is_personal,
                filter_log=filter_log,
                owner_info=owner_info
            )
            return schema_obj

        except Exception as ex:
            logger.warning(f"[UnifiedDataNormalizer] خطا در نرمال‌سازی داده: {ex}")
            return None

    @staticmethod
    def batch_normalize(
        items: List[Dict[str, Any]],
        source: str,
        category_meta: Dict[str, Any],
        city: str = 'تهران'
    ) -> List[NormalizedPropertySchema]:
        """نرمال‌سازی گروهی رکوردهای خام با رد کردن اقلام نامعتبر"""
        normalized_list: List[NormalizedPropertySchema] = []
        for raw in items:
            obj = UnifiedDataNormalizer.normalize_property(raw, source, category_meta, city=city)
            if obj:
                normalized_list.append(obj)
        return normalized_list
