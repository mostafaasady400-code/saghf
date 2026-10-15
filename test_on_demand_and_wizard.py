import unittest
import json
from app import create_app
from database.db import db
from database.models import Property
from telegram_bot.bot import (
    _build_start_keyboard,
    _build_wizard_step1_markup,
    _build_wizard_step2_markup,
    _build_wizard_step3_markup,
    _build_wizard_step4_markup,
    _build_wizard_step5_markup,
    wizard_sessions
)
from telegram_bot.notifier import format_property_telegram_message

class TestOnDemandAndWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_01_web_on_demand_search_api(self):
        """تست اندپوینت استخراج درجا وب‌اپ"""
        res = self.client.get('/properties/api/on-demand-search?deal_type=sale&district=پونک')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('status', data)
        self.assertIn('items', data)
        self.assertIn('crawler_running', data)
        print(f"✅ Web On-Demand Search API passed. Status: {data['status']}, Found items: {len(data['items'])}")

    def test_02_web_poll_live_api(self):
        """تست اندپوینت پولینگ زنده"""
        res = self.client.get('/properties/api/poll-live?deal_type=rent')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertIn('items', data)
        print(f"✅ Web Poll Live API passed. Total items returned: {data.get('count')}")

    def test_03_telegram_wizard_keyboards(self):
        """تست ساختار کیبوردهای شیشه‌ای ویزارد در تلگرام"""
        start_kb = _build_start_keyboard()
        first_btn = start_kb.keyboard[0][0]
        self.assertEqual(first_btn.callback_data, 'wiz_start')
        self.assertIn('فیلتر و استخراج', first_btn.text)

        step1_kb = _build_wizard_step1_markup()
        self.assertTrue(any(btn.callback_data == 'wiz_deal_sale' for row in step1_kb.keyboard for btn in row))
        self.assertTrue(any(btn.callback_data == 'wiz_deal_rent' for row in step1_kb.keyboard for btn in row))

        step2_kb = _build_wizard_step2_markup()
        self.assertTrue(any(btn.callback_data == 'wiz_type_apartment' for row in step2_kb.keyboard for btn in row))

        step3_kb = _build_wizard_step3_markup()
        self.assertTrue(any('wiz_dist_پونک' in btn.callback_data for row in step3_kb.keyboard for btn in row))
        self.assertTrue(any(btn.callback_data == 'wiz_dist_custom' for row in step3_kb.keyboard for btn in row))

        step4_kb_sale = _build_wizard_step4_markup('sale')
        self.assertTrue(any('wiz_bud_s' in btn.callback_data for row in step4_kb_sale.keyboard for btn in row))

        step4_kb_rent = _build_wizard_step4_markup('rent')
        self.assertTrue(any('wiz_bud_r' in btn.callback_data for row in step4_kb_rent.keyboard for btn in row))

        step5_kb = _build_wizard_step5_markup()
        self.assertTrue(any(btn.callback_data == 'wiz_exec' for row in step5_kb.keyboard for btn in row))
        print("✅ Telegram wizard inline keyboards 1 to 5 verified successfully.")

    def test_04_telegram_property_message_rule2_compliance(self):
        """تأیید رعایت بند ۲ قوانین AGENTS.md (تگ مستقیم لینک آگهی)"""
        with self.app.app_context():
            prop = Property.query.first()
            if prop:
                msg = format_property_telegram_message(prop)
                self.assertIn('<a href="', msg)
                self.assertIn('>لینک آگهی</a>', msg)
                print(f"✅ AGENTS.md Rule 2 strictly verified in Telegram message: '<a href=\"...\">لینک آگهی</a>' is present.")

if __name__ == '__main__':
    unittest.main()
