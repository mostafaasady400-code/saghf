"""
=============================================================================
مجموعه آزمون‌های جامع ممیزی ارتباطات چندکاناله و ربات‌ها (Omnichannel Bots Audit)
آزمون‌های یکپارچگی صفر-ماک (Zero-Mock) شامل:
۱. اینترفیس و سلامت آداپتورهای ۵ پیام‌رسان (Telegram, Bale, Eitaa, WhatsApp, Rubika)
۲. دیسپچر مرکزی، ارسال بسته‌های ملکی و ثبت در جدول OutreachLog
۳. ارسال دسته‌ای پیام مستقیم و تله‌متری شاخص‌های ارسال (Latency & Metrics)
۴. تقارن دکمه‌های شیشه‌ای در BotMarkupBuilder برای بله و تلگرام
۵. استیت‌ماشین ۵ مرحله‌ای ویزارد فیلترینگ و انزوای نشست‌های کاربران
۶. قانون حیاتی محرمانگی و عدم افشای شماره مالک در کارت‌های ربات
۷. تولید دیپ‌لینک‌های ۵ پیام‌رسان و استانداردسازی شماره‌های همراه
۸. پردازش دوطرفه استعلام چرخه حیات ملک (Reactivate vs Archive)
=============================================================================
"""

import json
import unittest
from datetime import datetime

from app import create_app
from database.db import db
from database.models import Property, Owner, CustomerLead, OutreachLog, Interaction
from services.omnichannel.dispatcher import omnichannel_dispatcher, OmnichannelDispatcher
from services.omnichannel.base import BaseChannelAdapter
from services.unified_bot_controller import UnifiedBotController, BotMarkupBuilder, wizard_sessions
from services.messenger_service import OmniMessengerService


