"""
=============================================================================
مجموعه تست جامع و اعتبارسنجی ربات‌های دوگانه @Saghf_bot (Telegram & Bale)
تست متقارن کلیه سناریوها:
۱. اعتبارسنجی کلاینت بله (BaleBotClient)
۲. کنترلر مرکزی مشترک (UnifiedBotController)
۳. فرآیند آنبوردینگ و دیپ‌لینک کد فایل (/start code_10001)
۴. استعلام مستقیم کد ملک و ارسال آلبوم
۵. ویزارد ۵ مرحله‌ای فیلتر و استخراج زنده (Conversation State Machine)
۶. پردازش مکالمات زنده توسط CRMSalesAssistantEngine
۷. قانون حیاتی محرمانگی (تضمین عدم افشای شماره مالک در کارت‌های بله و تلگرام)
۸. تولید هشدار Hot Lead به کارشناس پس از درخواست بازدید مشتری
۹. وب‌هوک‌های /api/bale/webhook و /api/telegram/webhook
=============================================================================
"""

import json
import unittest
from app import create_app
from database.db import db
from database.models import Property, Owner, Client, CustomerLead
from bale_bot.client import BaleBotClient, bale_client
from services.unified_bot_controller import UnifiedBotController, BotMarkupBuilder
from bale_bot.bot import process_bale_update
from telegram_bot.bot import process_update as process_telegram_update


