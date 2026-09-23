import unittest
import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from crawler.schemas import parse_price, sanitize_property_financials, NormalizedPropertySchema
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.hybrid_sheypoor import HybridSheypoorCrawler
from services.scoring_service import PropertyScorer

class TestDeepCrawlScoringFinancials(unittest.TestCase):

    def test_01_persian_price_parsing(self):
        """تست پارس انواع عبارات قیمتی فارسی ترکیبی، اعشاری و ریال"""
        # ۱. ترکیبی میلیارد و میلیون
        self.assertEqual(parse_price('۵ میلیارد و ۳۰۰ میلیون تومان'), 5_300_000_000)
        self.assertEqual(parse_price('۲ میلیارد و ۵۰۰ میلیون'), 2_500_000_000)

        # ۲. اعشاری
        self.assertEqual(parse_price('۵.۵ میلیارد تومان'), 5_500_000_000)
        self.assertEqual(parse_price('۲/۵ میلیارد'), 2_500_000_000)

        # ۳. فرمت با کاما
        self.assertEqual(parse_price('۲۲,۰۰۰,۰۰۰,۰۰۰'), 22_000_000_000)
        self.assertEqual(parse_price('۵،۰۰۰،۰۰۰ تومان'), 5_000_000)

        # ۴. ریال به تومان
        self.assertEqual(parse_price('۵۰,۰۰۰,۰۰۰ ریال'), 5_000_000)
        self.assertEqual(parse_price('۱۰۰ میلیون ریال'), 10_000_000)

        # ۵. عبارات غیرعددی
        self.assertEqual(parse_price('توافقی'), 0)
        self.assertEqual(parse_price('رایگان'), 0)

    def test_02_sanity_check_and_multiplier_fix(self):
        """تست قوانین اعتبارسنجی ارقام رهن/اجاره و حذف باگ ۵۰۰۰ میلیارد"""
        # ۱. اجاره باگ‌دار ۵۰۰۰ میلیارد تومان -> اصلاح به ۵ میلیون تومان
        p, dep, rent = sanitize_property_financials('rent', deposit=500_000_000, monthly_rent=5_000_000_000_000)
        self.assertEqual(rent, 5_000_000)
        self.assertEqual(dep, 500_000_000)

        # ۲. ودیعه باگ‌دار ۱۰۰۰ میلیارد تومان ناشی از ضرب ۱ میلیون در ۱ میلیون -> اصلاح به ۱ میلیون تومان
        p, dep, rent = sanitize_property_financials('rent', deposit=1_000_000_000_000, monthly_rent=20_000_000)
        self.assertEqual(dep, 1_000_000)
        self.assertEqual(rent, 20_000_000)

        # ۳. جابجایی احتمالی رهن و اجاره
        p, dep, rent = sanitize_property_financials('rent', deposit=15_000_000, monthly_rent=600_000_000)
        self.assertEqual(dep, 600_000_000)
        self.assertEqual(rent, 15_000_000)

        # ۴. تفکیک قطعی نوع معامله
        p, dep, rent = sanitize_property_financials('sale', total_price=8_000_000_000, deposit=500_000_000, monthly_rent=10_000_000)
        self.assertEqual(p, 8_000_000_000)
        self.assertEqual(dep, 0)
        self.assertEqual(rent, 0)

        # ۵. خروجی صحیح در Pydantic schema
        schema = NormalizedPropertySchema(
            source='divar',
            source_id='tst999',
            source_url='http://divar.ir/v/999',
            title='آپارتمان ۱۰۰ متری',
            deal_type='rent',
            deposit='۶۰۰ میلیون تومان',
            monthly_rent='۵،۰۰۰،۰۰۰ تومان'
        )
        self.assertIsInstance(schema.deposit, int)
        self.assertIsInstance(schema.monthly_rent, int)
        self.assertEqual(schema.deposit, 600_000_000)
        self.assertEqual(schema.monthly_rent, 5_000_000)

    def test_03_crawler_pagination_parameters(self):
        """تست پارامترهای صفحه‌بندی عمیق و لیمیت‌های جدید کراولرها"""
        divar = HybridDivarCrawler()
        sheypoor = HybridSheypoorCrawler()

        # بررسی سیگنچر متدهای fetch_listings
        import inspect
        d_sig = inspect.signature(divar.fetch_listings)
        s_sig = inspect.signature(sheypoor.fetch_listings)

        self.assertIn('max_pages', d_sig.parameters)
        self.assertEqual(d_sig.parameters['max_pages'].default, 20)
        self.assertGreaterEqual(d_sig.parameters['limit'].default, 50)

        self.assertIn('max_pages', s_sig.parameters)
        self.assertEqual(s_sig.parameters['max_pages'].default, 15)
        self.assertGreaterEqual(s_sig.parameters['limit'].default, 50)

    def test_04_scoring_engine_and_sorting(self):
        """تست موتور امتیازدهی ۰ تا ۱۰۰ و مرتب‌سازی نزولی بر اساس نیاز متقاضی"""
        # فایل ۱: تطابق عالی
        prop_best = {
            'id': 101,
            'deal_type': 'rent',
            'district': 'سعادت آباد',
            'deposit': 500_000_000,
            'monthly_rent': 15_000_000,
            'area': 110,
            'rooms': 2,
            'has_parking': True,
            'has_elevator': True,
            'has_warehouse': True
        }

        # فایل ۲: تطابق متوسط (منطقه متفاوت و بدون پارکینگ)
        prop_mid = {
            'id': 102,
            'deal_type': 'rent',
            'district': 'تهرانپارس',
            'deposit': 450_000_000,
            'monthly_rent': 12_000_000,
            'area': 100,
            'rooms': 2,
            'has_parking': False,
            'has_elevator': True,
            'has_warehouse': False
        }

        # فایل ۳: تطابق ضعیف (قیمت فراتر از بودجه و منطقه متفاوت)
        prop_poor = {
            'id': 103,
            'deal_type': 'rent',
            'district': 'نارمک',
            'deposit': 1_200_000_000,
            'monthly_rent': 40_000_000,
            'area': 70,
            'rooms': 1,
            'has_parking': False,
            'has_elevator': False,
            'has_warehouse': False
        }

        criteria = {
            'deal_type': 'rent',
            'district': 'سعادت آباد',
            'max_deposit': 600_000_000,
            'max_rent': 20_000_000,
            'min_area': 100,
            'rooms': 2,
            'has_parking': '1'
        }

        score_best, _ = PropertyScorer.calculate_match_score(prop_best, criteria)
        score_mid, _ = PropertyScorer.calculate_match_score(prop_mid, criteria)
        score_poor, _ = PropertyScorer.calculate_match_score(prop_poor, criteria)

        self.assertGreater(score_best, 85)
        self.assertGreater(score_best, score_mid)
        self.assertGreater(score_mid, score_poor)

        # تست رتبه‌بندی و سورت نزولی
        items = [prop_poor, prop_mid, prop_best]
        sorted_items = PropertyScorer.sort_properties(items, criteria)

        self.assertEqual(sorted_items[0]['id'], 101)  # بهترین در صدر خروجی
        self.assertEqual(sorted_items[1]['id'], 102)
        self.assertEqual(sorted_items[2]['id'], 103)

if __name__ == '__main__':
    unittest.main()
