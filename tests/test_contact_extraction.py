"""
Comprehensive Unit Test Suite for Contact Number Extraction & Verification Engine.
Tests Persian word-number decoding, operator identification, obfuscated digits,
dummy phone filtering, deep JSON extraction, and backward compatibility.
Zero-Mock Implementation.
"""

import unittest
from crawler.contact_extractor import ContactExtractor
from crawler.owner_filter import extract_phone_number, convert_persian_words_to_digits

class TestContactExtraction(unittest.TestCase):
    """
    آزمون‌های جامع استخراج و اعتبارسنجی شماره تماس آگهی‌دهندگان
    """

    def test_01_persian_word_number_decoding(self):
        """۱. آزمون دیکودر پیشرفته اعداد حروفی فارسی (تکی، ترکیبی، دهگان و صدگان)"""
        # الف) پیش‌شماره ترکیبی + اعداد یک رقمی
        text1 = "تماس با مالک: صفر نهصد و دوازده هشت هفت شش پنج چهار سه دو"
        decoded1 = ContactExtractor.convert_persian_words_to_digits(text1)
        phone1 = ContactExtractor.extract_primary_phone(text1)
        self.assertIn("0912", decoded1)
        self.assertEqual(phone1, "09128765432")

        # ب) پیش‌شماره نهصد و سی و پنج (ایرانسل)
        text2 = "شماره مستقیم: نهصد و سی و پنج دو دو یک چهار سه پنج شش"
        phone2 = ContactExtractor.extract_primary_phone(text2)
        self.assertEqual(phone2, "09352214356")

        # ج) پیش‌شماره رایتل
        text3 = "تماس فقط با نهصد و بیست و یک هشت هفت شش پنج چهار سه دو"
        phone3 = ContactExtractor.extract_primary_phone(text3)
        self.assertEqual(phone3, "09218765432")

    def test_02_persian_and_arabic_digit_normalization(self):
        """۲. آزمون استانداردسازی ارقام فارسی و عربی"""
        fa_text = "شماره مالک: ۰۹۱۲۸۷۶۵۴۳۲"
        ar_text = "شماره مالک: ٠٩١٢٨٧٦٥٤٣٢"

        phone_fa = ContactExtractor.extract_primary_phone(fa_text)
        phone_ar = ContactExtractor.extract_primary_phone(ar_text)

        self.assertEqual(phone_fa, "09128765432")
        self.assertEqual(phone_ar, "09128765432")

    def test_03_operator_identification_and_validation(self):
        """۳. آزمون اعتبارسنجی و شناسایی دقیق اپراتورهای مخابراتی ایران"""
        # همراه اول (MCI)
        mci_res = ContactExtractor.validate_and_normalize("09128765432")
        self.assertIsNotNone(mci_res)
        self.assertEqual(mci_res['operator'], 'MCI')
        self.assertEqual(mci_res['type'], 'mobile')
        self.assertTrue(mci_res['is_valid'])

        # ایرانسل (MTN_Irancell)
        mtn_res = ContactExtractor.validate_and_normalize("09351234567")
        self.assertIsNotNone(mtn_res)
        self.assertEqual(mtn_res['operator'], 'MTN_Irancell')
        self.assertEqual(mtn_res['type'], 'mobile')

        # رایتل (Rightel)
        rightel_res = ContactExtractor.validate_and_normalize("09211234567")
        self.assertIsNotNone(rightel_res)
        self.assertEqual(rightel_res['operator'], 'Rightel')

        # تلفن ثابت تهران
        landline_res = ContactExtractor.validate_and_normalize("02188776655")
        self.assertIsNotNone(landline_res)
        self.assertEqual(landline_res['type'], 'landline')
        self.assertIn('تهران', landline_res['operator'])

    def test_04_obfuscated_and_spaced_phone_extraction(self):
        """۴. آزمون استخراج شماره‌های استتاریافته، فاصله‌دار و دارای کاراکترهای جداکننده"""
        # الف) شماره‌های فاصله‌دار عمدی (0 9 1 2 ...)
        spaced_text = "مالک: 0 9 1 2 8 7 6 5 4 3 2"
        phone_spaced = ContactExtractor.extract_primary_phone(spaced_text)
        self.assertEqual(phone_spaced, "09128765432")

        # ب) خط تیره، نقطه، ستاره و اسلش
        symbols_text = "تماس: 0912-876-5432 یا 0935*876*5432 یا 0921/876/5432"
        all_phones = ContactExtractor.extract_all_phones(symbols_text)
        self.assertIn("09128765432", all_phones)
        self.assertIn("09358765432", all_phones)
        self.assertIn("09218765432", all_phones)

    def test_05_international_and_ten_digit_formats(self):
        """۵. آزمون استخراج شماره‌های بین‌المللی و ده‌رقمی بدون صفر اول"""
        # فرمت +989...
        phone_plus98 = ContactExtractor.extract_primary_phone("شماره تماس: +989128765432")
        self.assertEqual(phone_plus98, "09128765432")

        # فرمت 00989...
        phone_0098 = ContactExtractor.extract_primary_phone("واتساپ: 00989128765432")
        self.assertEqual(phone_0098, "09128765432")

        # فرمت ۱۰ رقمی بدون صفر اول (912...)
        phone_ten = ContactExtractor.extract_primary_phone("تلفن: 9128765432")
        self.assertEqual(phone_ten, "09128765432")

    def test_06_dummy_and_suspicious_phone_filtering(self):
        """۶. آزمون فیلتر شماره‌های جعلی، تستی، ساختگی یا اسپم"""
        # همه ارقام یکسان
        self.assertTrue(ContactExtractor.is_dummy_or_suspicious("09111111111"))
        self.assertTrue(ContactExtractor.is_dummy_or_suspicious("09222222222"))

        # توالی عددی ساده
        self.assertTrue(ContactExtractor.is_dummy_or_suspicious("09123456789"))

        # صفر یکنواخت در بدنه
        self.assertTrue(ContactExtractor.is_dummy_or_suspicious("09120000000"))

        # شماره معتبر نباید جعلی شناخته شود
        self.assertFalse(ContactExtractor.is_dummy_or_suspicious("09128765432"))

    def test_07_extract_from_deep_json_payloads(self):
        """۷. آزمون استخراج بازگشتی از ساختارهای تودرتوی JSON و ویجت‌های دیوار"""
        divar_widget_payload = {
            'widget_list': [
                {'widget_type': 'TITLE_ROW', 'data': {'text': 'آپارتمان ۷۵ متری'}},
                {
                    'widget_type': 'CONTACT_ROW',
                    'action': {
                        'type': 'CALL',
                        'payload': {
                            'phone_number': '09128765432',
                            'phone': '09128765432'
                        }
                    }
                }
            ]
        }
        phone = ContactExtractor.extract_from_json_recursive(divar_widget_payload)
        self.assertEqual(phone, "09128765432")

    def test_08_backward_compatibility_with_owner_filter(self):
        """۸. آزمون سازگاری کامل پس‌رو با توابع ماژول crawler.owner_filter"""
        # فراخوانی متد تاریخی extract_phone_number از owner_filter
        phone = extract_phone_number("تماس با 09128765432")
        self.assertEqual(phone, "09128765432")

        # فراخوانی convert_persian_words_to_digits از owner_filter
        res_words = convert_persian_words_to_digits("صفر نهصد و دوازده")
        self.assertEqual(res_words, "0912")

if __name__ == '__main__':
    unittest.main()
