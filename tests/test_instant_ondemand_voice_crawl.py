import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import create_app
from database.models import db, Property, Owner
from services.voice_ai_engine import voice_ai_pipeline
from services.on_demand_extractor import instant_extractor
from crawler.schemas import NormalizedPropertySchema, OwnerSchema

class TestInstantOnDemandVoiceCrawl(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        self.app_context.pop()

    def test_01_instant_extractor_live_or_mock_integration(self):
        """تست عملکرد پایپلاین استخراج و ذخیره‌سازی بلادرنگ"""
        sample_schema = NormalizedPropertySchema(
            source='divar',
            source_id='divar_test_instant_001',
            source_url='https://divar.ir/v/test_instant_001',
            title='آپارتمان ۸۰ متری شخصی پونک',
            deal_type='rent',
            property_type='apartment',
            city='tehran',
            district='پونک',
            area=80,
            rooms=2,
            deposit=500000000,
            monthly_rent=25000000,
            is_personal_owner=True,
            owner_info=OwnerSchema(name='مالک پونک', phone='09129990001')
        )
        
        with patch('crawler.hybrid_divar.HybridDivarCrawler.fetch_listings', return_value=[sample_schema]):
            props = instant_extractor.scrape_and_persist_live(
                deal_type='rent',
                districts=['پونک'],
                min_area=75,
                max_area=85,
                limit=1,
                max_duration_seconds=3.0
            )
            self.assertGreaterEqual(len(props), 1)
            saved = Property.query.filter_by(source_id='divar_test_instant_001').first()
            self.assertIsNotNone(saved)
            self.assertEqual(saved.area, 80)
            self.assertEqual(saved.district, 'پونک')
            self.assertTrue(saved.is_personal_owner)

    def test_02_voice_ai_turn_instant_crawl_flow(self):
        """تست مکالمه دستیار هوش مصنوعی و استخراج زنده بر اساس متراژ و منطقه"""
        sample_schema = NormalizedPropertySchema(
            source='divar',
            source_id='divar_test_instant_002',
            source_url='https://divar.ir/v/test_instant_002',
            title='اجاره واحد ۸۰ متری پونک عدل شخصی',
            deal_type='rent',
            property_type='apartment',
            city='tehran',
            district='پونک',
            area=80,
            rooms=2,
            deposit=600000000,
            monthly_rent=20000000,
            is_personal_owner=True
        )

        with patch('crawler.hybrid_divar.HybridDivarCrawler.fetch_listings', return_value=[sample_schema]):
            result = voice_ai_pipeline.process_turn(None, "اجاره آپارتمان ۸۰ متری در پونک")
            self.assertTrue(result['success'])
            self.assertEqual(result['intent'], 'lead_discovery')
            self.assertIn('پونک', result['extracted_entities']['districts'])
            self.assertGreaterEqual(len(result['matched_properties']), 1)
            # بررسی اینکه حداقل یکی از املاک منطبق، ملک ۸۰ متری پونک است
            punak_match = any('پونک' in p['district'] for p in result['matched_properties'])
            self.assertTrue(punak_match)

    def test_03_on_demand_search_api_endpoint(self):
        """تست اندپوینت آن‌دیمند سرچ با فیلتر منطقه و متراژ"""
        resp = self.client.get('/properties/api/on-demand-search?deal_type=rent&district=پونک&min_area=70&max_area=90')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn(data.get('status'), ['found', 'ok', 'crawling'])
        self.assertIn('items', data)

    def test_04_ai_voice_search_api_endpoint(self):
        """تست اندپوینت جستجوی هوشمند متنی و صوتی هوش مصنوعی"""
        resp = self.client.post('/properties/api/ai-voice-search', json={
            'query': 'دنبال اجاره آپارتمان ۸۰ متری در پونک هستم'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('items', data)
        self.assertIn('ai_message', data)

if __name__ == '__main__':
    unittest.main()
