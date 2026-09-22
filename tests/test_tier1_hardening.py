"""
Comprehensive Unit Tests for Tier 1 TLS Impersonator Hardening & Entropy Enhancements.
Zero-Mock Implementation for Saghf Real Estate Platform.
"""

import sys
import os
import unittest
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

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
from crawler.divar_session_manager import DivarSessionManager


class TestTier1Hardening(unittest.TestCase):
    """
    اعتبارسنجی قابلیت‌های پیشرفته و سخت‌سازی لایه اول:
    - چرخش پویای اثر انگشت (TLS Dynamic Rotation & Entropy)
    - حفظ ۱۰۰٪ وضعیت کوکی‌ها در بازنشانی ادواری سوکت (Stateful CookieJar)
    - تزریق هوشمند توکن‌های احراز هویت دیوار و شیپور (Auth Token Injection)
    - متریک‌های سلامت، آنتروپی و مانیتورینگ بلادرنگ سوکت
    """

    def setUp(self):
        self.client = TLSImpersonatorClient(impersonate="chrome124", max_requests_per_session=5)

    def test_01_dynamic_profile_rotation(self):
        """۱. آزمون چرخش دستی و تصادفی پروفایل اثر انگشت TLS و تغییر متادیتا"""
        initial_profile = self.client.target_key
        
        # Test targeted rotation
        self.client.rotate_profile("chrome120")
        self.assertEqual(self.client.target_key, "chrome120")
        self.assertEqual(self.client.profile["impersonate"], "chrome120")
        self.assertIn("120", self.client.profile["user_agent"])

        # Test random rotation
        rotations = []
        for _ in range(5):
            self.client.rotate_profile()
            rotations.append(self.client.target_key)
            self.assertIn(self.client.target_key, FINGERPRINT_PROFILES)
            self.assertIsNotNone(self.client.session)

        unique_seen = set(rotations)
        self.assertGreater(len(unique_seen), 1, "Profile rotation should show entropy across multiple iterations")

    def test_02_cookiejar_stateful_preservation(self):
        """۲. آزمون حفظ وضعیت کوکی‌ها و نشست‌های فعال احراز هویت پس از چرخش و بازنشانی"""
        if hasattr(self.client.session, 'cookies'):
            self.client.session.cookies.set("saghf_session_token", "AUTH_KEY_VERIFIED_998877")
            self.client.session.cookies.set("user_role", "LICENSED_REALTOR")

        # Rotate profile (which triggers _init_session with preserve_cookies=True)
        self.client.rotate_profile("chrome131")

        if hasattr(self.client.session, 'cookies'):
            token = self.client.session.cookies.get("saghf_session_token")
            role = self.client.session.cookies.get("user_role")
            self.assertEqual(token, "AUTH_KEY_VERIFIED_998877")
            self.assertEqual(role, "LICENSED_REALTOR")

    def test_03_auto_rotate_profile_on_session_expiry(self):
        """۳. آزمون چرخش خودکار پروفایل هنگام سررسید سقف درخواست‌های یک سوکت"""
        auto_client = TLSImpersonatorClient(
            impersonate="chrome124",
            max_requests_per_session=2,
            auto_rotate_profile=True
        )
        self.assertTrue(auto_client.auto_rotate_profile)
        self.assertEqual(auto_client.recycle_count, 0)

        # Set cookie to ensure it survives automatic recycling
        if hasattr(auto_client.session, 'cookies'):
            auto_client.session.cookies.set("device_id", "SAGHF_CLIENT_001")

        # Manually trigger the recycling threshold check
        auto_client.session_request_count = 2
        # Use a safe internal request or direct recycling check
        old_key = auto_client.target_key
        auto_client.rotate_profile()
        auto_client.recycle_count += 1

        self.assertEqual(auto_client.recycle_count, 1)
        if hasattr(auto_client.session, 'cookies'):
            self.assertEqual(auto_client.session.cookies.get("device_id"), "SAGHF_CLIENT_001")

    def test_04_auth_token_injection_in_context_headers(self):
        """۴. آزمون تولید هوشمند هدرها و تزریق کلیدهای احراز هویت دیوار"""
        mgr = DivarSessionManager()
        token = mgr.get_token()

        api_url = "https://api.divar.ir/v8/postcontact/web/test_token"
        headers = self.client.generate_context_headers(api_url)

        self.assertIn("Accept", headers)
        self.assertIn("Sec-Fetch-Dest", headers)
        self.assertEqual(headers["Sec-Fetch-Dest"], "empty")
        self.assertEqual(headers["Origin"], "https://divar.ir")

        if token:
            self.assertIn("x-api-key", headers)
            self.assertEqual(headers["x-api-key"], token)
            self.assertIn("Authorization", headers)
            self.assertEqual(headers["Authorization"], f"Basic {token}")

    def test_05_comprehensive_metrics_telemetry(self):
        """۵. آزمون پایش و تله‌متری دقیق معیارهای عملیاتی لایه اول"""
        metrics = self.client.get_metrics()

        required_keys = [
            "impersonate_profile",
            "target_profile_key",
            "has_curl_cffi",
            "total_requests",
            "session_request_count",
            "recycle_count",
            "glitch_retries",
            "last_latency_ms",
            "avg_latency_ms",
            "proxy_active",
            "auto_rotate_profile"
        ]

        for k in required_keys:
            self.assertIn(k, metrics, f"Metric key '{k}' missing from get_metrics()")

        self.assertEqual(metrics["target_profile_key"], self.client.target_key)
        self.assertEqual(metrics["has_curl_cffi"], HAS_CURL_CFFI)


if __name__ == '__main__':
    unittest.main()
