"""
آزمون‌های پردازش بازخورد و ارزیابی لیدها بر اساس contact_key و شماره تماس
(Lead Feedback and Contact Key Lookup Tests)
"""

import unittest
from unittest.mock import patch
from app import create_app
from database.db import db
from database.models import CustomerLead, Client
from services.crm_dual_store import DualCRMStore
from services.nurturing_engine import nurturing_engine

class TestPhase2ContactKeyLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

        # ۱. ساخت لید با contact_key پیام‌رسان
        lead_msg, client_msg = DualCRMStore.store_customer_lead({
            'contact_key': 'telegram:lead_fb_test_01',
            'full_name': 'متقاضی فیدبک تلگرام',
            'deal_type': 'rent',
            'active_messenger': 'telegram'
        }, channel='telegram')
        client_msg.lead_status = 'contacted'
        db.session.commit()
        cls.lead_msg = lead_msg

        # ۲. ساخت لید با شماره تماس
        lead_phone, client_phone = DualCRMStore.store_customer_lead({
            'phone': '09129998877',
            'full_name': 'متقاضی فیدبک موبایل',
            'deal_type': 'sale',
            'active_messenger': 'bale'
        }, channel='bale')
        client_phone.lead_status = 'contacted'
        db.session.commit()
        cls.lead_phone = lead_phone

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_feedback_lookup_via_contact_key_positive(self):
        """۱. پردازش بازخورد مثبت با ارسال contact_key تلگرام و ارتقای وضعیت به visiting"""
        with patch('services.omnichannel.telegram_adapter.TelegramAdapter.send_text') as mock_send:
            mock_send.return_value = {'success': True}
            res = nurturing_engine.process_lead_feedback('telegram:lead_fb_test_01', '۱: پسندیدم')

            self.assertTrue(res['success'])
            self.assertEqual(res['action'], 'visit_scheduled')

            # بررسی تغییر وضعیت در Client
            client = db.session.get(Client, self.lead_msg.client_id)
            self.assertEqual(client.lead_status, 'visiting')

    def test_02_feedback_lookup_via_phone_negative(self):
        """۲. پردازش بازخورد متقاضی بر اساس شماره تماس و استخراج موارد جایگزین"""
        with patch('services.omnichannel.bale_adapter.BaleAdapter.send_text') as mock_send:
            mock_send.return_value = {'success': True}
            res = nurturing_engine.process_lead_feedback('09129998877', '۲: متراژ مناسب نبود موارد جدید بفرستید')

            self.assertTrue(res['success'])
            self.assertEqual(res['action'], 'replacements_dispatched')

    def test_03_feedback_http_api_with_contact_key(self):
        """۳. تست ارسال فیدبک به اندپوینت API با استفاده از contact_key"""
        with patch('services.omnichannel.telegram_adapter.TelegramAdapter.send_text') as mock_send:
            mock_send.return_value = {'success': True}
            resp = self.client.post('/api/omnichannel/feedback', json={
                'contact_key': 'telegram:lead_fb_test_01',
                'feedback': '۱: عالیه'
            })
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('success'))
            self.assertEqual(data.get('action'), 'visit_scheduled')
