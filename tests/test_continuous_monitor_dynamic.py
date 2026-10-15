import unittest
from unittest.mock import MagicMock
from app import app
from data.tehran_districts import (
    get_region_for_district,
    is_in_target_districts,
    is_in_region_2_or_5
)
from crawler.continuous_monitor import DivarContinuousMonitor
from database.models import Property, Owner

class DummyProperty:
    def __init__(self):
        self.id = 101
        self.title = "آپارتمان ۱۰۰ متری پونک"
        self.deal_type = "rent"
        self.district = "پونک"
        self.city = "تهران"
        self.area = 100
        self.rooms = 2
        self.floor = 3
        self.total_price = 0
        self.deposit = 500_000_000
        self.monthly_rent = 15_000_000
        self.meter_price = 0
        self.source = "divar"
        self.source_url = "https://divar.ir/v/test_ad_123"
        self.file_code = "FL-101"
        self.images = []
        self.images_json = "[]"
        self.owner = None
        self.owner_type = None
        self.property_type = "apartment"
        self.has_parking = True
        self.has_elevator = True
        self.has_warehouse = True
        self.has_balcony = True

class DummyOwner:
    def __init__(self):
        self.id = 55
        self.full_name = "مالک مستقیم محترم"
        self.phone_number = "09121112233"

class TestContinuousMonitorDynamic(unittest.TestCase):
    """
    آزمون‌های خودکار برای ماژول پایش مداوم داینامیک و سیستم اطلاع‌رسانی سقف
    منطبق بر استانداردهای AGENTS.md:
    - فیلتر محله‌های داینامیک برای هر دفتر املاک
    - عدم استفاده از دیتای ماک در پایپ‌لاین اصلی
    - اعتبارسنجی تگ لینک مستقیم <a href="...">لینک آگهی</a>
    - ایمنی ۱۰۰٪ در مواجهه با قطعی یا خطای پیام‌رسان‌ها
    """

    def test_01_get_region_for_district(self):
        """۱. آزمون تشخیص صحیح شماره منطقه شهرداری برای محله‌های مختلف"""
        self.assertEqual(get_region_for_district('پونک'), '5')
        self.assertEqual(get_region_for_district('جنت آباد'), '5')
        self.assertEqual(get_region_for_district('شهران'), '5')
        self.assertEqual(get_region_for_district('سعادت آباد'), '2')
        self.assertEqual(get_region_for_district('شهرک غرب'), '2')
        self.assertEqual(get_region_for_district('نیاوران'), '1')
        self.assertIsNone(get_region_for_district(None))
        self.assertIsNone(get_region_for_district(''))

    def test_02_is_in_target_districts_fallback(self):
        """۲. آزمون رفتار پیش‌فرض (منطقه ۲ و ۵) در صورت خالی بودن محله‌های هدف"""
        self.assertTrue(is_in_target_districts('پونک', '', []))
        self.assertTrue(is_in_target_districts('سعادت آباد', '', None))
        self.assertFalse(is_in_target_districts('نیاوران', '', []))
        self.assertFalse(is_in_target_districts('تهرانپارس', '', None))

    def test_03_is_in_target_districts_custom(self):
        """۳. آزمون فیلتر اختصاصی بر اساس محله‌های هدف دفتر املاک"""
        agency_districts = ['نیاوران', 'فرمانیه', 'کامرانیه']
        # باید نیاوران قبول شود
        self.assertTrue(is_in_target_districts('نیاوران', '', agency_districts))
        self.assertTrue(is_in_target_districts(None, 'آپارتمان لوکس در فرمانیه', agency_districts))
        # پونک که خارج از محله‌های هدف این دفتر است باید رد شود
        self.assertFalse(is_in_target_districts('پونک', 'آپارتمان در پونک', agency_districts))

    def test_04_monitor_status_and_params(self):
        """۴. آزمون دریافت وضعیت و پارامترهای داینامیک مانیتور"""
        monitor = DivarContinuousMonitor()
        status = monitor.get_status()
        self.assertIn('is_running', status)
        self.assertIn('target_district', status)
        self.assertIn('status_message', status)
        self.assertFalse(status['is_running'])

    def test_05_dispatch_notification_safety(self):
        """۵. آزمون ارسال ایمن نوتیفیکیشن بدون کرش در غیاب توکن‌ها"""
        monitor = DivarContinuousMonitor()
        mock_prop = DummyProperty()
        mock_owner = DummyOwner()

        with app.app_context():
            # متد نباید هیچ خطایی پرتاب کند
            try:
                monitor._dispatch_owner_notification(mock_prop, mock_owner)
                executed_safely = True
            except Exception as e:
                executed_safely = False

        self.assertTrue(executed_safely, "Notification dispatch should never crash or throw exceptions")

    def test_06_notification_format_contains_direct_ad_link(self):
        """۶. اعتبارسنجی انطباق پیام‌های تلگرام و بله با قانون ۴.۱ AGENTS.md (لینک آگهی مستقیم)"""
        from telegram_bot.notifier import format_property_telegram_message
        from bale_bot.notifier import format_property_bale_message

        mock_prop = DummyProperty()
        mock_prop.source_url = "https://divar.ir/v/shahr-test-888"

        with app.app_context():
            tg_msg = format_property_telegram_message(mock_prop)
            bale_msg = format_property_bale_message(mock_prop)

        # بررسی وجود تگ <a> با عنوان 'لینک آگهی' طبق AGENTS.md
        self.assertIn('لینک آگهی', tg_msg)
        self.assertIn('https://divar.ir/v/shahr-test-888', tg_msg)
        self.assertIn('<a href="https://divar.ir/v/shahr-test-888">لینک آگهی</a>', tg_msg)

        self.assertIn('لینک آگهی', bale_msg)
        self.assertIn('https://divar.ir/v/shahr-test-888', bale_msg)
        self.assertIn('<a href="https://divar.ir/v/shahr-test-888">لینک آگهی</a>', bale_msg)

if __name__ == '__main__':
    unittest.main()
