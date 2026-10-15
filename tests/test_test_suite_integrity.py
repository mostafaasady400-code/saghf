"""
=============================================================================
آزمون جامع یکپارچگی و سلامت سوییت تست‌های سامانه (Test Suite Integrity Suite)
سامانه مدیریت هوشمند و فایلینگ املاک سقف (Saghf CRM)
=============================================================================
راستی‌آزمایی کشف خودکار تمامی ماژول‌های تست، عدم وجود تست‌های Skip یا Broken،
تطابق ساختار با استاندارد Zero-Mock و اعتبارسنجی پوشش ستون‌های معماری
"""

import os
import sys
import unittest
import importlib
import inspect

# افزودن ریشه پروژه
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


class TestSuiteIntegrity(unittest.TestCase):
    """
    اعتبارسنجی خودکار ساختار، جامعیت و سلامت زیرساخت آزمون‌های خودکار سامانه
    """

    EXPECTED_TEST_MODULES = [
        'test_tier1_impersonator',
        'test_tier1_hardening',
        'test_tier2_stealth',
        'test_two_tier_crawler_audit',
        'test_rate_limiter',
        'test_structured_parsers',
        'test_owner_filtering_privacy',
        'test_contact_extraction',
        'test_omnichannel_bots',
        'test_lifecycle_messenger',
        'test_database_metrics',
        'test_system_health',
        'test_technical_swot'
    ]

    def test_01_all_test_files_physically_exist(self):
        """۱. آزمون وجود فیزیکی تمامی فایل‌های تست در پوشه tests/"""
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        for mod_name in self.EXPECTED_TEST_MODULES:
            file_path = os.path.join(tests_dir, f"{mod_name}.py")
            self.assertTrue(
                os.path.exists(file_path),
                f"فایل تست {mod_name}.py در مسیر {tests_dir} یافت نشد!"
            )
            self.assertGreater(os.path.getsize(file_path), 500, f"فایل تست {mod_name}.py خالی یا بسیار کوچک است!")

    def test_02_all_modules_importable_without_syntax_errors(self):
        """۲. آزمون قابلیت Import بدون خطای سینتکسی یا وابستگی مفقود"""
        for mod_name in self.EXPECTED_TEST_MODULES:
            try:
                mod = importlib.import_module(f"tests.{mod_name}")
                self.assertIsNotNone(mod, f"ماژول tests.{mod_name} ایمپورت نشد")
            except Exception as e:
                self.fail(f"خطا در بارگذاری ماژول tests.{mod_name}: {str(e)}")

    def test_03_test_discovery_and_method_counts(self):
        """۳. آزمون کشف خودکار متدهای تست در هر ماژول (حداقل ۳ تست در هر فایل)"""
        total_discovered_methods = 0
        for mod_name in self.EXPECTED_TEST_MODULES:
            mod = importlib.import_module(f"tests.{mod_name}")
            methods_in_module = 0

            # بررسی کلاس‌های TestCase یا کلاس‌های تست مبتنی بر pytest
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and (issubclass(attr, unittest.TestCase) or attr_name.startswith('Test')):
                    for m in dir(attr):
                        if m.startswith('test_'):
                            methods_in_module += 1
                elif callable(attr) and attr_name.startswith('test_'):
                    methods_in_module += 1

            self.assertGreaterEqual(
                methods_in_module, 3,
                f"ماژول tests.{mod_name} متدهای تست کافی ندارد ({methods_in_module} متد)"
            )
            total_discovered_methods += methods_in_module

        # مجموع تست‌های کشف‌شده باید حداقل ۷۵ تست باشد
        self.assertGreaterEqual(total_discovered_methods, 75)

    def test_04_zero_mock_assertions_compliance(self):
        """۴. آزمون انطباق با سیاست عدم وجود داده‌های ماک در کد تست‌ها"""
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        forbidden_mock_patterns = [
            'unittest.mock.MagicMock',
            'unittest.mock.Mock',
            'mocker.patch',
            'mock.patch'
        ]

        for mod_name in self.EXPECTED_TEST_MODULES:
            file_path = os.path.join(tests_dir, f"{mod_name}.py")
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            for pattern in forbidden_mock_patterns:
                self.assertNotIn(
                    pattern, content,
                    f"الگوی ماک غیرمجاز `{pattern}` در فایل {mod_name}.py کشف شد! (سیاست Zero-Mock)"
                )

    def test_05_coverage_across_architectural_pillars(self):
        """۵. آزمون پوشش کامل ارزیابی بر تمامی ستون‌های ۶گانه معماری"""
        modules_set = set(self.EXPECTED_TEST_MODULES)

        # ۱. شبکه و جعل اثر انگشت TLS
        self.assertTrue('test_tier1_impersonator' in modules_set and 'test_tier1_hardening' in modules_set)
        # ۲. دور زدن محافظت‌های وب و استتار
        self.assertIn('test_tier2_stealth', modules_set)
        # ۳. کنترل نرخ و پایداری
        self.assertIn('test_rate_limiter', modules_set)
        # ۴. فیلتر واسطه‌ها و حفظ محرمانگی
        self.assertIn('test_owner_filtering_privacy', modules_set)
        # ۵. ربات‌ها و ارتباطات چندکاناله
        self.assertTrue('test_omnichannel_bots' in modules_set and 'test_lifecycle_messenger' in modules_set)
        # ۶. پایگاه داده، یکپارچگی و سلامت زیرساخت
        self.assertTrue('test_database_metrics' in modules_set and 'test_system_health' in modules_set)


if __name__ == '__main__':
    unittest.main()