class TestOmnichannelBotsAudit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

        # مالک و ملک واقعی جهت آزمون‌های یکپارچگی و اصل محرمانگی
        owner = Owner.query.filter_by(phone_number="09129876543").first()
        if not owner:
            owner = Owner(full_name="مالک تست محرمانگی نیاوران", phone_number="09129876543")
            db.session.add(owner)
            db.session.commit()
        cls.test_owner = owner

        # بررسی یا ایجاد ملک نمونه با کد مشخص
        prop = Property.query.filter_by(title="آپارتمان ۱۴۰ متری ممیزی چندکاناله سقف").first()
        if not prop:
            prop = Property(
                title="آپارتمان ۱۴۰ متری ممیزی چندکاناله سقف",
                district="نیاوران",
                city="تهران",
                deal_type="sale",
                property_type="apartment",
                total_price=12_000_000_000,
                area=140,
                rooms=3,
                floor=4,
                has_parking=True,
                has_elevator=True,
                has_warehouse=True,
                has_balcony=True,
                source="divar",
                source_url="https://divar.ir/v/confidential-omnichannel-audit",
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

        # متقاضی واقعی جهت آزمون دیسپچر
        lead = CustomerLead.query.filter_by(phone_number="09351234567").first()
        if not lead:
            lead = CustomerLead(
                full_name="متقاضی تست چندکاناله",
                phone_number="09351234567",
                active_messenger="bale",
                deal_type="sale",
                max_budget=15_000_000_000,
                preferred_districts=["نیاوران", "فرمانیه"]
            )
            db.session.add(lead)
            db.session.commit()
        cls.test_lead = lead

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def test_01_adapter_interfaces_and_platforms(self):
        """۱. آزمون انطباق اینترفیس و اسامی ۵ آداپتور رسمی پیام‌رسان‌ها"""
        expected_platforms = ['telegram', 'bale', 'eitaa', 'whatsapp', 'rubika']
        for p in expected_platforms:
            adapter = omnichannel_dispatcher.get_adapter(p)
            self.assertIsInstance(adapter, BaseChannelAdapter)
            self.assertEqual(adapter.platform_name, p)

            # ارسال تست شبیه‌سازی / زنده
            res = adapter.send_text("09351234567", f"پیام ارزیابی ممیزی پلتفرم {p}")
            self.assertIsInstance(res, dict)
            self.assertIn('success', res)
            self.assertEqual(res.get('platform'), p)

    def test_02_dispatcher_lead_routing_and_outreach_log(self):
        """۲. آزمون دیسپچ پکیج ملکی به متقاضی و ثبت رکورد تحویل در جدول OutreachLog"""
        prop_item = {
            'id': self.test_property.id,
            'ad_code': self.test_property.file_code or "99001",
            'title': self.test_property.title,
            'district': self.test_property.district,
            'area': self.test_property.area,
            'total_price': self.test_property.total_price,
            'match_score': 95,
            'source_type': 'property',
            'images': ['https://example.com/img1.jpg'],
            'source_url': 'https://divar.ir/v/sample'
        }

        results = omnichannel_dispatcher.dispatch_to_lead(
            lead=self.test_lead,
            property_items=[prop_item],
            platform='bale',
            enable_fallback=False
        )

        self.assertEqual(len(results), 1)
        r0 = results[0]
        self.assertEqual(r0['platform'], 'bale')
        self.assertIn(r0['status'], ['sent', 'failed'])
        self.assertGreaterEqual(r0['latency_ms'], 0.0)

        # اعتبارسنجی ثبت در دیتابیس OutreachLog
        log_entry = OutreachLog.query.filter_by(
            lead_id=self.test_lead.id,
            platform='bale'
        ).order_by(OutreachLog.id.desc()).first()

        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.platform, 'bale')
        self.assertIn(log_entry.status, ['sent', 'failed'])

    def test_03_batch_direct_dispatching_and_metrics(self):
        """۳. آزمون ارسال دسته‌ای پیام مستقیم و تله‌متری شاخص‌های عملکرد دیسپچر"""
        recipients = ["09121111111", "09352222222", "09213333333"]
        test_msg = "🏛️ هشدار سامانه سقف: فایل جدید متناسب با بودجه شما ثبت گردید."

        batch_res = omnichannel_dispatcher.batch_dispatch_direct(
            recipients=recipients,
            message=test_msg,
            platform='telegram'
        )

        self.assertEqual(len(batch_res), 3)
        for br in batch_res:
            self.assertTrue(br['success'])
            self.assertEqual(br['platform'], 'telegram')
            self.assertGreaterEqual(br['latency_ms'], 0.0)

        # بررسی شاخص‌های عملیاتی دیسپچر
        metrics = omnichannel_dispatcher.get_dispatch_metrics()
        self.assertGreater(metrics['total_dispatches'], 0)
        self.assertGreater(metrics['successful_dispatches'], 0)
        self.assertGreaterEqual(metrics['success_rate_pct'], 50.0)
        self.assertIn('telegram', metrics['platform_breakdown'])

    def test_04_bot_markup_builder_symmetry(self):
        """۴. آزمون تقارن ساختاری دکمه‌های شیشه‌ای برای تلگرام و بله در BotMarkupBuilder"""
        # الف) بله: تولید دیکشنری استاندارد JSON
        bale_b = BotMarkupBuilder('bale')
        bale_b.add_row(("🎯 فیلتر هوشمند", "cb_filter", None), ("🏷️ فایل‌های فروش", "cb_sale", None))
        bale_b.add_row(("🌐 ورود به پرتال", None, "https://saghf.ir"))
        bale_markup = bale_b.build()

        self.assertIsInstance(bale_markup, dict)
        self.assertIn('inline_keyboard', bale_markup)
        self.assertEqual(len(bale_markup['inline_keyboard']), 2)
        self.assertEqual(len(bale_markup['inline_keyboard'][0]), 2)
        self.assertEqual(bale_markup['inline_keyboard'][0][0]['callback_data'], 'cb_filter')
        self.assertEqual(bale_markup['inline_keyboard'][1][0]['url'], 'https://saghf.ir')

        # ب) تلگرام: تولید شیء رسمی telebot.types.InlineKeyboardMarkup
        tg_b = BotMarkupBuilder('telegram')
        tg_b.add_row(("🎯 فیلتر هوشمند", "cb_filter", None), ("🏷️ فایل‌های فروش", "cb_sale", None))
        tg_b.add_row(("🌐 ورود به پرتال", None, "https://saghf.ir"))
        tg_markup = tg_b.build()

        self.assertEqual(len(tg_markup.keyboard), 2)
        self.assertEqual(len(tg_markup.keyboard[0]), 2)
        self.assertEqual(tg_markup.keyboard[0][0].callback_data, 'cb_filter')
        self.assertEqual(tg_markup.keyboard[1][0].url, 'https://saghf.ir')

    def test_05_unified_bot_controller_five_step_wizard(self):
        """۵. آزمون چرخه کامل استیت‌ماشین ویزارد ۵ مرحله‌ای در بله و تلگرام"""
        chat_id_bale = 77701
        chat_id_tg = 77702

        for plat, cid in [('bale', chat_id_bale), ('telegram', chat_id_tg)]:
            # گام ۱: استارت ویزارد
            r1 = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_start')
            self.assertIn('گام ۱ از ۵', r1['message'])

            # گام ۲: انتخاب نوع معامله (فروش)
            r2 = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_deal_sale')
            self.assertIn('گام ۲ از ۵', r2['message'])

            # گام ۳: نوع ملک (آپارتمان)
            r3 = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_type_apartment')
            self.assertIn('گام ۳ از ۵', r3['message'])

            # گام ۴: محدوده محله (نیاوران)
            r4 = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_dist_نیاوران')
            self.assertIn('گام ۴ از ۵', r4['message'])

            # گام ۵: بودجه
            r5 = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_bud_s3')
            self.assertIn('گام ۵ از ۵', r5['message'])

            # بررسی وجود و انزوای نشست کاربر قبل از اجرای نهایی
            sess_key = UnifiedBotController.get_session_key(plat, cid)
            self.assertIn(sess_key, wizard_sessions)

            # اجرای نهایی و دریافت کارت‌های فایلینگ
            r_exec = UnifiedBotController.handle_callback_query(plat, cid, 'wiz_exec')
            self.assertIn(r_exec['type'], ['crm_matches', 'text'])

            # بررسی پاک‌سازی ایمن نشست پس از اجرا
            self.assertNotIn(sess_key, wizard_sessions)

    def test_06_direct_code_search_and_privacy_redaction(self):
        """۶. آزمون جستجوی مستقیم کد فایل و اصل حیاتی عدم افشای شماره مالک در کارت ربات"""
        code = self.test_property.file_code
        self.assertIsNotNone(code)

        # استعلام مستقیم در بله
        res = UnifiedBotController.handle_code_search('bale', 88801, code)
        self.assertEqual(res['type'], 'property_package')
        card_text = res['card_text']

        # مشخصات کلی باید موجود باشد
        self.assertIn(code, card_text)
        self.assertIn(self.test_property.district, card_text)

        # اصل طلایی محرمانگی:
        # ۱. شماره تماس مستقیم مالک (09129876543) نباید تحت هیچ شرایطی در کارت ظاهر شود
        self.assertNotIn("09129876543", card_text)
        # ۲. لینک خام دیوار نباید افشا شود
        self.assertNotIn("https://divar.ir/v/confidential-omnichannel-audit", card_text)

    def test_07_omni_messenger_deep_links_and_phone_normalization(self):
        """۷. آزمون استانداردسازی شماره‌های همراه و تولید دیپ‌لینک‌های ۵ پیام‌رسان"""
        # الف) استانداردسازی پیش‌شماره‌های ایران به قالب ۱۰ رقمی
        self.assertEqual(OmniMessengerService.normalize_phone("09129876543"), "9129876543")
        self.assertEqual(OmniMessengerService.normalize_phone("+989129876543"), "9129876543")
        self.assertEqual(OmniMessengerService.normalize_phone("989129876543"), "9129876543")
        self.assertEqual(OmniMessengerService.normalize_phone("0935 123 4567"), "9351234567")

        # ب) تولید دیپ‌لینک‌ها برای ۵ پیام‌رسان
        links = OmniMessengerService.get_platform_links(
            phone="09129876543",
            message="سلام تست استعلام موجودی ملک سقف",
            source_url="https://divar.ir/v/sample"
        )
        self.assertIn('whatsapp', links)
        self.assertIn('telegram', links)
        self.assertIn('bale', links)
        self.assertIn('eitaa', links)
        self.assertIn('rubika', links)

        self.assertTrue(links['whatsapp']['url'].startswith("https://wa.me/989129876543"))
        self.assertTrue(links['telegram']['url'].startswith("https://t.me/+989129876543"))
        self.assertTrue(links['bale']['url'].startswith("https://ble.ir/+989129876543"))
        self.assertTrue(links['eitaa']['url'].startswith("https://eitaa.com/+989129876543"))
        self.assertTrue(links['rubika']['url'].startswith("https://rubika.ir/+989129876543"))

    def test_08_two_way_lifecycle_owner_response_state_machine(self):
        """۸. آزمون استیت‌ماشین پردازش دوطرفه پاسخ مالک (فعال‌سازی مجدد در برابر بایگانی)"""
        prop_id = self.test_property.id

        # سناریوی الف: پاسخ «1» یا «موجود» -> ملک فعال شده، تایمر صفر می‌شود
        res_avail = OmniMessengerService.handle_owner_response(
            property_id=prop_id,
            response_code="1",
            platform="bale",
            notes="مالک اعلام کرد کماکان موجود و قابل بازدید است"
        )
        self.assertTrue(res_avail['success'])
        self.assertEqual(res_avail['status'], 'available')

        refreshed_p = Property.query.get(prop_id)
        self.assertEqual(refreshed_p.status, 'available')
        self.assertIn(refreshed_p.inquiry_status, ['confirmed_available', 'confirmed'])

        # سناریوی ب: پاسخ «2» یا «واگذار شد» -> ملک به وضعیت بایگانی قطعی منتقل می‌شود
        res_sold = OmniMessengerService.handle_owner_response(
            property_id=prop_id,
            response_code="2",
            platform="telegram",
            notes="ملک فروخته شده است"
        )
        self.assertTrue(res_sold['success'])
        self.assertEqual(res_sold['status'], 'archived')

        archived_p = Property.query.get(prop_id)
        self.assertEqual(archived_p.status, 'archived')
        self.assertIn(archived_p.inquiry_status, ['confirmed_sold', 'sold'])

        # بازگردانی وضعیت به verified جهت آزمون‌های بعدی و پاک‌سازی تعاملات تستی
        archived_p.status = 'verified'
        from database.models import Interaction
        Interaction.query.filter_by(property_id=prop_id).delete()
        db.session.commit()


if __name__ == '__main__':
    unittest.main()
