"""
آزمون‌های Fallback امن و اعتبارسنجی کانال دوم در دیسپچر چندکاناله سقف
(Fallback Identity Validation Tests)
"""

import unittest
from unittest.mock import patch
from app import create_app
from database.db import db
from database.models import CustomerLead
from services.omnichannel.dispatcher import omnichannel_dispatcher

class TestPhase2FallbackIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_fallback_skipped_when_no_valid_secondary_identity(self):
        """۱. در صورتی که لید تنها شناسه تلگرام دارد و شماره تماس ندارد، نباید Fallback بی‌هدف به بله انجام شود"""
        lead_tg_only = CustomerLead(
            contact_key='telegram:987654321',
            phone_number=None,
            full_name='کاربر تلگرام بدون شماره',
            active_messenger='telegram'
        )

        item = {
            'id': 8801,
            'ad_code': 'FB-NO-SEC-01',
            'title': 'ملک تستی برای تست فال‌بک',
            'district': 'ونک',
            'area': 90,
            'match_score': 80,
            'source_type': 'property'
        }

        # شبیه‌سازی شکست ارسال در تلگرام
        with patch.object(
            omnichannel_dispatcher.get_adapter('telegram'),
            'send_property_package',
            return_value={'success': False, 'error': 'Network timeout'}
        ):
            with patch.object(
                omnichannel_dispatcher.get_adapter('bale'),
                'send_property_package'
            ) as mock_bale:
                res = omnichannel_dispatcher.dispatch_to_lead(
                    lead=lead_tg_only,
                    property_items=[item],
                    platform='telegram',
                    enable_fallback=True
                )

                # چون کاربر هویت معتبر بله ندارد، نباید به بله متصل شود
                mock_bale.assert_not_called()
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0]['status'], 'failed')

    def test_02_fallback_executed_when_phone_available(self):
        """۲. در صورتی که لید دارای شماره موبایل باشد، فال‌بک به کانال دوم با موفقیت انجام می‌شود"""
        lead_with_phone = CustomerLead(
            contact_key='09127778899',
            phone_number='09127778899',
            full_name='کاربر دارای موبایل',
            active_messenger='telegram'
        )

        item = {
            'id': 8802,
            'ad_code': 'FB-WITH-PHONE-02',
            'title': 'ملک تستی فال‌بک با شماره',
            'district': 'ونک',
            'area': 90,
            'match_score': 80,
            'source_type': 'property'
        }

        with patch.object(
            omnichannel_dispatcher.get_adapter('telegram'),
            'send_property_package',
            return_value={'success': False, 'error': 'Telegram blocked'}
        ):
            with patch.object(
                omnichannel_dispatcher.get_adapter('bale'),
                'send_property_package',
                return_value={'success': True, 'platform': 'bale'}
            ) as mock_bale:
                res = omnichannel_dispatcher.dispatch_to_lead(
                    lead=lead_with_phone,
                    property_items=[item],
                    platform='telegram',
                    enable_fallback=True
                )

                # باید به بله فال‌بک بزند
                mock_bale.assert_called_once()
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0]['platform'], 'bale')
                self.assertEqual(res[0]['status'], 'sent')
