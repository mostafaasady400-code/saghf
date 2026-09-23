"""
تست‌های جامع اعتبارسنجی ۵ گام پیاده‌سازی شده:
۱. سرعت استخراج غیرهمزمان و سقف زمانی
۲. فیلترهای بازه‌ای سن بنا و مبالغ
۳. سیستم جستجوی زنده محله‌ها
۴. حذف باکس لاگ کراولر
۵. عملکرد گوی شناور هوشمند (App Voice Controller, Lead Assistant, Operational Commands)
"""

import unittest
import json
from app import create_app
from database.db import db
from database.models import Property, Owner
from crawler.hybrid_divar import HybridDivarCrawler
from crawler.hybrid_sheypoor import HybridSheypoorCrawler
from services.nlp_extractor import PropertyLeadNLPExtractor

class TestAIOrbAndSpeed(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_01_crawler_speed_and_age_filters(self):
        """گام اول و دوم: بررسی سقف زمانی و پشتیبانی کراولرها از بازه سن بنا"""
        divar = HybridDivarCrawler()
        self.assertEqual(divar.MAX_CRAWL_DURATION, 18)
        self.assertEqual(divar.CONCURRENCY_WORKERS, 6)

        # تست اعتبارسنجی آیتم با سن بنا
        cand = {
            'token': 'test1',
            'title': 'آپارتمان ۸۵ متری پونک شخصی',
            'source_id': 'divar_test1',
            'district': 'پونک',
            'middle_desc': 'شخصی',
            'bottom_desc': 'نوساز',
            'd': {'area': 85, 'build_year': 1400}
        }
        post_details = {
            'description': 'فایل شخصی تک برگ سند نوساز آماده تحویل',
            'images': [],
            'is_agency_post': False
        }
        category_meta = {'deal_type': 'sale', 'property_type': 'apartment'}

        filters_valid = {'min_age': 1, 'max_age': 5, 'min_area': 80, 'max_area': 100}
        validated = divar._build_validated_item(cand, post_details, category_meta, filters=filters_valid)
        self.assertIsNotNone(validated)
        self.assertEqual(validated.build_year, 1400)

        # اگر سن بنا خارج از محدوده مجاز باشد باید رد شود
        filters_invalid = {'min_age': 10, 'max_age': 20}
        out_of_range = divar._build_validated_item(cand, post_details, category_meta, filters=filters_invalid)
        self.assertIsNone(out_of_range)

    def test_02_crawler_terminal_removed_from_live_html(self):
        """گام چهارم: اطمینان از حذف کامل باکس لاگ کراولر از تمپلیت live.html"""
        res = self.client.get('/crawler/live')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertNotIn('id="crawler-terminal"', html)
        self.assertIn('مانیتورینگ خودکار پس‌زمینه', html)

    def test_03_ai_orb_voice_controller_api(self):
        """گام پنجم (کارکرد ۱): تست کنترل صوتی اپ و نگاشت به فیلترها و استخراج"""
        cmd_payload = {
            'command': 'اجاره در پونک بین ۵۰۰ میلیون تا ۱۰ میلیون برام بیار'
        }
        res = self.client.post(
            '/api/ai-orb/parse-command',
            data=json.dumps(cmd_payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn(data['action'], ['apply_filters', 'agent_results'])
        self.assertEqual(data['deal_type'], 'rent')
        self.assertEqual(data['district'], 'پونک')
        self.assertEqual(data['params']['max_deposit'], 500000000)
        self.assertEqual(data['params']['max_rent'], 10000000)
        self.assertTrue('رهن و اجاره' in data['voice_reply'])

    def test_04_ai_orb_lead_assistant_negotiation(self):
        """گام پنجم (کارکرد ۲): شنود زنده مذاکره، تفکیک برچسب‌ها و ارائه کارت‌های پیشنهادی"""
        transcript_payload = {
            'transcript': 'سلام وقت بخیر، ما دنبال یک واحد رهن و اجاره در پونک یا جنت آباد هستیم، بودجمون تا ۶۰۰ میلیون ودیعه و ۲۰ میلیون اجاره ماهانه هست، حتما آسانسور و پارکینگ داشته باشه'
        }
        res = self.client.post(
            '/api/ai-orb/analyze-lead',
            data=json.dumps(transcript_payload),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIn('criteria', data)
        self.assertIn('tags', data)
        self.assertIn('matches', data)

        # بررسی تفکیک برچسب‌ها
        labels = [t['label'] for t in data['tags']]
        self.assertTrue(any('پونک' in l or 'جنت‌آباد' in l for l in labels))
        self.assertTrue(any('ودیعه' in l for l in labels))

    def test_05_ai_orb_operational_commands(self):
        """گام پنجم (کارکرد ۳): تست فرامین صوتی روتین (ناوبری، کراولر)"""
        # ناوبری
        res_nav = self.client.post(
            '/api/ai-orb/parse-command',
            data=json.dumps({'command': 'برو به اتاق مانیتورینگ کراولر'}),
            content_type='application/json'
        )
        data_nav = res_nav.get_json()
        self.assertTrue(data_nav['success'])
        self.assertEqual(data_nav['action'], 'navigate')
        self.assertEqual(data_nav['url'], '/crawler/live')

        # اجرای کراولر
        res_crawl = self.client.post(
            '/api/ai-orb/parse-command',
            data=json.dumps({'command': 'شروع کراولینگ'}),
            content_type='application/json'
        )
        data_crawl = res_crawl.get_json()
        self.assertTrue(data_crawl['success'])
        self.assertEqual(data_crawl['action'], 'crawler_started')

if __name__ == '__main__':
    unittest.main()
