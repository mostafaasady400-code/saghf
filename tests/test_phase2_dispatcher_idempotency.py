"""
آزمون‌های عدم تکرار و اصالت لاگ دیسپچر چندکاناله (Dispatcher Idempotency & OutreachLog Tests)
تضمین عدم ارسال دوگانه در اثر وب‌هوک تکراری و مدیریت صحیح کلیدهای Idempotency
"""

import unittest
from unittest.mock import patch
from app import create_app
from database.db import db
from database.models import CustomerLead, OutreachLog
from services.omnichannel.dispatcher import omnichannel_dispatcher

class TestPhase2DispatcherIdempotency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

        # ساخت لید آزمایشی
        lead = CustomerLead.query.filter_by(contact_key='test_idem_lead_01').first()
        if not lead:
            lead = CustomerLead(
                contact_key='test_idem_lead_01',
                phone_number='09120000001',
                full_name='متقاضی آزمون آیدم‌پوتنسی',
                active_messenger='telegram'
            )
            db.session.add(lead)
            db.session.commit()
        cls.test_lead = lead

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_idempotency_key_generation(self):
        """۱. آزمون تولید کلید هش یکتا برای جلوگیری از ارسال تکراری"""
        k1 = omnichannel_dispatcher.make_idempotency_key(self.test_lead.id, 'P-1001', 'telegram')
        k2 = omnichannel_dispatcher.make_idempotency_key(self.test_lead.id, 'P-1001', 'telegram')
        k3 = omnichannel_dispatcher.make_idempotency_key(self.test_lead.id, 'P-1002', 'telegram')

        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertEqual(len(k1), 32)

    def test_02_duplicate_dispatch_skipped(self):
        """۲. آزمون عدم ارسال مجدد در صورت ثبت موفق قبلی در همان روز"""
        item = {
            'id': 9991,
            'ad_code': 'TEST-IDEM-99',
            'title': 'ملک تستی برای آیدم‌پوتنسی',
            'district': 'پونک',
            'area': 100,
            'match_score': 90,
            'source_type': 'property'
        }

        with patch.object(
            omnichannel_dispatcher.get_adapter('telegram'),
            'send_property_package',
            return_value={'success': True, 'platform': 'telegram'}
        ):
            # ارسال اول
            res1 = omnichannel_dispatcher.dispatch_to_lead(
                lead=self.test_lead,
                property_items=[item],
                platform='telegram',
                enable_fallback=False
            )
            self.assertEqual(len(res1), 1)
            self.assertEqual(res1[0]['status'], 'sent')

            # بررسی وجود لاگ در OutreachLog
            key = omnichannel_dispatcher.make_idempotency_key(self.test_lead.id, 'TEST-IDEM-99', 'telegram')
            log = OutreachLog.query.filter_by(idempotency_key=key).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, 'sent')
            self.assertEqual(log.delivery_status, 'sent')

            # ارسال دوم با همان مشخصات (باید تکراری تشخیص داده شده و از ارسال مجدد جلوگیری شود)
            res2 = omnichannel_dispatcher.dispatch_to_lead(
                lead=self.test_lead,
                property_items=[item],
                platform='telegram',
                enable_fallback=False
            )
            self.assertEqual(len(res2), 1)
            self.assertTrue(res2[0].get('is_duplicate', False))

            # تعداد رکورد در پایگاه داده نباید دوبرابر شود
            count = OutreachLog.query.filter_by(idempotency_key=key).count()
            self.assertEqual(count, 1)

    def test_03_direct_message_idempotency(self):
        """۳. آزمون Idempotency در متد dispatch_direct_message"""
        msg = "پیام تستی اختصاصی با کلید کنترل تکرار"
        custom_key = "test_custom_direct_key_4455"

        with patch.object(
            omnichannel_dispatcher.get_adapter('telegram'),
            'send_text',
            return_value={'success': True, 'platform': 'telegram', 'latency_ms': 10.0}
        ):
            # ارسال اول
            r1 = omnichannel_dispatcher.dispatch_direct_message(
                recipient="09120000001",
                message=msg,
                platform="telegram",
                idempotency_key=custom_key
            )
            self.assertTrue(r1.get('success'))

            # ارسال دوم با همان کلید
            r2 = omnichannel_dispatcher.dispatch_direct_message(
                recipient="09120000001",
                message=msg,
                platform="telegram",
                idempotency_key=custom_key
            )
            self.assertTrue(r2.get('success'))
            self.assertTrue(r2.get('is_duplicate', False))
