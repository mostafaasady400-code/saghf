"""
=============================================================================
سرویس استخراج بلادرنگ و در لحظه سقف (Instant On-Demand Extraction Service)
هدف: اجرای کراولینگ زنده و فوق‌سریع در زمان واقعی استعلام کاربر یا دستیار هوش مصنوعی
استخراج آگهی‌های تازه ثبت‌شده (لحظاتی پیش، دقایقی پیش، ساعتی پیش) متعلق به مالکین واقعی
=============================================================================
"""

import time
import logging
from typing import List, Dict, Any, Optional
from flask import current_app

from database.db import db
from database.models import Property, Owner, PropertyListing
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.dedup import dedup_engine
from crawler.owner_filter import OwnerFilter
from crawler.schemas import NormalizedPropertySchema

logger = logging.getLogger(__name__)

class InstantOnDemandExtractor:
    """
    موتور استخراج زنده و هدفمند بر اساس نیاز لحظه‌ای کاربر
    """

    @classmethod
    def scrape_and_persist_live(
        cls,
        deal_type: str = 'sale',
        districts: Optional[List[str]] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        max_budget: Optional[int] = None,
        max_deposit: Optional[int] = None,
        max_rent: Optional[int] = None,
        limit: int = 5,
        max_duration_seconds: float = 6.0
    ) -> List[Property]:
        """
        اجرای استخراج آنلاین در لحظه، اعتبارسنجی مالک و ذخیره بلادرنگ در دیتابیس سقف.
        خروجی: لیست آبجکت‌های مدل Property ذخیره‌شده و آماده ارائه به کاربر
        """
        category_key = 'rent-apartment' if deal_type == 'rent' else 'buy-apartment'

        # آماده‌سازی محدوده متراژ با انعطاف‌پذیری هوشمند
        calc_min_area = int(min_area * 0.85) if min_area and min_area > 0 else None
        calc_max_area = int(max_area * 1.15) if max_area and max_area > 0 else (int(min_area * 1.25) if min_area and min_area > 0 else None)

        # پاکسازی نام محله‌ها
        clean_districts = []
        if districts:
            for d in districts:
                d_str = (d or '').strip()
                if d_str and d_str not in ['all', 'تهران', 'کل شهر', 'همه']:
                    clean_districts.append(d_str)

        logger.info(f"[InstantExtractor] شروع استخراج درجا: معامله={deal_type}, محله‌ها={clean_districts}, متراژ={calc_min_area}-{calc_max_area}")

        crawler = HybridDivarCrawler(city='tehran')
        # تنظیم سقف زمانی اختصاصی برای استخراج سریع بلادرنگ
        crawler.MAX_CRAWL_DURATION = max_duration_seconds

        extracted_schemas: List[NormalizedPropertySchema] = []
        try:
            extracted_schemas = crawler.fetch_listings(
                category_key=category_key,
                limit=limit,
                districts=clean_districts if clean_districts else None,
                min_area=calc_min_area,
                max_area=calc_max_area,
                max_price=max_budget if (deal_type == 'sale' and max_budget) else None,
                max_deposit=max_deposit if (deal_type == 'rent' and max_deposit) else None,
                max_rent=max_rent if (deal_type == 'rent' and max_rent) else None,
                max_pages=1
            )
        except Exception as e:
            logger.error(f"[InstantExtractor] خطای واکشی آنلاین: {e}", exc_info=True)

        logger.info(f"[InstantExtractor] تعداد {len(extracted_schemas)} فایل از کراولر زنده واکشی شد.")

        saved_properties: List[Property] = []
        if not extracted_schemas:
            return saved_properties

        # ذخیره‌سازی بلادرنگ در پایگاه داده
        for schema_item in extracted_schemas:
            try:
                sid = schema_item.source_id
                # کنترل ددوپلیکیشن دیتابیس
                existing = Property.query.filter_by(source_id=sid).first()
                if existing:
                    dedup_engine.mark_seen(sid)
                    if existing not in saved_properties:
                        saved_properties.append(existing)
                    continue

                # بررسی یا ثبت اطلاعات مالک
                owner = None
                if schema_item.owner_info and schema_item.owner_info.phone:
                    phone = schema_item.owner_info.phone
                    owner = Owner.query.filter_by(phone_number=phone).first()
                    if not owner:
                        owner = Owner(
                            full_name=schema_item.owner_info.name or "مالک محترم",
                            phone_number=phone,
                            urgency=schema_item.owner_info.urgency,
                            flexibility=schema_item.owner_info.flexibility,
                            notes=schema_item.owner_info.notes
                        )
                        db.session.add(owner)
                        db.session.flush()

                # ایجاد رکورد اصلی ملک
                prop = Property(
                    source=schema_item.source,
                    source_id=sid,
                    source_url=schema_item.source_url,
                    title=schema_item.title,
                    deal_type=schema_item.deal_type,
                    property_type=schema_item.property_type,
                    city=schema_item.city,
                    district=schema_item.district,
                    address=schema_item.address,
                    total_price=schema_item.total_price,
                    meter_price=schema_item.meter_price,
                    deposit=schema_item.deposit,
                    monthly_rent=schema_item.monthly_rent,
                    area=schema_item.area,
                    rooms=schema_item.rooms,
                    floor=schema_item.floor,
                    total_floors=schema_item.total_floors,
                    build_year=schema_item.build_year,
                    has_elevator=schema_item.has_elevator,
                    has_parking=schema_item.has_parking,
                    has_warehouse=schema_item.has_warehouse,
                    has_balcony=schema_item.has_balcony,
                    description=schema_item.description,
                    status=schema_item.status,
                    score=schema_item.score or 95,
                    is_personal_owner=True,
                    owner_type='personal',
                    filter_log=schema_item.filter_log or "استخراج بلادرنگ دستیار هوش مصنوعی سقف",
                    owner_id=owner.id if owner else None
                )
                prop.features = schema_item.features
                prop.images = schema_item.images

                db.session.add(prop)

                # ثبت در PropertyListing جهت سازگاری کامل
                try:
                    existing_pl = PropertyListing.query.filter_by(ad_code=str(sid)).first()
                    if not existing_pl:
                        pl = PropertyListing(
                            ad_code=str(sid),
                            source=schema_item.source,
                            source_url=schema_item.source_url,
                            title=schema_item.title,
                            description=schema_item.description,
                            deal_type=schema_item.deal_type,
                            property_type=schema_item.property_type,
                            city=schema_item.city,
                            district=schema_item.district,
                            address=schema_item.address,
                            total_price=schema_item.total_price,
                            meter_price=schema_item.meter_price,
                            deposit=schema_item.deposit,
                            monthly_rent=schema_item.monthly_rent,
                            area=schema_item.area,
                            rooms=schema_item.rooms,
                            floor=schema_item.floor,
                            total_floors=schema_item.total_floors,
                            build_year=schema_item.build_year,
                            has_elevator=schema_item.has_elevator,
                            has_parking=schema_item.has_parking,
                            has_warehouse=schema_item.has_warehouse,
                            has_balcony=schema_item.has_balcony,
                            images=schema_item.images,
                            features=schema_item.features,
                            is_direct_owner=True,
                            owner_phone=owner.phone_number if owner else None,
                            status='active'
                        )
                        db.session.add(pl)
                except Exception:
                    pass

                db.session.commit()
                dedup_engine.mark_seen(sid)
                saved_properties.append(prop)
                logger.info(f"[InstantExtractor] ✓ ملک با موفقیت ثبت شد: {prop.title} ({prop.district})")

                # تقارن سه‌گانه: دیسپچ اعلان به ربات‌ها
                try:
                    from telegram_bot.notifier import send_property_alert
                    send_property_alert(prop)
                except Exception:
                    pass
                try:
                    from bale_bot.notifier import send_property_bale_alert
                    send_property_bale_alert(prop)
                except Exception:
                    pass

            except Exception as e:
                db.session.rollback()
                logger.error(f"[InstantExtractor] خطای ذخیره ملک {schema_item.source_id}: {e}")

        return saved_properties

instant_extractor = InstantOnDemandExtractor()
