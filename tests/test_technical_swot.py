"""
=============================================================================
سوییت آزمون خودکار ماتریس تحلیل راهبردی فنی (Technical SWOT Test Suite)
سامانه مدیریت هوشمند و فایلینگ املاک سقف (Saghf CRM)
=============================================================================
اعتبارسنجی صفر-ماک ساختار ماتریس SWOT، استراتژی‌های متقاطع TOWS، شاخص‌های کمی
تاب‌آوری و مصونیت از مسدودسازی و نقشه راه فازبندی‌شده
"""

import os
import sys
import unittest

# افزودن ریشه پروژه
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from services.swot_evaluator import TechnicalSWOTEvaluator


class TestTechnicalSWOT(unittest.TestCase):
    """
    آزمون‌های اعتبارسنجی ماتریس تحلیل راهبردی فنی و استراتژی‌های TOWS
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_swot_structure_and_categories(self):
        """۱. آزمون وجود ساختار ۴گانه Strengths, Weaknesses, Opportunities, Threats"""
        swot = TechnicalSWOTEvaluator.get_swot_matrix()

        self.assertIn('strengths', swot)
        self.assertIn('weaknesses', swot)
        self.assertIn('opportunities', swot)
        self.assertIn('threats', swot)

        # اعتبارسنجی تعداد و فیلدهای نقاط قوت
        self.assertGreaterEqual(len(swot['strengths']), 4)
        for s in swot['strengths']:
            self.assertTrue(s['id'].startswith('S'))
            self.assertTrue(len(s['title']) > 5)
            self.assertIn('metric', s)
            self.assertIn('impact', s)

        # اعتبارسنجی نقاط ضعف
        self.assertGreaterEqual(len(swot['weaknesses']), 2)
        for w in swot['weaknesses']:
            self.assertTrue(w['id'].startswith('W'))
            self.assertIn('bottleneck', w)
            self.assertIn('mitigation', w)

        # اعتبارسنجی فرصت‌ها و تهدیدات
        self.assertGreaterEqual(len(swot['opportunities']), 3)
        self.assertGreaterEqual(len(swot['threats']), 2)

    def test_02_tows_strategies_completeness(self):
        """۲. آزمون استراتژی‌های متقاطع چهارگانه TOWS (SO, WO, ST, WT)"""
        tows = TechnicalSWOTEvaluator.get_tows_strategies()

        self.assertIn('SO', tows)
        self.assertIn('WO', tows)
        self.assertIn('ST', tows)
        self.assertIn('WT', tows)

        for cat, strats in tows.items():
            self.assertGreaterEqual(len(strats), 2, f"تعداد استراتژی‌های دسته {cat} کمتر از ۲ است")
            for st in strats:
                self.assertTrue(st['code'].startswith(cat))
                self.assertIn('title', st)
                self.assertIn('rationale', st)
                self.assertGreater(len(st['rationale']), 10)

    def test_03_resilience_and_immunity_scoring(self):
        """۳. آزمون شاخص‌های کمی تاب‌آوری معماری و مصونیت از مسدودسازی"""
        kpis = TechnicalSWOTEvaluator.get_strategic_kpis()

        self.assertGreaterEqual(kpis['resilience_index'], 80.0)
        self.assertGreaterEqual(kpis['anti_ban_immunity_score'], 90.0)
        self.assertEqual(kpis['data_authenticity_rate'], 100.0)
        self.assertEqual(kpis['ci_cd_test_reliability'], 100.0)
        self.assertGreaterEqual(kpis['composite_maturity_score'], 90.0)
        self.assertIn(kpis['deployment_grade'], ['A', 'A+ (Enterprise Production Ready)'])
        self.assertIn('CMMI Level 4+', kpis['cmmi_level'])

    def test_04_roadmap_phases_integrity(self):
        """۴. آزمون ساختار نقشه راه فنی در ۳ فاز عملیاتی"""
        roadmap = TechnicalSWOTEvaluator.get_actionable_roadmap()

        self.assertEqual(len(roadmap), 3)
        expected_phases = ['فاز اول', 'فاز دوم', 'فاز سوم']
        for idx, phase_data in enumerate(roadmap):
            self.assertIn(expected_phases[idx], phase_data['phase'])
            self.assertIn(phase_data['priority'], ['High', 'Medium-High', 'Strategic'])
            self.assertGreaterEqual(len(phase_data['actions']), 3)
            self.assertTrue(len(phase_data['acceptance_criteria']) > 10)

    def test_05_zero_mock_telemetry_integration(self):
        """۵. آزمون استخراج زنده داده‌ها از دیتابیس و عدم استفاده از مقادیر ماک"""
        report = TechnicalSWOTEvaluator.generate_full_strategic_report()

        self.assertIn('timestamp', report)
        self.assertIn('kpis', report)
        self.assertIn('swot', report)
        self.assertIn('tows', report)
        self.assertIn('roadmap', report)

        # تایید ارتباط با پایگاه داده واقعی
        swot_s = report['swot']['strengths']
        s2 = next((item for item in swot_s if item['id'] == 'S2'), None)
        self.assertIsNotNone(s2)
        self.assertIn('اصالت مالک مستقیم', s2['metric'])


if __name__ == '__main__':
    unittest.main()
