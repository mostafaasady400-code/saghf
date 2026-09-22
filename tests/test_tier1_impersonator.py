import sys
import os
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from crawler.network.impersonator import (
    TLSImpersonatorClient,
    FINGERPRINT_PROFILES,
    HAS_CURL_CFFI
)


class TestTier1TLSImpersonator(unittest.TestCase):
    """
    مجموعه آزمون‌های جامع اعتبارسنجی و بنچمارک لایه اول:
    (Tier 1: High-Throughput TLS Impersonator)
    """

    def setUp(self):
        self.client = TLSImpersonatorClient(impersonate="chrome124", max_requests_per_session=10)

    def test_01_profile_synchronization(self):
        """۱. بررسی تطابق کامل پروفایل‌های اثر انگشت TLS و هدرهای لایه کاربردی"""
        print("\n--- [تست ۱] بررسی همگام‌سازی ماتریس پروفایل‌های TLS ---")
        for key, prof in FINGERPRINT_PROFILES.items():
            self.assertIn("impersonate", prof)
            self.assertIn("user_agent", prof)
            self.assertIn("sec_ch_ua", prof)
            self.assertIn("sec_ch_ua_platform", prof)

            # بررسی تطابق شماره نسخه در User-Agent و Sec-Ch-Ua
            if "124" in key:
                self.assertIn("124", prof["user_agent"])
                self.assertIn("124", prof["sec_ch_ua"])
            elif "120" in key:
                self.assertIn("120", prof["user_agent"])
                self.assertIn("120", prof["sec_ch_ua"])
            elif "131" in key:
                self.assertIn("131", prof["user_agent"])
                self.assertIn("131", prof["sec_ch_ua"])

        print(f"  ✓ تعداد {len(FINGERPRINT_PROFILES)} پروفایل مدرن با هماهنگی ۱۰۰٪ تایید شدند.")

    def test_02_context_aware_header_synthesis(self):
        """۲. بررسی تولیدکننده تطبیقی هدرها متناسب با نوع درخواست (HTML vs API)"""
        print("\n--- [تست ۲] بررسی تولید هوشمند هدرها بر اساس بستر هدف ---")

        # درخواست به صفحه وب دیوار
        divar_web_headers = self.client.generate_context_headers("https://divar.ir/s/tehran/buy-apartment")
        self.assertEqual(divar_web_headers["Sec-Fetch-Dest"], "document")
        self.assertEqual(divar_web_headers["Sec-Fetch-Mode"], "navigate")
        self.assertIn("text/html", divar_web_headers["Accept"])
        self.assertIn("divar.ir", divar_web_headers["Referer"])

        # درخواست به REST API دیوار
        divar_api_headers = self.client.generate_context_headers("https://api.divar.ir/v8/posts-v2/web/test_token")
        self.assertEqual(divar_api_headers["Sec-Fetch-Dest"], "empty")
        self.assertEqual(divar_api_headers["Sec-Fetch-Mode"], "cors")
        self.assertIn("application/json", divar_api_headers["Accept"])
        self.assertEqual(divar_api_headers["Origin"], "https://divar.ir")

        # درخواست به صفحه وب شیپور
        sheypoor_headers = self.client.generate_context_headers("https://www.sheypoor.com/s/tehran/real-estate")
        self.assertEqual(sheypoor_headers["Sec-Fetch-Dest"], "document")
        self.assertIn("sheypoor.com", sheypoor_headers["Referer"])

        print("  ✓ تفکیک دقیق هدرهای وب، API و پلتفرم‌های مقصد تایید شد.")

    def test_03_live_divar_web_throughput(self):
        """۳. آزمون زنده اتصال به دیوار با کلاینت جعل اثر انگشت و سنجش تاخیر"""
        print("\n--- [تست ۳] آزمون زنده اتصال به دیوار و سنجش Throughput ---")
        url = "https://divar.ir/s/tehran/buy-apartment"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("__PRELOADED_STATE__", resp.text)
        metrics = self.client.get_metrics()

        print(f"  ✓ پاسخ دریافت شد: وضعیت {resp.status_code} | طول محتوا: {len(resp.text):,} بایت")
        print(f"  ✓ زمان تاخیر اتصال (Latency): {metrics['last_latency_ms']} میلی‌ثانیه")
        self.assertLess(metrics['last_latency_ms'], 20000, "Latency is higher than expected")

    def test_04_live_sheypoor_throughput(self):
        """۴. آزمون زنده اتصال به شیپور با لایه اول"""
        print("\n--- [تست ۴] آزمون زنده اتصال به شیپور ---")
        url = "https://www.sheypoor.com/s/tehran/real-estate"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        metrics = self.client.get_metrics()
        print(f"  ✓ پاسخ دریافت شد: وضعیت {resp.status_code} | طول محتوا: {len(resp.text):,} بایت")
        print(f"  ✓ زمان تاخیر اتصال: {metrics['last_latency_ms']} میلی‌ثانیه")

    def test_05_session_lifecycle_and_auto_recycling(self):
        """۵. بررسی چرخه حیات نشست و بازنشانی خودکار پس از سقف درخواست‌ها"""
        print("\n--- [تست ۵] بررسی چرخه حیات نشست و بازنشانی ادواری (Auto-Recycling) ---")
        small_client = TLSImpersonatorClient(max_requests_per_session=3)

        self.assertEqual(small_client.session_request_count, 0)
        small_client.generate_context_headers("https://divar.ir/s/tehran")
        small_client.session_request_count = 3
        # در درخواست بعدی باید نشست بازنشانی شود
        small_client.get("https://divar.ir/s/tehran/real-estate")
        self.assertEqual(small_client.session_request_count, 1)
        self.assertGreater(small_client.total_requests, 0)

        metrics = small_client.get_metrics()
        print(f"  ✓ بازنشانی نشست تایید شد. آمار مانیتورینگ: {metrics}")


if __name__ == '__main__':
    unittest.main()
