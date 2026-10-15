"""
آزمون‌های یکپارچگی ورودی بات‌ها و پایپ‌لاین OmniChannelEngine
(Bot Ingestion and Namespace Isolation Tests)
"""

import unittest
from app import create_app
from database.db import db
from database.models import CustomerLead, Client
from services.omnichannel_engine import omnichannel_engine

class TestPhase2BotIngest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_telegram_and_bale_same_id_namespace_isolation(self):
        """۱. تضمین عدم تداخل شناسه‌های یکسان در تلگرام و بله با استفاده از فضای نام contact_key"""
        chat_id = "554433221"

        # ۱. رویداد تلگرام
        res_tg = omnichannel_engine.ingest_interaction(
            channel='telegram',
            sender_id=chat_id,
            text='من دنبال آپارتمان اجاره‌ای در منطقه ۵ با ودیعه ۵۰۰ میلیون هستم'
        )
        self.assertTrue(res_tg['success'])
        self.assertEqual(res_tg['sender_id'], f'telegram:{chat_id}')

        lead_tg = CustomerLead.query.filter_by(contact_key=f'telegram:{chat_id}').first()
        self.assertIsNotNone(lead_tg)
        self.assertEqual(lead_tg.source_channel, 'telegram')

        # ۲. رویداد بله با همان شناسه عددی
        res_bale = omnichannel_engine.ingest_interaction(
            channel='bale',
            sender_id=chat_id,
            text='من متقاضی خرید آپارتمان ۱۰۰ متری در سعادت‌آباد با بودجه ۱۰ میلیارد هستم'
        )
        self.assertTrue(res_bale['success'])
        self.assertEqual(res_bale['sender_id'], f'bale:{chat_id}')

        lead_bale = CustomerLead.query.filter_by(contact_key=f'bale:{chat_id}').first()
        self.assertIsNotNone(lead_bale)
        self.assertEqual(lead_bale.source_channel, 'bale')

        # این دو لید باید کاملاً مجزا باشند
        self.assertNotEqual(lead_tg.id, lead_bale.id)

    def test_02_webhook_api_endpoint_ingest(self):
        """۲. آزمون فراخوانی وب‌هوک API چندکاناله از طریق HTTP POST"""
        payload = {
            'chat_id': '88776655',
            'text': 'سلام من مستاجر هستم، آپارتمان دو خوابه پونک می‌خوام',
            'sender_name': 'متقاضی وب‌هوک'
        }

        resp = self.client.post('/api/omnichannel/webhook/telegram', json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('channel'), 'telegram')
        self.assertEqual(data.get('sender_id'), 'telegram:88776655')