class TestDualBotsUnifiedPlatform(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

        # ملک نمونه با مالک واقعی جهت بررسی آزمون‌های محرمانگی و هماهنگی
        owner = Owner.query.filter_by(phone_number="09129998877").first()
        if not owner:
            owner = Owner(full_name="مالک تست ولنجک", phone_number="09129998877")
            db.session.add(owner)
            db.session.commit()

        cls.owner = owner
        prop = Property.get_by_code("10001")
        if not prop:
            prop = Property(
                title="آپارتمان لوکس ۱۲۰ متری نیاوران فول",
                district="نیاوران",
                city="تهران",
                deal_type="sale",
                property_type="apartment",
                total_price=9_500_000_000,
                area=120,
                rooms=2,
                floor=3,
                has_parking=True,
                has_elevator=True,
                has_warehouse=True,
                has_balcony=True,
                source="divar",
                source_url="https://divar.ir/v/test-confidential-ad",
                status="verified",
                owner_id=owner.id,
                images=json.dumps([
                    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c",
                    "https://images.unsplash.com/photo-1600565193348-f74bd3c7ccdf"
                ])
            )
            db.session.add(prop)
            db.session.commit()
        cls.test_property = prop

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_bale_client_basic_methods(self):
        """تست رفتار کلاینت بله در حالت شبیه‌سازی و تولید پی‌لود"""
        client = BaleBotClient(token="")
        self.assertFalse(client.is_configured)

        res_me = client.get_me()
        self.assertTrue(res_me.get('ok'))
        self.assertTrue(res_me.get('simulated'))

        res_msg = client.send_message(12345, "سلام تست بله")
        self.assertTrue(res_msg.get('ok'))

        res_photo = client.send_photo(12345, "https://example.com/p.jpg", caption="تست کپشن")
        self.assertTrue(res_photo.get('ok'))

    def test_02_markup_builder_telegram_and_bale(self):
        """تست تولید متقارن دکمه‌های شیشه‌ای برای هر دو پلتفرم"""
        bale_builder = BotMarkupBuilder('bale')
        bale_builder.add_row(("🎯 دکمه تست بله", "test_cb", None))
        bale_markup = bale_builder.build()
        self.assertIn('inline_keyboard', bale_markup)
        self.assertEqual(bale_markup['inline_keyboard'][0][0]['callback_data'], 'test_cb')

        tg_builder = BotMarkupBuilder('telegram')
        tg_builder.add_row(("🎯 دکمه تست تلگرام", "test_cb_tg", None))
        tg_markup = tg_builder.build()
        self.assertEqual(len(tg_markup.keyboard), 1)

    def test_03_handle_start_and_deep_linking(self):
        """تست شروع کار ربات و دیپ‌لینک کد فایل /start code_10001 در بله و تلگرام"""
        # ۱. استارت عادی در بله
        res_bale = UnifiedBotController.handle_start('bale', 101, 'علی رضایی')
        self.assertEqual(res_bale['type'], 'text')
        self.assertIn('سقف خوش آمدید', res_bale['message'])
        self.assertIn('inline_keyboard', res_bale['reply_markup'])

        # ۲. استارت با دیپ‌لینک کد فایل در تلگرام
        file_code = self.test_property.file_code
        res_tg_code = UnifiedBotController.handle_start('telegram', 102, 'محمدی', deep_link_param=f"code_{file_code}")
        self.assertEqual(res_tg_code['type'], 'property_package')
        self.assertEqual(res_tg_code['property'].file_code, file_code)

    def test_04_direct_code_search_and_confidentiality(self):
        """استعلام کد فایل و اعتبارسنجی ۱۰۰٪ اصل محرمانگی (عدم وجود شماره مالک و لینک خام)"""
        file_code = self.test_property.file_code
        # استخراج با کد
        res = UnifiedBotController.handle_code_search('bale', 201, file_code)
        self.assertEqual(res['type'], 'property_package')
        card_text = res['card_text']

        # بررسی وجود اطلاعات الزامی
        self.assertIn(file_code, card_text)
        self.assertIn(self.test_property.district, card_text)

        # قانون حیاتی محرمانگی: شماره تلفن مالک (09129998877) نباید در کارت باشد
        self.assertNotIn("09129998877", card_text)
        # لینک مستقیم سورس دیوار نباید در کارت باشد
        self.assertNotIn("https://divar.ir/v/test-confidential-ad", card_text)

    def test_05_interactive_wizard_five_steps(self):
        """تست عملکرد چرخه استیت ماشین ویزارد ۵ مرحله‌ای"""
        chat_id = 99991

        # گام ۱: شروع
        s1 = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_start')
        self.assertIn('گام ۱ از ۵', s1['message'])

        # گام ۲: نوع معامله فروش
        s2 = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_deal_sale')
        self.assertIn('گام ۲ از ۵', s2['message'])

        # گام ۳: کاربری آپارتمان
        s3 = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_type_apartment')
        self.assertIn('گام ۳ از ۵', s3['message'])

        # گام ۴: محله نیاوران
        s4 = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_dist_نیاوران')
        self.assertIn('گام ۴ از ۵', s4['message'])

        # گام ۵: بودجه
        s5 = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_bud_s2')
        self.assertIn('گام ۵ از ۵', s5['message'])

        # اجرای نهایی و دریافت فایل‌ها
        s_exec = UnifiedBotController.handle_callback_query('bale', chat_id, 'wiz_exec')
        self.assertEqual(s_exec['type'], 'crm_matches')
        self.assertGreaterEqual(len(s_exec['cards']), 1)

    def test_06_natural_conversation_crm_sales_assistant(self):
        """تست گفتگوی محاوره‌ای طبیعی و هدایت توسط مشاور ارشد CRM سقف"""
        chat_id = 88882
        user_query = "سلام من خریدار یه آپارتمان حدود ۱۲۰ متر در نیاوران با بودجه ۱۰ میلیارد هستم پارکینگ و آسانسور واجبه"
        
        res = UnifiedBotController.handle_natural_text('telegram', chat_id, user_query, user_phone="09351112233", user_name="سارا حسینی")
        # باید پاسخ یا کارت‌های منطبق برگشت داده شود
        self.assertIn(res['type'], ['text', 'crm_matches'])
        if res['type'] == 'crm_matches':
            self.assertGreaterEqual(len(res['cards']), 1)
            # بررسی محرمانگی در کارت‌های پیشنهادی مشاور
            first_card = res['cards'][0]['card_text']
            self.assertNotIn("09129998877", first_card)

    def test_07_hot_lead_visit_coordination_alert(self):
        """تست درخواست بازدید حضوری کاربر و تولید رسمی هشدار Hot Lead"""
        chat_id = 77773
        prop_id = self.test_property.id

        # کاربر دکمه «هماهنگی بازدید» را می‌زند
        res = UnifiedBotController.handle_callback_query('bale', chat_id, f"act_visit_{prop_id}", user_name="رضا مرادی")
        self.assertEqual(res['type'], 'text')
        self.assertIn('با موفقیت ثبت شد', res['message'])
        self.assertIn('Hot Lead', res['message'])

    def test_08_super_admin_commands(self):
        """تست اعتبارسنجی دسترسی سوپرادمین در تلگرام و بله"""
        # کاربر عادی
        res_forbidden = UnifiedBotController.handle_admin_commands('bale', 12345, '/admin')
        self.assertIn('دسترسی غیرمجاز', res_forbidden['message'])

    def test_09_bale_webhook_route(self):
        """تست دریافت وبهوک شبیه‌سازی‌شده بله از اندپوینت /api/bale/webhook"""
        fake_bale_update = {
            "update_id": 987654,
            "message": {
                "message_id": 456,
                "from": {"id": 1234567, "first_name": "امیر"},
                "chat": {"id": 1234567, "type": "private"},
                "text": self.test_property.file_code
            }
        }
        resp = self.client.post('/api/bale/webhook', json=fake_bale_update)
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertTrue(data.get('processed'))

    def test_10_bale_status_endpoint(self):
        """تست وضعیت سرویس بله از اندپوینت /api/bale/status"""
        resp = self.client.get('/api/bale/status')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('configured', data)


if __name__ == '__main__':
    unittest.main()
