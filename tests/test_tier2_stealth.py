"""
Comprehensive Unit Tests for Tier 2: Playwright Headless Stealth Fallback.
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

from crawler.fallback_solver import PlaywrightStealthSolver, FallbackSolver, FallbackResponse


class TestTier2Stealth(unittest.TestCase):
    """
    اعتبارسنجی قابلیت‌های پیشرفته و معماری لایه دوم:
    - شناسایی و کانال مرورگر رسمی سیستم‌عامل
    - نفوذناپذیری اسکریپت‌های ضدردیابی اتوماسیون (Anti-CDP Stealth) داخل DOM
    - مسدودسازی ترافیک رسانه و شتاب‌دهی رندر (Route Interception)
    - الگوهای شناسایی چالش‌های WAF و Cloudflare
    - تاب‌آوری Failover و ثبت در صف خطای مرده (DLQ)
    - تله‌متری و پایش معیارهای عملیاتی لایه دوم
    """

    def setUp(self):
        self.solver = PlaywrightStealthSolver()
        self.solver._check_availability()
        self.fb = FallbackSolver(max_retries=2, base_delay=0.5)

    def test_01_availability_and_channel_discovery(self):
        """۱. آزمون شناسایی کانال مرورگر سیستم‌عامل و در دسترس بودن Playwright"""
        is_avail = self.solver._check_availability()
        self.assertTrue(is_avail, "Playwright with official browser must be available")
        self.assertIn(self.solver.channel, ['chrome', 'msedge', 'chromium'])

    def test_02_stealth_anti_cdp_evasion(self):
        """۲. آزمون ارزیابی متغیرهای ضدردیابی اتوماسیون در کانتکست مرورگر واقعی"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ch = self.solver.channel
            launch_kwargs = {
                "headless": True,
                "args": ['--disable-blink-features=AutomationControlled', '--no-sandbox']
            }
            if ch and ch != "chromium":
                launch_kwargs["channel"] = ch

            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context()
            context.add_init_script(self.solver.get_stealth_init_script())
            page = context.new_page()

            page.goto("data:text/html,<html><body><h1>Anti-CDP Probe</h1></body></html>")

            # 1. navigator.webdriver must be undefined
            webdriver_val = page.evaluate("navigator.webdriver")
            self.assertIsNone(webdriver_val, "navigator.webdriver must be undefined")

            # 2. window.chrome must exist and have runtime
            has_chrome = page.evaluate("!!window.chrome")
            self.assertTrue(has_chrome, "window.chrome must be emulated")

            has_runtime = page.evaluate("!!(window.chrome && window.chrome.runtime)")
            self.assertTrue(has_runtime, "window.chrome.runtime must be emulated")

            # 3. WebGL vendor spoofing
            vendor = page.evaluate("""(() => {
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                const ext = gl ? gl.getExtension('WEBGL_debug_renderer_info') : null;
                return (gl && ext) ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null;
            })()""")
            self.assertEqual(vendor, "Intel Inc.", "WebGL vendor should be spoofed to Intel Inc.")

            # 4. Plugins
            plugins_count = page.evaluate("navigator.plugins.length")
            self.assertGreater(plugins_count, 0, "navigator.plugins should not be empty")

            browser.close()

    def test_03_waf_and_challenge_detection(self):
        """۳. آزمون شناسایی الگوهای انسداد و چالش‌های امنیتی WAF"""
        # Status code tests
        self.assertTrue(self.fb.is_blocked_response(403))
        self.assertTrue(self.fb.is_blocked_response(429))
        self.assertTrue(self.fb.is_blocked_response(503))
        self.assertFalse(self.fb.is_blocked_response(200, "<html><body>Valid Content</body></html>"))

        # Cloudflare markers
        self.assertTrue(self.fb.is_blocked_response(200, "<html><title>Just a moment...</title></html>"))
        self.assertTrue(self.fb.is_blocked_response(200, "<div class='cf-challenge'></div>"))
        self.assertTrue(self.fb.is_blocked_response(200, "<div>Attention Required! | Cloudflare</div>"))

        # Iranian WAF / Captcha markers
        self.assertTrue(self.fb.is_blocked_response(200, "<div>کد امنیتی را وارد کنید</div>"))
        self.assertTrue(self.fb.is_blocked_response(200, "<span>ارسال بیش از حد مجاز</span>"))

    def test_04_fallback_response_interface(self):
        """۴. آزمون سازگاری اینترفیس شیء FallbackResponse با پاسخ‌های وب"""
        resp = FallbackResponse(status_code=200, text='{"key": "value"}', url="https://example.com")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.url, "https://example.com")
        self.assertIn("content-type", resp.headers)
        self.assertEqual(resp.json(), {"key": "value"})

    def test_05_dlq_recording_and_recovery(self):
        """۵. آزمون عملکرد صف خطای مرده (DLQ) در صورت شکست کامل"""
        initial_dlq_len = len(self.fb.dlq)

        def always_fails():
            raise ValueError("Simulated unrecoverable failure")

        res = self.fb.execute_with_resilience(
            task_name="DLQ_Test_Task",
            func=always_fails,
            fallback_url=None  # No fallback URL provided -> triggers DLQ
        )

        self.assertIsNone(res)
        self.assertEqual(len(self.fb.dlq), initial_dlq_len + 1)
        last_item = self.fb.dlq[-1]
        self.assertEqual(last_item["task"], "DLQ_Test_Task")
        self.assertIn("Simulated unrecoverable failure", last_item["error"])

    def test_06_metrics_and_telemetry(self):
        """۶. آزمون پایش و تله‌متری بلادرنگ وضعیت لایه دوم"""
        metrics = self.solver.get_metrics()
        required_keys = [
            "available", "channel", "invocations_count",
            "success_count", "failure_count", "last_render_time_ms",
            "avg_render_time_ms", "blocked_resources_count"
        ]
        for k in required_keys:
            self.assertIn(k, metrics)

        stats = self.fb.get_stats()
        self.assertIn("dlq_count", stats)
        self.assertIn("tier2_metrics", stats)


if __name__ == '__main__':
    unittest.main()
