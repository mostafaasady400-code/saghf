import os
import sys
import unittest

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data.tehran_districts import (
    get_all_tehran_regions, 
    get_divar_slug_for_district, 
    get_district_names,
    find_matched_district
)
from crawler.owner_filter import OwnerFilter
from crawler.schemas import NormalizedPropertySchema

class TestTehranDistrictsAndSharedHousing(unittest.TestCase):

    def test_tehran_districts_catalog(self):
        regions = get_all_tehran_regions()
        self.assertEqual(len(regions), 22, "Should have all 22 municipal regions of Tehran")
        
        # Test specific known regions and neighborhoods
        reg2 = next((r for r in regions if str(r.get('id')) == '2' or r.get('region_id') == 2), None)
        self.assertIsNotNone(reg2)
        sub_names_2 = [s['name'] for s in reg2['sub_districts']]
        self.assertIn("سعادت‌آباد", sub_names_2)
        self.assertIn("شهرک غرب", sub_names_2)

        reg5 = next((r for r in regions if str(r.get('id')) == '5' or r.get('region_id') == 5), None)
        self.assertIsNotNone(reg5)
        sub_names_5 = [s['name'] for s in reg5['sub_districts']]
        self.assertIn("پونک", sub_names_5)
        self.assertIn("جنت‌آباد جنوبی", sub_names_5)

        # Test Divar slug mapping
        self.assertEqual(get_divar_slug_for_district("پونک"), "poonak")
        self.assertEqual(get_divar_slug_for_district("سعادت آباد"), "saadat-abad")
        self.assertEqual(get_divar_slug_for_district("سعادت‌آباد"), "saadat-abad")
        self.assertEqual(get_divar_slug_for_district("نیاوران"), "niavaran")
        self.assertEqual(get_divar_slug_for_district("تهرانپارس غربی"), "west-tehranpars")

        # Test fuzzy / prefix matching
        matched = find_matched_district("آپارتمان شیک در محله پونک شمالی")
        self.assertIsNotNone(matched)
        self.assertEqual(matched, "پونک")

    def test_shared_housing_strict_rejection(self):
        roommate_samples = [
            ("نیازمند همخونه خانم موجه", "یک نفر خانم کارمند جهت همخانه شدن در آپارتمان ۷۵ متری پونک"),
            ("هم‌اتاقی آقا دانشجو", "اتاق مجزا با تمام امکانات جهت اجاره به هم اتاقی آقا"),
            ("پذیرش همخونه", "به یک همخونه بی حاشیه و مرتب نیازمندیم"),
            ("پانسیون و خوابگاه دخترانه", "خوابگاه لوکس دانشجویی با امکانات کامل"),
            ("اجاره اتاق در سعادت آباد", "یک اتاق از آپارتمان ۱۲۰ متری واگذار می‌شود"),
            ("هم خانه میخوام", "منزل مبله با دسترسی عالی مترو نیازمند هم خانه"),
            ("هم اتاقی موجه", "بدون پول پیش فقط شریک در کرایه")
        ]

        for title, desc in roommate_samples:
            res = OwnerFilter.evaluate(
                platform='divar',
                title=title,
                description=desc,
                raw_text=f"{title} {desc}"
            )
            self.assertFalse(res.is_personal, f"Should reject roommate ad: '{title}'")
            self.assertEqual(res.status, 'rejected_shared_housing')
            self.assertIn('همخونه', res.reason)

    def test_genuine_personal_ads_pass(self):
        genuine_samples = [
            ("آپارتمان ۱۰۰ متری ۲ خوابه پونک", "مالک هستم. سند تک برگ شخصی. فول امکانات پارکینگ آسانسور انباری. تخلیه فوری"),
            ("رهن کامل آپارتمان ۸۵ متری در سعادت آباد", "واحد فوق العاده تمیز، تخلیه، مالک مستقیم، مناسب خانواده یا زوج")
        ]

        for title, desc in genuine_samples:
            res = OwnerFilter.evaluate(
                platform='divar',
                title=title,
                description=desc,
                raw_text=f"{title} {desc}"
            )
            self.assertTrue(res.is_personal, f"Should accept genuine owner ad: '{title}'")
            self.assertEqual(res.status, 'approved_personal')

if __name__ == '__main__':
    unittest.main()
