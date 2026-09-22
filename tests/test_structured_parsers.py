"""
Comprehensive Unit Tests for Structured Data Parsing & Normalization Architecture.
Zero-Mock Implementation for Saghf Real Estate Platform.
"""

import sys
import os
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from crawler.parsers.divar_parser import DivarStructuredParser
from crawler.parsers.sheypoor_parser import SheypoorStructuredParser
from crawler.parsers.normalizer import UnifiedDataNormalizer
from crawler.schemas import NormalizedPropertySchema


class TestStructuredParsers(unittest.TestCase):
    """
    اعتبارسنجی قابلیت‌های پیشرفته تفکیک ساختاریافته داده‌های دیوار و شیپور:
    - پارس درخت ویجت‌های دیوار
    - پارس اسکریپت‌های Schema.org JSON-LD شیپور
    - ارتقای کیفیت و پالایش تصاویر CDN
    - موتور نرمال‌سازی Pydantic V2 و پاک‌سازی داده‌ها
    - تاب‌آوری در برابر داده‌های ناقص و مخدوش
    """

    def test_01_divar_widget_tree_parsing(self):
        """۱. آزمون استخراج مشخصات از درخت ویجت‌های دیوار"""
        data = {
            "sections": [
                {
                    "widgets": [
                        {"widget_type": "TITLE_ROW", "data": {"title": "آپارتمان ۸۵ متری فردوس"}},
                        {"widget_type": "DESCRIPTION_ROW", "data": {"text": "تخلیه و آماده سکونت مالک هستم"}},
                        {
                            "widget_type": "GROUP_INFO_ROW",
                            "data": {
                                "items": [
                                    {"title": "متراژ", "value": "۸۵"},
                                    {"title": "ساخت", "value": "۱۳۹۹"},
                                    {"title": "اتاق", "value": "۲"}
                                ]
                            }
                        },
                        {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "قیمت کل", "value": "۹٬۵۰۰٬۰۰۰٬۰۰۰ تومان"}},
                        {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "طبقه", "value": "۲ از ۵"}},
                        {
                            "widget_type": "GROUP_FEATURE_ROW",
                            "data": {
                                "items": [
                                    {"title": "آسانسور", "available": True},
                                    {"title": "پارکینگ", "available": True},
                                    {"title": "انباری", "available": True},
                                    {"title": "بالکن", "available": True}
                                ]
                            }
                        },
                        {
                            "widget_type": "IMAGE_CAROUSEL",
                            "data": {
                                "items": [
                                    {"image": {"url": "https://s100.divarcdn.com/static/photo/test1.webp"}},
                                    {"image": {"url": "https://adserver.com/banner.png"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        parsed = DivarStructuredParser.parse_widget_tree(data)
        self.assertEqual(parsed['title'], "آپارتمان ۸۵ متری فردوس")
        self.assertEqual(parsed['area'], 85)
        self.assertEqual(parsed['rooms'], 2)
        self.assertEqual(parsed['build_year'], 1399)
        self.assertEqual(parsed['total_price'], 9_500_000_000)
        self.assertEqual(parsed['floor'], 2)
        self.assertEqual(parsed['total_floors'], 5)
        self.assertTrue(parsed['has_elevator'])
        self.assertTrue(parsed['has_parking'])
        self.assertTrue(parsed['has_warehouse'])
        self.assertTrue(parsed['has_balcony'])
        self.assertEqual(len(parsed['images']), 1)
        self.assertIn("divarcdn.com", parsed['images'][0])

    def test_02_divar_preloaded_state_parsing(self):
        """۲. آزمون استخراج آگهی‌های اولیه از __PRELOADED_STATE__ دیوار"""
        html = """
        <html><body>
        <script>
        window.__PRELOADED_STATE__ = {
            "browse": {
                "postList": [
                    {
                        "data": {
                            "token": "AZ123456",
                            "title": "آپارتمان ۷۰ متری پونک",
                            "district": "پونک",
                            "middle_description_string": "۷۰ متر | ۲ اتاق",
                            "bottom_description_sub_title": "ودیعه ۲۰۰ م | اجاره ۱۰ م"
                        }
                    }
                ]
            }
        };
        </script>
        </body></html>
        """
        items = DivarStructuredParser.parse_preloaded_state(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['token'], "AZ123456")
        self.assertEqual(items[0]['title'], "آپارتمان ۷۰ متری پونک")
        self.assertEqual(items[0]['district'], "پونک")

    def test_03_sheypoor_json_ld_parsing(self):
        """۳. آزمون استخراج مشخصات از اسکریپت‌های Schema.org JSON-LD شیپور"""
        html = """
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Apartment",
                "name": "اجاره واحد ۶۵ متری سعادت‌آباد",
                "description": "تخلیه بدون مالک",
                "price": "500000000",
                "itemOffered": {
                    "floorSize": {"value": "۶۵"},
                    "numberOfRooms": "۱",
                    "address": {"addressLocality": "سعادت‌آباد"},
                    "amenityFeature": [
                        {"name": "Elevator", "value": true},
                        {"name": "Parking", "value": true}
                    ],
                    "additionalProperty": [
                        {"name": "ودیعه", "value": "۵۰۰٬۰۰۰٬۰۰۰"},
                        {"name": "اجاره", "value": "۱۲٬۰۰۰٬۰۰۰"}
                    ]
                }
            }
            </script>
        </head>
        </html>
        """
        parsed = SheypoorStructuredParser.parse_json_ld(html)
        self.assertEqual(parsed['title'], "اجاره واحد ۶۵ متری سعادت‌آباد")
        self.assertEqual(parsed['area'], 65)
        self.assertEqual(parsed['rooms'], 1)
        self.assertEqual(parsed['district'], "سعادت‌آباد")
        self.assertEqual(parsed['deposit'], 500_000_000)
        self.assertEqual(parsed['monthly_rent'], 12_000_000)
        self.assertTrue(parsed['has_elevator'])
        self.assertTrue(parsed['has_parking'])
        self.assertFalse(parsed['has_warehouse'])

    def test_04_sheypoor_image_upscaling(self):
        """۴. آزمون ارتقای رزولوشن و فیلتر تصاویر شیپور"""
        html = """
        <div>
            <img src="https://img.sheypoor.com/small/photos/pic1.jpg" />
            <img src="https://img.sheypoor.com/225x225_af/photos/pic2.webp" />
            <img src="https://img.sheypoor.com/logo/logo.png" />
        </div>
        """
        imgs = SheypoorStructuredParser.extract_and_upscale_images(html)
        self.assertEqual(len(imgs), 2)
        self.assertIn("/large/", imgs[0])
        self.assertIn("800x800_af", imgs[1])

    def test_05_unified_data_normalizer(self):
        """۵. آزمون موتور نرمال‌سازی و تبدیل به NormalizedPropertySchema"""
        raw = {
            'id': 'test_divar_123',
            'title': '  آپارتمان ۹۰ متری طرشت  ',
            'district': 'در طرشت',
            'total_price': 8_100_000_000,
            'meter_price': 90_000_000,
            'area': 90,
            'rooms': 2,
            'floor': 3,
            'build_year': 1400,
            'has_elevator': True,
            'contact_phone': '۰۹۱۲۹۹۸۸۷۷۶',
            'images': ['https://s100.divarcdn.com/static/photo/post.jpg', 'data:image/png;base64,invalid']
        }

        category_meta = {'deal_type': 'sale', 'property_type': 'apartment'}
        schema_obj = UnifiedDataNormalizer.normalize_property(raw, source='divar', category_meta=category_meta)

        self.assertIsNotNone(schema_obj)
        self.assertIsInstance(schema_obj, NormalizedPropertySchema)
        self.assertEqual(schema_obj.source_id, "divar_test_divar_123")
        self.assertEqual(schema_obj.district, "طرشت")
        self.assertEqual(schema_obj.owner_info.phone, "09129988776")
        self.assertEqual(len(schema_obj.images), 1)  # base64 must be filtered out

    def test_06_fault_tolerance_on_malformed_data(self):
        """۶. آزمون تاب‌آوری در برابر داده‌های پوچ، ناقص یا خراب"""
        # داده بدون شناسه
        res1 = UnifiedDataNormalizer.normalize_property({}, source='divar', category_meta={})
        self.assertIsNone(res1)

        # داده با عنوان بسیار کوتاه
        res2 = UnifiedDataNormalizer.normalize_property({'id': '123', 'title': 'a'}, source='divar', category_meta={})
        self.assertIsNone(res2)

        # ارزیابی ویجت خالی
        parsed_empty = DivarStructuredParser.parse_widget_tree({})
        self.assertEqual(parsed_empty['total_price'], 0)
        self.assertEqual(parsed_empty['area'], 85)


if __name__ == '__main__':
    unittest.main()
