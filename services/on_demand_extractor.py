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


class LiveExtractionError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def exact_match(item, deal_type, districts, min_area, max_area, max_budget, max_deposit, max_rent):
    from crawler.strict_owner_guard import strict_decision
    if item.is_personal_owner is not True or not strict_decision(item.title, item.description).allowed:
        return False
    if item.deal_type not in (('sale', 'buy') if deal_type == 'sale' else ('rent',)):
        return False
    normalize = lambda value: ''.join((value or '').replace('ي', 'ی').replace('ك', 'ک').split()).replace('\u200c', '')
    if districts and not any(normalize(name) in normalize(item.district) for name in districts):
        return False
    for value, low, high in [(item.area, min_area, max_area),
            (item.total_price if deal_type == 'sale' else item.deposit, None, max_budget if deal_type == 'sale' else max_deposit),
            (item.monthly_rent, None, max_rent if deal_type == 'rent' else None)]:
        if low is not None or high is not None:
            if value is None or value < 0 or (low is not None and value < low) or (high is not None and value > high):
                return False
    return True

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
        max_duration_seconds: float = 6.0,
        report: Optional[Dict[str, Any]] = None
    ) -> List[Property]:
        """
        اجرای استخراج آنلاین در لحظه، اعتبارسنجی مالک و ذخیره بلادرنگ در دیتابیس سقف.
        خروجی: لیست آبجکت‌های مدل Property ذخیره‌شده و آماده ارائه به کاربر
        """
        if deal_type not in ('sale', 'rent'):
            raise ValueError('invalid_deal_type')
        if min_area is not None and max_area is not None and min_area > max_area:
            raise ValueError('invalid_area_range')
        if any(value is not None and value < 0 for value in (min_area, max_area, max_budget, max_deposit, max_rent)):
            raise ValueError('invalid_negative_filter')
        report = report if report is not None else {}
        report.update(source_status='not_started', is_live=False, coverage_status='incomplete')
        category_key = 'rent-apartment' if deal_type == 'rent' else 'buy-apartment'

        # آماده‌سازی محدوده متراژ با انعطاف‌پذیری هوشمند
        calc_min_area = min_area
        calc_max_area = max_area

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
                max_price=max_budget if deal_type == 'sale' else None,
                max_deposit=max_deposit if deal_type == 'rent' else None,
                max_rent=max_rent if deal_type == 'rent' else None,
                max_pages=1
            )
        except Exception as e:
            report.update(source_status='connection_failed', error_type=type(e).__name__)
            logger.warning('instant_extraction_failed:%s', type(e).__name__)
            raise LiveExtractionError('connection_failed') from None

        fetch_report = getattr(crawler, 'last_fetch_report', {})
        if isinstance(fetch_report, dict):
            report.update(fetch_report)
        report['received_count'] = len(extracted_schemas)
        if not extracted_schemas:
            status = report.get('source_status')
            if status in ('not_started', None):
                status = 'empty_unverified'
            report['source_status'] = status
            raise LiveExtractionError(status)
        report.update(source_status='partial', is_live=True)
        extracted_schemas = [item for item in extracted_schemas if exact_match(item, deal_type,
            clean_districts, min_area, max_area, max_budget, max_deposit, max_rent)]

        logger.info(f"[InstantExtractor] تعداد {len(extracted_schemas)} فایل از کراولر زنده واکشی شد.")

        saved_properties: List[Property] = []
        if not extracted_schemas:
            report['matched_count'] = 0
            return saved_properties

        # ذخیره‌سازی بلادرنگ در پایگاه داده
        for schema_item in extracted_schemas:
            try:
                sid = schema_item.source_id
                # کنترل ددوپلیکیشن دیتابیس
                existing = Property.query.filter_by(source_id=sid).first()
                if existing:
                    dedup_engine.mark_seen(sid)
                    report['reused_count'] = report.get('reused_count', 0) + 1
                    if existing not in saved_properties and exact_match(existing, deal_type,
                            clean_districts, min_area, max_area, max_budget, max_deposit, max_rent):
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
                    transaction_type=schema_item.transaction_type or ('buy' if schema_item.deal_type in ('sale', 'buy') else 'rent'),
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
                            total_price=schema_item.total_price,
                            deposit=schema_item.deposit,
                            monthly_rent=schema_item.monthly_rent,
                            area=schema_item.area,
                            rooms=schema_item.rooms,
                            floor=schema_item.floor,
                            build_year=schema_item.build_year,
                            has_elevator=schema_item.has_elevator,
                            has_parking=schema_item.has_parking,
                            has_warehouse=schema_item.has_warehouse,
                            has_balcony=schema_item.has_balcony,
                            images=schema_item.images,
                            is_personal_owner=True,
                            phone_number=owner.phone_number if owner else None
                        )
                        db.session.add(pl)
                except Exception:
                    raise

                db.session.commit()
                dedup_engine.mark_seen(sid)
                saved_properties.append(prop)
                logger.info(f"[InstantExtractor] ✓ ملک با موفقیت ثبت شد: {prop.title} ({prop.district})")

                # تمرکز ۱۰۰٪ روی ذخیره و نمایش در سایت بدون ارسال به ربات‌ها

            except Exception as e:
                db.session.rollback()
                report['persistence_errors'] = report.get('persistence_errors', 0) + 1
                logger.warning('instant_persistence_failed:%s', type(e).__name__)

        report['matched_count'] = len(saved_properties)
        if report.get('persistence_errors') and not saved_properties:
            report['source_status'] = 'persistence_failed'
            raise LiveExtractionError('persistence_failed')
        return saved_properties

instant_extractor = InstantOnDemandExtractor()
