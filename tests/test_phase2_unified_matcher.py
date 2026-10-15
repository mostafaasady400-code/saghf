"""
آزمون‌های طلایی موتور تطبیق یکپارچه فاز ۲ (Unified Smart Matching Engine)
تست امتیازدهی، تلورانس مالی، محله، امکانات الزامی و یکسان‌سازی خروجی فایل‌های داخلی و کراول‌شده
"""

import unittest
from app import create_app
from database.db import db
from database.models import Property, PropertyListing, CustomerLead, Client
from services.unified_matcher import UnifiedMatcher, MatchCandidate, DemandProfile, _Scorer

class TestPhase2UnifiedMatcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_scorer_rent_budget_tolerance(self):
        """۱. بررسی تلورانس ۱۰ درصدی بودجه رهن و اجاره در Scorer یکپارچه"""
        profile = DemandProfile(
            deal_type='rent',
            districts=['پونک'],
            max_deposit=500_000_000,
            max_rent=20_000_000,
            max_budget=0,
            min_budget=0,
            min_area=80,
            max_area=120,
            features=['پارکینگ']
        )

        # ملک در محدوده دقیق بودجه
        cand_ok = {
            'deal_type': 'rent',
            'deposit': 450_000_000,
            'monthly_rent': 18_000_000,
            'district': 'پونک',
            'area': 90,
            'build_year': 1401,
            'has_parking': True,
            'has_elevator': True,
            'has_warehouse': True
        }
        score, reasons = _Scorer.score(cand_ok, profile)
        self.assertGreaterEqual(score, 70)
        self.assertTrue(any('سقف بودجه' in r for r in reasons))

        # ملک با ودیعه بیشتر از تلورانس ۱۰٪ (باید رد شود score=0)
        cand_over = {
            'deal_type': 'rent',
            'deposit': 560_000_000,  # بیش از 550 میلیون (110%)
            'monthly_rent': 18_000_000,
            'district': 'پونک',
            'area': 90,
            'has_parking': True
        }
        score_over, _ = _Scorer.score(cand_over, profile)
        self.assertEqual(score_over, 0)

    def test_02_scorer_sale_budget_and_negotiation(self):
        """۲. بررسی امتیازدهی خرید و فروش و امتیاز قیمت قابل مذاکره (تا ۵٪ بالاتر)"""
        profile = DemandProfile(
            deal_type='sale',
            districts=['سعادت‌آباد'],
            max_deposit=0,
            max_rent=0,
            max_budget=10_000_000_000,
            min_budget=8_000_000_000,
            min_area=100,
            max_area=150,
            features=[]
        )

        # قیمت نزدیک به بودجه (تا ۵٪ بالاتر - قابل مذاکره)
        cand_negotiable = {
            'deal_type': 'sale',
            'total_price': 10_400_000_000,
            'district': 'سعادت‌آباد',
            'area': 110,
            'build_year': 1400,
            'has_parking': True,
            'has_elevator': True
        }
        score, reasons = _Scorer.score(cand_negotiable, profile)
        self.assertGreaterEqual(score, 50)
        self.assertTrue(any('قابل مذاکره' in r for r in reasons))

    def test_03_scorer_mandatory_amenity_penalty(self):
        """۳. جریمه عدم وجود امکانات الزامی (پارکینگ، آسانسور در طبقات بالا)"""
        profile_parking = DemandProfile(
            deal_type='rent',
            districts=['صادقیه'],
            max_deposit=400_000_000,
            max_rent=15_000_000,
            max_budget=0,
            min_budget=0,
            min_area=70,
            max_area=100,
            features=['پارکینگ'],
            must_parking=True
        )

        cand_without_parking = {
            'deal_type': 'rent',
            'deposit': 350_000_000,
            'monthly_rent': 14_000_000,
            'district': 'صادقیه',
            'area': 80,
            'has_parking': False,
            'has_elevator': True
        }
        cand_with_parking = dict(cand_without_parking, has_parking=True)

        sc_without, _ = _Scorer.score(cand_without_parking, profile_parking)
        sc_with, _ = _Scorer.score(cand_with_parking, profile_parking)
        self.assertGreater(sc_with, sc_without)

    def test_04_unified_matcher_candidate_to_dict_symmetry(self):
        """۴. بررسی صحت فیلدهای خروجی MatchCandidate و وجود تگ معتبر لینک آگهی"""
        candidate = MatchCandidate(
            source_type='listing',
            source_id=101,
            ad_code='DIVAR-9988',
            title='آپارتمان ۷۵ متری پونک',
            district='پونک',
            city='تهران',
            deal_type='rent',
            area=75,
            rooms=2,
            floor=3,
            deposit=300_000_000,
            monthly_rent=12_000_000,
            total_price=0,
            build_year=1398,
            has_parking=True,
            has_elevator=True,
            has_warehouse=True,
            has_balcony=True,
            phone_number='09121112233',
            images=['https://example.com/p1.jpg'],
            source_url='https://divar.ir/v/9988',
            score=85,
            reasons=['تطابق دقیق منطقه: پونک', 'ودیعه و اجاره در سقف بودجه متقاضی']
        )

        d = candidate.to_dict()
        self.assertEqual(d['source_type'], 'listing')
        self.assertEqual(d['ad_code'], 'DIVAR-9988')
        self.assertEqual(d['match_score'], 85)
        self.assertIn('ad_link_html', d)
        self.assertIn('href="https://divar.ir/v/9988"', d['ad_link_html'])
        self.assertIn('لینک آگهی', d['ad_link_html'])

    def test_05_unified_matcher_match_lead_execution(self):
        """۵. آزمون تطبیق یک CustomerLead نمونه از طریق UnifiedMatcher"""
        lead = CustomerLead(
            contact_key='telegram:test_matcher_lead_99',
            full_name='متقاضی تستی آزمون فاز ۲',
            deal_type='rent',
            max_deposit=600_000_000,
            max_rent=25_000_000,
            min_area=70,
            preferred_districts=['پونک', 'جنت‌آباد'],
            active_messenger='telegram'
        )

        results = UnifiedMatcher.match(lead, threshold=40, limit=5)
        self.assertIsInstance(results, list)
        for cand in results:
            self.assertIsInstance(cand, MatchCandidate)
            self.assertGreaterEqual(cand.score, 40)
            self.assertIn(cand.source_type, ['property', 'listing'])
