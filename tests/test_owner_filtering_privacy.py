"""
Comprehensive Test Suite for Owner Filtering & Privacy Preservation Engine.
Tests two-stage filtering, evasion neutralization, false-positive guardrails,
confidence scoring, phone masking, text sanitization, and access audit logging.
Zero-Mock Implementation.
"""

import unittest
from crawler.owner_filter import OwnerFilter, FilterResult, clean_persian_text, extract_phone_number
from crawler.privacy import PrivacyManager

class TestOwnerFilteringPrivacy(unittest.TestCase):
    """
    آزمون‌های جامع سیستم فیلترینگ واسطه‌ها و حفظ محرمانگی اطلاعات مالکین
    """

    def test_01_two_stage_owner_filtering_accuracy(self):
        """۱. آزمون دقت فیلتر دومرحله‌ای (مرحله اول: نوع حساب / مرحله دوم: متن و عنوان)"""
        # ۱. الف: مرحله ۱ - تشخیص پنل املاک دیوار در bottom_description
        res_divar_agency = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۷۵ متری شیک',
            description='طبقه اول با پارکینگ سندی',
            widget_data={'bottom_description_text': 'املاک بزرگ پارس در سعادت آباد'}
        )
        self.assertFalse(res_divar_agency.is_personal)
        self.assertEqual(res_divar_agency.status, 'rejected_account_type')
        self.assertEqual(res_divar_agency.owner_type, 'agency')
        self.assertEqual(res_divar_agency.confidence_score, 0)
        self.assertEqual(res_divar_agency.risk_level, 'high')

        # ۱. ب: مرحله ۱ - تشخیص اکانت تجاری دیوار در سرور
        res_divar_biz = OwnerFilter.evaluate(
            platform='divar',
            title='واحد ۱۲۰ متری نوساز',
            widget_data={'action_log': {'server_side_info': {'info': {'is_business': True, 'business_id': 'biz_89'}}}}
        )
        self.assertFalse(res_divar_biz.is_personal)
        self.assertEqual(res_divar_biz.status, 'rejected_account_type')

        # ۱. ج: مرحله ۱ - تشخیص اسپانسرینگ و حساب آژانس در شیپور
        res_sheypoor_ad = OwnerFilter.evaluate(
            platform='sheypoor',
            title='آپارتمان ۹۰ متری',
            raw_text='آپارتمان ۹۰ متری Ad تابلو شده املاک پایتخت'
        )
        self.assertFalse(res_sheypoor_ad.is_personal)
        self.assertEqual(res_sheypoor_ad.status, 'rejected_account_type')

        # ۱. د: مرحله ۲ - اکانت شخصی است ولی کلمه ممنوعه (مشاور) در متن دارد
        res_text_broker = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۸۰ متری فول',
            description='مشاور شما احمدی در خدمت شماست',
            widget_data={'bottom_description_text': 'دقایقی پیش در ونک'}
        )
        self.assertFalse(res_text_broker.is_personal)
        self.assertEqual(res_text_broker.status, 'rejected_forbidden_words')
        self.assertIn('مشاور', res_text_broker.detected_terms)

    def test_02_unicode_and_stealth_evasion_neutralization(self):
        """۲. آزمون خنثی‌سازی شگردهای گریز، تطویل (کشیدگی حروف) و نویسه‌های مخفی یونیکد"""
        # الف: استفاده از کشیدگی حروف (تطویل / کَشیده: اـمـلـاـک)
        tatweel_text = "واحد فوق العاده جهت هماهنگی با اـمـلـاـک تماس بگیرید"
        cleaned_tatweel = clean_persian_text(tatweel_text)
        self.assertIn("املاک", cleaned_tatweel)
        res_tatweel = OwnerFilter.evaluate(platform='divar', title='آپارتمان', description=tatweel_text)
        self.assertFalse(res_tatweel.is_personal)
        self.assertEqual(res_tatweel.status, 'rejected_forbidden_words')

        # ب: استفاده از نویسه‌های نامرئی Zero-Width Space و Zero-Width Non-Joiner
        invisible_text = "دفتر\u200bم\u200cش\u200bا\u200cو\u200bر املاک پاسخگوی شماست"
        res_invisible = OwnerFilter.evaluate(platform='divar', title='آپارتمان', description=invisible_text)
        self.assertFalse(res_invisible.is_personal)

        # ج: حروف فاصله‌دار یا نمادین بین کلمات (ا م ل ا ک یا ا*م*ل*ا*ک)
        spaced_text = "جهت بازدید هماهنگ با ا م ل ا ک مرکزی"
        res_spaced = OwnerFilter.evaluate(platform='divar', title='آپارتمان', description=spaced_text)
        self.assertFalse(res_spaced.is_personal)

    def test_03_false_positive_guardrails(self):
        """۳. آزمون گاردریل‌های پیشگیری از مثبت کاذب بر روی واژگان طبیعی و مجاز زبان فارسی"""
        # کلمه «کارخانه» نباید به دلیل وجود زیررشته «خانه» باعث رد آگهی شود
        res_factory = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۸۵ متری نزدیک کارخانه قند',
            description='واحد شخصی ساز بسیار تمیز با سند تک برگ شخصی',
            widget_data={'bottom_description_text': 'دقایقی پیش در وردآورد'}
        )
        self.assertTrue(res_factory.is_personal)
        self.assertEqual(res_factory.status, 'approved_personal')

        # کلمه «صاحبخانه» و «آشپزخانه» نباید منجر به رد آگهی شوند
        res_home = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۹۰ متری دو خوابه',
            description='صاحبخانه هستم و آشپزخانه واحد کاملاً بازسازی شده است. تخلیه فوری.',
            widget_data={'bottom_description_text': 'دقایقی پیش در پونک'}
        )
        self.assertTrue(res_home.is_personal)
        self.assertEqual(res_home.status, 'approved_personal')

        # کلمه «داروخانه»
        res_pharma = OwnerFilter.evaluate(
            platform='sheypoor',
            title='فروش آپارتمان ۷۰ متری جنب داروخانه شبانه‌روزی',
            description='فروشنده واقعی هستم، بدون واسطه.'
        )
        self.assertTrue(res_pharma.is_personal)

    def test_04_confidence_scoring_and_risk_levels(self):
        """۴. آزمون محاسبه نمره اطمینان مالکیت شخصی (Confidence Score) و سطوح ریسک"""
        # فایل با نشانه‌های محکم شخصی (سند تک برگ، مالک هستم، بدون واسطه)
        res_high_conf = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۱۱۰ متری شخصی ساز',
            description='مالک هستم، سند تک برگ شخصی، بدون واسطه به خریدار واقعی تخفیف پای معامله داده می‌شود.',
            widget_data={'bottom_description_text': 'دقایقی پیش در سعادت آباد'}
        )
        self.assertTrue(res_high_conf.is_personal)
        self.assertGreaterEqual(res_high_conf.confidence_score, 90)
        self.assertEqual(res_high_conf.risk_level, 'low')
        self.assertIn('مالک هستم', res_high_conf.metadata.get('positive_markers', []))

        # فایل رد شده با سطح ریسک high
        res_rejected = OwnerFilter.evaluate(
            platform='divar',
            title='واحد اداری',
            description='کمیسیون یک درصد دریافت می‌شود',
            widget_data={'bottom_description_text': 'دقایقی پیش در ونک'}
        )
        self.assertFalse(res_rejected.is_personal)
        self.assertLessEqual(res_rejected.confidence_score, 40)
        self.assertEqual(res_rejected.risk_level, 'high')

    def test_05_phone_masking_styles_and_robustness(self):
        """۵. آزمون ماسک‌گذاری هوشمند شماره‌های تماس در استایل‌های متنوع"""
        raw_phone = "09123456789"

        # استایل پیش‌فرض (ستاره)
        masked_star = PrivacyManager.mask_phone(raw_phone, style="asterisk")
        self.assertEqual(masked_star, "0912***6789")

        # استایل خط تیره (hyphen)
        masked_hyphen = PrivacyManager.mask_phone(raw_phone, style="hyphen")
        self.assertEqual(masked_hyphen, "0912-XXX-6789")

        # استایل نقطه بولت (dot)
        masked_dot = PrivacyManager.mask_phone(raw_phone, style="dot")
        self.assertEqual(masked_dot, "0912••••6789")

        # شماره ۱۰ رقمی بدون صفر اول
        masked_ten = PrivacyManager.mask_phone("9123456789")
        self.assertEqual(masked_ten, "0912***6789")

        # داده خالی یا نامعتبر
        self.assertEqual(PrivacyManager.mask_phone(None), "")
        self.assertEqual(PrivacyManager.mask_phone(""), "")

    def test_06_text_sanitization_and_privacy_safeguards(self):
        """۶. آزمون پالایش امن متن و ماسک‌کردن شماره‌های تلفن موجود در توضیحات"""
        raw_desc = "واحد نوساز طبقه ۴. جهت هماهنگی با شماره 09123456789 یا 09351112233 تماس بگیرید."
        sanitized = PrivacyManager.sanitize_text(raw_desc)

        # اطمینان از اینکه شماره‌های خام در متن باقی نمانده‌اند
        self.assertNotIn("09123456789", sanitized)
        self.assertNotIn("09351112233", sanitized)
        # شماره‌ها باید به صورت ماسک‌شده در متن درج شوند
        self.assertIn("0912***6789", sanitized)
        self.assertIn("0935***2233", sanitized)

    def test_07_rbac_unmasking_and_access_audit_logging(self):
        """۷. آزمون کنترل دسترسی نقشی (RBAC) و ثبت رخداد ممیزی محرمانگی (Audit Trail)"""
        phone = "09129876543"

        # نقش مهمان یا کاربر عادی -> شماره باید ماسک شود
        guest_view = PrivacyManager.unmask_phone(phone, viewer_role="guest")
        self.assertEqual(guest_view, "0912***6543")

        # نقش ادمین یا مشاور تأییدشده -> شماره کامل نمایش داده می‌شود
        admin_view = PrivacyManager.unmask_phone(phone, viewer_role="admin")
        self.assertEqual(admin_view, "09129876543")

        # ایجاد رخداد ممیزی دسترسی به هویت مالک
        audit_event = PrivacyManager.create_access_audit_event(
            property_id=101,
            user_id="agent_42",
            user_role="vip_broker",
            action="VIEW_CONTACT",
            ip_address="192.168.1.15"
        )
        self.assertEqual(audit_event['event_type'], 'OWNER_CONTACT_ACCESS')
        self.assertEqual(audit_event['property_id'], 101)
        self.assertEqual(audit_event['user_id'], 'agent_42')
        self.assertTrue(audit_event['is_authorized'])
        self.assertIn('timestamp', audit_event)

    def test_08_persian_word_number_phone_extraction(self):
        """۸. آزمون استخراج شماره‌های نوشته شده به حروف فارسی"""
        word_phone_text = "تماس با مالک: صفر نهصد و دوازده سه چهار پنج شش هفت هشت نه"
        phone = extract_phone_number(word_phone_text)
        self.assertEqual(phone, "09123456789")

if __name__ == '__main__':
    unittest.main()
