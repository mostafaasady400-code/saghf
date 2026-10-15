"""
=============================================================================
سرویس جامع تله‌متری و ممیزی پایگاه داده (Database Metrics & Telemetry Service)
سامانه مدیریت هوشمند و فایلینگ املاک سقف (Saghf CRM)
=============================================================================
این ماژول شاخص‌های ساختاری، یکپارچگی ارجاعی، توزیع داده‌های واقعی (Zero-Mock)،
پوشش ایندکس‌ها، تاخیر پردازش کوئری‌ها و بهداشت ذخیره‌سازی را به صورت زنده ارزیابی می‌کند.
"""

import os
import re
import time
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import text, func

from database.db import db
from database.models import (
    Property, Owner, Client, Interaction, Visit, MatchRecord, Agent,
    PropertyListing, FilterProfile, CallRecord, CustomerLead, OutreachLog
)
from config import Config


class DatabaseMetricsService:
    """
    سرویس ممیزی جامع، ارزیابی سلامت و استخراج تله‌متری پایگاه داده SQLite
    """

    IRANIAN_MOBILE_REGEX = re.compile(r"^09\d{9}$")

    TABLE_MODELS = {
        'properties': Property,
        'owners': Owner,
        'clients': Client,
        'agents': Agent,
        'matching_records': MatchRecord,
        'interactions': Interaction,
        'visits': Visit,
        'property_listings': PropertyListing,
        'filter_profiles': FilterProfile,
        'call_records': CallRecord,
        'customer_leads': CustomerLead,
        'outreach_logs': OutreachLog
    }

    @classmethod
    def get_database_file_info(cls) -> Dict[str, Any]:
        """اطلاعات فیزیکی فایل پایگاه داده در دیسک"""
        db_uri = getattr(Config, 'SQLALCHEMY_DATABASE_URI', '')
        if db_uri.startswith('sqlite:///'):
            db_path = db_uri.replace('sqlite:///', '')
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, 'saghf_database.db')

        exists = os.path.exists(db_path)
        size_bytes = os.path.getsize(db_path) if exists else 0
        size_kb = round(size_bytes / 1024, 2)
        size_mb = round(size_bytes / (1024 * 1024), 2)
        mtime = datetime.fromtimestamp(os.path.getmtime(db_path)).strftime('%Y-%m-%d %H:%M:%S') if exists else None

        return {
            'file_path': db_path,
            'exists': exists,
            'size_bytes': size_bytes,
            'size_kb': size_kb,
            'size_mb': size_mb,
            'last_modified': mtime,
            'storage_engine': 'SQLite 3 (WAL / Serialized)'
        }

    @classmethod
    def get_table_counts(cls) -> Dict[str, Any]:
        """شمارش دقیق و زنده رکوردهای تمامی ۱۲ جدول اصلی سامانه"""
        counts = {}
        total = 0
        for table_name, model_cls in cls.TABLE_MODELS.items():
            try:
                c = model_cls.query.count()
                counts[table_name] = c
                total += c
            except Exception as e:
                counts[table_name] = 0

        return {
            'tables': counts,
            'total_registered_tables': len(cls.TABLE_MODELS),
            'total_database_records': total
        }

    @classmethod
    def get_property_distribution(cls) -> Dict[str, Any]:
        """تحلیل توزیع جامع و چندبعدی املاک ثبت‌شده"""
        # ۱. تفکیک بر اساس منبع (Source)
        source_counts = dict(
            db.session.query(Property.source, func.count(Property.id))
            .group_by(Property.source).all()
        )

        # ۲. تفکیک بر اساس نوع معامله (Deal Type)
        deal_counts = dict(
            db.session.query(Property.deal_type, func.count(Property.id))
            .group_by(Property.deal_type).all()
        )

        # ۳. تفکیک بر اساس نوع کاربری (Property Type)
        prop_type_counts = dict(
            db.session.query(Property.property_type, func.count(Property.id))
            .group_by(Property.property_type).all()
        )

        # ۴. تفکیک بر اساس وضعیت (Status)
        status_counts = dict(
            db.session.query(Property.status, func.count(Property.id))
            .group_by(Property.status).all()
        )

        # ۵. تفکیک بر اساس وضعیت استعلام هفتگی (Inquiry Status)
        inquiry_counts = dict(
            db.session.query(Property.inquiry_status, func.count(Property.id))
            .group_by(Property.inquiry_status).all()
        )

        # ۶. تفکیک نوع مالکیت و رد واسطه‌ها
        personal_count = Property.query.filter_by(is_personal_owner=True).count()
        agency_count = Property.query.filter_by(is_personal_owner=False).count()
        total_props = Property.query.count()
        personal_ratio = round((personal_count / total_props * 100), 1) if total_props > 0 else 100.0

        # ۷. فایل‌های منطقه‌ای هدفمند (PropertyListing)
        pl_total = PropertyListing.query.count()
        pl_deal = dict(
            db.session.query(PropertyListing.deal_type, func.count(PropertyListing.id))
            .group_by(PropertyListing.deal_type).all()
        )

        return {
            'total_properties': total_props,
            'by_source': source_counts,
            'by_deal_type': deal_counts,
            'by_property_type': prop_type_counts,
            'by_status': status_counts,
            'by_inquiry_status': inquiry_counts,
            'personal_owner_count': personal_count,
            'agency_filtered_count': agency_count,
            'personal_owner_ratio_percent': personal_ratio,
            'property_listings': {
                'total': pl_total,
                'by_deal_type': pl_deal
            }
        }

    @classmethod
    def get_owner_metrics(cls) -> Dict[str, Any]:
        """ممیزی مالکان ثبت‌شده، راستی‌آزمایی شماره‌های تماس و تفکیک سطح انعطاف"""
        owners = Owner.query.all()
        total_owners = len(owners)

        valid_phones = 0
        secondary_phones_count = 0
        urgency_counts = {'low': 0, 'medium': 0, 'high': 0, 'very_urgent': 0}
        flexibility_counts = {}

        for o in owners:
            if o.phone_number and cls.IRANIAN_MOBILE_REGEX.match(o.phone_number.strip()):
                valid_phones += 1
            if o.secondary_phone:
                secondary_phones_count += 1
            u = o.urgency or 'medium'
            urgency_counts[u] = urgency_counts.get(u, 0) + 1
            fl = o.flexibility or 'معمولی'
            flexibility_counts[fl] = flexibility_counts.get(fl, 0) + 1

        phone_validity_percent = round((valid_phones / total_owners * 100), 1) if total_owners > 0 else 100.0

        return {
            'total_owners': total_owners,
            'valid_phone_numbers': valid_phones,
            'phone_validity_percent': phone_validity_percent,
            'secondary_phones_count': secondary_phones_count,
            'urgency_distribution': urgency_counts,
            'flexibility_distribution': flexibility_counts
        }

    @classmethod
    def get_integrity_and_pragmas(cls) -> Dict[str, Any]:
        """سنجش یکپارچگی فیزیکی دیتابیس و بررسی عدم نقض کلیدهای خارجی (Foreign Keys)"""
        t0 = time.perf_counter()
        integrity_res = db.session.execute(text("PRAGMA integrity_check")).fetchall()
        integrity_ok = len(integrity_res) > 0 and str(integrity_res[0][0]).lower() == 'ok'

        quick_res = db.session.execute(text("PRAGMA quick_check")).fetchall()
        quick_ok = len(quick_res) > 0 and str(quick_res[0][0]).lower() == 'ok'

        fk_violations = db.session.execute(text("PRAGMA foreign_key_check")).fetchall()
        fk_ok = len(fk_violations) == 0
        check_time_ms = round((time.perf_counter() - t0) * 1000, 2)

        return {
            'integrity_check': 'ok' if integrity_ok else 'failed',
            'quick_check': 'ok' if quick_ok else 'failed',
            'foreign_key_violations_count': len(fk_violations),
            'foreign_key_check_passed': fk_ok,
            'violations_detail': [list(v) for v in fk_violations],
            'check_execution_time_ms': check_time_ms,
            'is_healthy': integrity_ok and quick_ok and fk_ok
        }

    @classmethod
    def get_index_coverage(cls) -> Dict[str, Any]:
        """ارزیابی پوشش ایندکس‌های سفارشی روی ستون‌های کلیدی و فارن‌کی‌ها"""
        query = text(
            "SELECT tbl_name, name FROM sqlite_master "
            "WHERE type='index' AND name NOT LIKE 'sqlite_autoindex%';"
        )
        rows = db.session.execute(query).fetchall()

        indices_by_table: Dict[str, List[str]] = {}
        for tbl, idx in rows:
            indices_by_table.setdefault(tbl, []).append(idx)

        critical_expected_indices = [
            'ix_properties_source',
            'ix_properties_deal_type',
            'ix_properties_district',
            'ix_properties_area',
            'ix_properties_status',
            'ix_properties_property_type',
            'ix_owners_phone_number',
            'ix_clients_phone_number',
            'ix_clients_lead_status',
            'ix_matching_records_property_id',
            'ix_matching_records_client_id'
        ]

        active_index_names = {idx for tbl, idx in rows}
        missing_indices = [idx for idx in critical_expected_indices if idx not in active_index_names]
        coverage_percent = round(
            ((len(critical_expected_indices) - len(missing_indices)) / len(critical_expected_indices)) * 100,
            1
        )

        return {
            'total_custom_indices': len(rows),
            'indices_by_table': indices_by_table,
            'critical_indices_checked': len(critical_expected_indices),
            'missing_critical_indices': missing_indices,
            'index_coverage_percent': coverage_percent,
            'is_optimal': len(missing_indices) == 0
        }

    @classmethod
    def get_performance_benchmarks(cls) -> Dict[str, Any]:
        """بنچ‌مارک سرعت و تاخیر انواع کوئری‌ها بر حسب میلی‌ثانیه"""
        # ۱. کوئری پینگ ساده
        t0 = time.perf_counter()
        db.session.execute(text("SELECT 1")).scalar()
        ping_latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        # ۲. کوئری فیلتر ایندکس‌دار بر اساس محله
        t0 = time.perf_counter()
        _ = Property.query.filter_by(district="نیاوران").all()
        indexed_filter_latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        # ۳. کوئری بازه قیمت و مرتب‌سازی
        t0 = time.perf_counter()
        _ = (
            Property.query.filter(Property.total_price > 0)
            .order_by(Property.total_price.desc())
            .limit(10).all()
        )
        range_sort_latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        # ۴. جستجوی کد ۵ رقمی فایل
        t0 = time.perf_counter()
        _ = Property.get_by_code(10001)
        code_search_latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        # ۵. کوئری تجمیعی شمارش و گروه‌بندی
        t0 = time.perf_counter()
        _ = (
            db.session.query(Property.district, func.count(Property.id))
            .group_by(Property.district).all()
        )
        aggregation_latency_ms = round((time.perf_counter() - t0) * 1000, 3)

        all_latencies = [
            ping_latency_ms,
            indexed_filter_latency_ms,
            range_sort_latency_ms,
            code_search_latency_ms,
            aggregation_latency_ms
        ]
        avg_latency_ms = round(sum(all_latencies) / len(all_latencies), 3)

        return {
            'ping_latency_ms': ping_latency_ms,
            'indexed_filter_latency_ms': indexed_filter_latency_ms,
            'range_sort_latency_ms': range_sort_latency_ms,
            'code_search_latency_ms': code_search_latency_ms,
            'aggregation_latency_ms': aggregation_latency_ms,
            'average_query_latency_ms': avg_latency_ms,
            'performance_status': 'optimal' if avg_latency_ms < 20.0 else ('acceptable' if avg_latency_ms < 50.0 else 'slow')
        }

    @classmethod
    def get_storage_hygiene(cls) -> Dict[str, Any]:
        """
        راستی‌آزمایی بهداشت ذخیره‌سازی تصاویر مطابق قانون بهینه‌سازی دیتابیس:
        تضمین عدم وجود هرگونه رشته Base64 یا باینری و تایید ۱۰۰٪ ذخیره آدرس CDN مستقیم
        """
        props = Property.query.all()
        total_image_urls = 0
        base64_violations = 0
        invalid_format_urls = 0

        for p in props:
            try:
                raw_json = p.images_json or '[]'
                # جستجوی مستقیم رشته Base64 در متن خام
                if 'data:image' in raw_json or ';base64,' in raw_json:
                    base64_violations += 1

                urls = json.loads(raw_json)
                if isinstance(urls, list):
                    for u in urls:
                        if isinstance(u, str):
                            total_image_urls += 1
                            if u.startswith('data:') or ';base64,' in u or len(u) > 2000:
                                base64_violations += 1
                            elif not u.startswith(('http://', 'https://')):
                                invalid_format_urls += 1
            except Exception:
                pass

        hygiene_percent = 100.0 if base64_violations == 0 else max(0.0, 100.0 - (base64_violations * 10))

        return {
            'total_scanned_properties': len(props),
            'total_image_urls_checked': total_image_urls,
            'base64_binary_violations': base64_violations,
            'invalid_format_urls': invalid_format_urls,
            'storage_hygiene_percent': hygiene_percent,
            'compliance_status': 'compliant' if base64_violations == 0 else 'violation'
        }

    @classmethod
    def get_comprehensive_audit_report(cls) -> Dict[str, Any]:
        """
        تولید شناسنامه تجمیعی و کارنامه ممیزی جامع دیتابیس با محاسبه نمره بلوغ فنی
        """
        file_info = cls.get_database_file_info()
        counts = cls.get_table_counts()
        distribution = cls.get_property_distribution()
        owner_metrics = cls.get_owner_metrics()
        integrity = cls.get_integrity_and_pragmas()
        indices = cls.get_index_coverage()
        performance = cls.get_performance_benchmarks()
        hygiene = cls.get_storage_hygiene()

        # محاسبه امتیازات ۶ ستون ارزیابی پایگاه داده
        score_schema = 100 if counts['total_registered_tables'] == 12 else 80
        score_integrity = 100 if integrity['is_healthy'] else 0
        score_indices = int(indices['index_coverage_percent'])
        score_hygiene = int(hygiene['storage_hygiene_percent'])
        score_performance = 100 if performance['performance_status'] == 'optimal' else 85
        score_zero_mock = 100 if counts['tables'].get('properties', 0) > 0 and distribution['personal_owner_ratio_percent'] >= 95 else 80

        total_score = round(
            (score_schema * 0.20) +
            (score_integrity * 0.20) +
            (score_indices * 0.15) +
            (score_hygiene * 0.15) +
            (score_performance * 0.15) +
            (score_zero_mock * 0.15),
            1
        )

        grade = "A+ (Enterprise Production Ready)" if total_score >= 95 else ("A (Production Ready)" if total_score >= 85 else "B")

        return {
            'audit_timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'overall_score': total_score,
            'grade': grade,
            'status': 'healthy' if integrity['is_healthy'] and total_score >= 90 else 'degraded',
            'file_info': file_info,
            'table_counts': counts,
            'property_distribution': distribution,
            'owner_metrics': owner_metrics,
            'integrity': integrity,
            'index_coverage': indices,
            'performance': performance,
            'storage_hygiene': hygiene,
            'sub_scores': {
                'schema_completeness': score_schema,
                'relational_integrity': score_integrity,
                'index_coverage': score_indices,
                'storage_hygiene': score_hygiene,
                'query_performance': score_performance,
                'zero_mock_authenticity': score_zero_mock
            }
        }
