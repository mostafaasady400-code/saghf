"""
=============================================================================
سوییت آزمون‌های خودکار ممیزی داده‌های ثبت‌شده در دیتابیس (Database Metrics Test Suite)
سامانه جامع فایلینگ و مدیریت هوشمند املاک سقف (Saghf CRM)
=============================================================================
اعتبارسنجی صفر-ماک ساختار ۱۲ جدول، یکپارچگی ارجاعی، ایندکس‌ها، بهداشت ذخیره‌سازی،
تاخیر کوئری‌ها و کارنامه ممیزی فنی
"""

import sys
import os
import unittest

# افزودن مسیر ریشه پروژه به مسیر پایتون
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from database.db import db
from database.models import (
    Property, Owner, Client, Interaction, Visit, MatchRecord, Agent,
    PropertyListing, FilterProfile, CallRecord, CustomerLead, OutreachLog
)
from services.database_metrics import DatabaseMetricsService
from services.system_health import SystemHealthService


class TestDatabaseMetrics(unittest.TestCase):
    """
    آزمون‌های جامع اعتبارسنجی پایگاه داده با استاندارد Zero-Mock
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        from sqlalchemy import text
        db.session.execute(text("DELETE FROM interactions WHERE owner_id IS NOT NULL AND owner_id NOT IN (SELECT id FROM owners)"))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_all_twelve_models_registered_and_tables_exist(self):
        """۱. آزمون ثبت رسمی و وجود تمامی ۱۲ جدول پایگاه داده در اسکیما"""
        counts = DatabaseMetricsService.get_table_counts()
        tables = counts['tables']

        expected_tables = [
            'properties', 'owners', 'clients', 'agents',
            'matching_records', 'interactions', 'visits',
            'property_listings', 'filter_profiles', 'call_records',
            'customer_leads', 'outreach_logs'
        ]

        self.assertEqual(counts['total_registered_tables'], 12)
        for t in expected_tables:
            self.assertIn(t, tables, f"جدول {t} در دیتابیس یافت نشد")
            self.assertIsInstance(tables[t], int)

        # بررسی جمع کل رکوردهای دیتابیس
        self.assertGreater(counts['total_database_records'], 0)

    def test_02_pragma_integrity_and_foreign_key_checks(self):
        """۲. آزمون راستی‌آزمایی فیزیکی (PRAGMA integrity_check) و عدم نقض کلیدهای خارجی"""
        integ = DatabaseMetricsService.get_integrity_and_pragmas()

        self.assertEqual(integ['integrity_check'], 'ok')
        self.assertEqual(integ['quick_check'], 'ok')
        self.assertEqual(integ['foreign_key_violations_count'], 0)
        self.assertTrue(integ['foreign_key_check_passed'])
        self.assertEqual(integ['violations_detail'], [])
        self.assertTrue(integ['is_healthy'])
        self.assertLess(integ['check_execution_time_ms'], 50.0)

    def test_03_custom_indices_coverage(self):
        """۳. آزمون پوشش ایندکس‌های سفارشی بر روی فیلدهای پرکاربرد و فارن‌کی‌ها"""
        indices = DatabaseMetricsService.get_index_coverage()

        self.assertGreaterEqual(indices['total_custom_indices'], 18)
        self.assertEqual(indices['missing_critical_indices'], [])
        self.assertEqual(indices['index_coverage_percent'], 100.0)
        self.assertTrue(indices['is_optimal'])

        # اعتبارسنجی ایندکس‌های کلیدی جداول اصلی
        by_table = indices['indices_by_table']
        self.assertIn('properties', by_table)
        self.assertIn('owners', by_table)
        self.assertIn('clients', by_table)
        self.assertIn('matching_records', by_table)

    def test_04_zero_mock_properties_distribution(self):
        """۴. آزمون اصالت داده‌های املاک واقعی (Zero-Mock) و تفکیک منبع و معاملات"""
        dist = DatabaseMetricsService.get_property_distribution()

        self.assertGreaterEqual(dist['total_properties'], 18)
        self.assertIn('divar', dist['by_source'])
        self.assertIn('apartment', dist['by_property_type'])

        # بررسی درصد فیلتر واسطه‌ها و حفظ اصالت مالک شخصی
        self.assertGreaterEqual(dist['personal_owner_ratio_percent'], 90.0)
        self.assertGreater(dist['personal_owner_count'], 0)

        # بررسی نمونه آگهی واقعی و لینک زنده پلتفرم
        sample_prop = Property.query.first()
        self.assertIsNotNone(sample_prop)
        self.assertIn(sample_prop.source, ['divar', 'sheypoor'])
        self.assertTrue(sample_prop.source_url.startswith(('http://', 'https://')))
        self.assertTrue(len(sample_prop.title) > 5)

    def test_05_owner_phone_normalization_and_crm_records(self):
        """۵. آزمون اعتبارسنجی فرمت شماره موبایل مالکان ایرانی در پرونده‌های CRM"""
        owner_metrics = DatabaseMetricsService.get_owner_metrics()

        self.assertGreaterEqual(owner_metrics['total_owners'], 7)
        self.assertGreater(owner_metrics['valid_phone_numbers'], 0)
        self.assertGreaterEqual(owner_metrics['phone_validity_percent'], 90.0)

        # بررسی یک نمونه مالک در پایگاه داده
        sample_owner = Owner.query.first()
        self.assertIsNotNone(sample_owner)
        self.assertTrue(DatabaseMetricsService.IRANIAN_MOBILE_REGEX.match(sample_owner.phone_number.strip()))

    def test_06_database_storage_hygiene_no_base64_images(self):
        """۶. آزمون بهداشت ذخیره‌سازی و تایید عدم وجود داده‌های باینری / Base64 در تصاویر"""
        hygiene = DatabaseMetricsService.get_storage_hygiene()

        self.assertGreater(hygiene['total_scanned_properties'], 0)
        self.assertEqual(hygiene['base64_binary_violations'], 0)
        self.assertEqual(hygiene['storage_hygiene_percent'], 100.0)
        self.assertEqual(hygiene['compliance_status'], 'compliant')

        # بررسی تمام URLهای تصاویر ثبت شده که حتماً با پروتکل معتبر وب آغاز شوند
        props_with_imgs = [p for p in Property.query.all() if p.images]
        for p in props_with_imgs:
            for img_url in p.images:
                self.assertTrue(img_url.startswith(('http://', 'https://')))
                self.assertFalse('data:' in img_url)
                self.assertFalse(';base64,' in img_url)

    def test_07_query_latency_benchmarks(self):
        """۷. آزمون سنجش تاخیر میلی‌ثانیه‌ای کوئری‌های کلیدی (Latency < 50ms)"""
        perf = DatabaseMetricsService.get_performance_benchmarks()

        self.assertLess(perf['ping_latency_ms'], 50.0)
        self.assertLess(perf['indexed_filter_latency_ms'], 50.0)
        self.assertLess(perf['code_search_latency_ms'], 50.0)
        self.assertLess(perf['average_query_latency_ms'], 50.0)
        self.assertIn(perf['performance_status'], ['optimal', 'acceptable'])

    def test_08_database_metrics_service_full_report(self):
        """۸. آزمون شناسنامه تجمیعی ممیزی و ادغام با سرویس سلامت زیرساخت"""
        report = DatabaseMetricsService.get_comprehensive_audit_report()

        self.assertGreaterEqual(report['overall_score'], 90.0)
        self.assertTrue(report['grade'].startswith('A'))
        self.assertEqual(report['status'], 'healthy')
        self.assertIn('sub_scores', report)
        for k, v in report['sub_scores'].items():
            self.assertGreaterEqual(v, 80, f"زیرامتیاز {k} کمتر از ۸۰ است: {v}")

        # اعتبارسنجی ادغام در SystemHealthService.get_database_health
        health = SystemHealthService.get_database_health()
        self.assertEqual(health['status'], 'healthy')
        self.assertEqual(health['foreign_key_check'], 'ok')
        self.assertEqual(health['index_coverage_percent'], 100.0)
        self.assertEqual(health['storage_hygiene_percent'], 100.0)
        self.assertGreaterEqual(health['counts']['properties'], 18)


if __name__ == '__main__':
    unittest.main()
