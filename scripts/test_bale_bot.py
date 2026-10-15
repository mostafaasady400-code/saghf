"""
اسکریپت تست و اعتبارسنجی جامع ربات پیام‌رسان بله (Bale Bot Verification Script)
بررسی اتصال، ساختار پیام‌ها، آلارم‌های طلایی/سبز و موتور هوشمند چندکاناله
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from database.db import db
from database.models import Property, Owner, CustomerLead
from config import Config
from bale_bot import (
    get_bale_bot,
    format_property_bale_message,
    send_bale_gold_property_alert,
    send_bale_green_lead_alert
)
from services.bale_auth_service import BaleAuthService
from services.omnichannel_engine import OmniChannelEngine

class TestBaleBotIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_1_bale_bot_connectivity(self):
        """تست اتصال به سرور بله و اعتبار سنجی توکن"""
        bot = get_bale_bot()
        me = bot.get_me()
        print(f"\n✅ ربات بله با موفقیت متصل شد: @{me.username} (ID: {me.id})")
        self.assertEqual(me.username, 'saghf_bot')
        self.assertEqual(me.id, 1375429946)

    def test_2_auth_deep_link(self):
        """تست تولید دیپ‌لینک ورود بله"""
        deep_link = BaleAuthService.get_deep_link("test_token_abc123")
        print(f"🔗 لینک ورود بله: {deep_link}")
        self.assertEqual(deep_link, "https://ble.ir/saghf_bot?start=login_test_token_abc123")

    def test_3_property_message_formatting_and_agents_rule(self):
        """تست قالب‌بندی پیام ملک و رعایت قانون درج <a href>لینک آگهی</a>"""
        prop = Property.query.first()
        self.assertIsNotNone(prop, "حداقل یک ملک باید در دیتابیس وجود داشته باشد")
        msg = format_property_bale_message(prop)
        print(f"\n📝 نمونه پیام فایل ملکی در بله:\n{msg[:150]}...")
        # بررسی خط قرمز AGENTS.md
        self.assertIn('<a href="', msg)
        self.assertIn('لینک آگهی</a>', msg)

    def test_4_gold_and_green_alerts_generation(self):
        """تست ساخت آلارم‌های طلایی و سبز ادمین بله"""
        prop = Property.query.first()
        lead = CustomerLead.query.first()
        # تست با یک چت‌آیدی آزمایشی (بدون خطا حتی اگر ارسال واقعی انجام نشود یا 200 برگرداند)
        gold_res = send_bale_gold_property_alert(prop, target_chat_id="7495565146")
        print(f"🟡 ارسال آلارم طلایی بله: {gold_res}")
        if lead:
            green_res = send_bale_green_lead_alert(lead, target_chat_id="7495565146")
            print(f"🟢 ارسال آلارم سبز بله: {green_res}")

    def test_5_omnichannel_bale_intake(self):
        """تست پردازش خودکار پیام دریافتی از بله در موتور چندکاناله"""
        test_text = "سلام، یک آپارتمان ۱۱۰ متری در پونک با پارکینگ و آسانسور برای فروش به قیمت ۹ میلیارد دارم."
        engine = OmniChannelEngine()
        result = engine.ingest_interaction(
            channel='bale',
            sender_id='09121112233',
            text=test_text,
            metadata={'chat_id': 12345678, 'user_name': 'تست بله'}
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['role'], 'owner')
        print(f"🤖 نتیجه کلاسیفایر هوشمند بله: نقش={result['role']}, کد فایل={result['details']['file_code']}")

if __name__ == '__main__':
    unittest.main(verbosity=2)
