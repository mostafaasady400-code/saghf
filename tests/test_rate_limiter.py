"""
Comprehensive Unit Tests for Rate Limiting & Behavioral Jitter Architecture.
Zero-Mock Implementation for Saghf Real Estate Platform.
"""

import sys
import os
import unittest
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from crawler.network.rate_limiter import TokenBucketRateLimiter, DomainRateLimiterManager, domain_rate_limiter


class TestRateLimiter(unittest.TestCase):
    """
    اعتبارسنجی قابلیت‌های پیشرفته کنترل نرخ و تاخیر رفتاری:
    - تخصیص توکن در حالت Burst و پر شدن مجدد
    - توزیع تاخیر گوسی شبه‌انسانی (Gaussian Human Jitter)
    - کنترل ازدحام تطبیقی AIMD (Penalize & Recovery)
    - تفکیک و ایزولاسیون دامنه‌ها در DomainRateLimiterManager
    - ایمنی همزمانی در محیط چندنخی (Thread Safety)
    - تله‌متری و سلامت عملیاتی
    """

    def setUp(self):
        self.limiter = TokenBucketRateLimiter(
            capacity=4.0,
            fill_rate=2.0,
            min_jitter=0.05,
            max_jitter=0.25,
            jitter_strategy="gaussian"
        )
        self.mgr = DomainRateLimiterManager()

    def test_01_token_bucket_burst_and_refill(self):
        """۱. آزمون مصرف انفجاری سطل توکن و پر شدن مجدد بر مبنای زمان پیوسته"""
        self.assertEqual(self.limiter.capacity, 4.0)
        self.assertEqual(self.limiter.tokens, 4.0)

        # مصرف ۱ توکن بدون انتظار فیزیکی
        wait1 = self.limiter.acquire(tokens=1, wait=False)
        self.assertLessEqual(self.limiter.tokens, 3.01)
        self.assertGreaterEqual(wait1, 0.05)

        # مصرف ۳ توکن دیگر تا تخلیه کامل سطل
        _ = self.limiter.acquire(tokens=3, wait=False)
        self.assertAlmostEqual(self.limiter.tokens, 0.0, places=1)

        # توکن بعدی نیازمند زمان پر شدن سطل است
        wait_extra = self.limiter.acquire(tokens=1, wait=False)
        self.assertGreater(wait_extra, 0.4, "Waiting time should be needed when bucket is depleted")

    def test_02_gaussian_jitter_distribution(self):
        """۲. آزمون اعتبار کران‌ها و میانگین توزیع تاخیر گوسی شبه‌انسانی"""
        g_limiter = TokenBucketRateLimiter(
            capacity=5.0,
            fill_rate=5.0,
            min_jitter=0.20,
            max_jitter=0.80,
            jitter_strategy="gaussian",
            gaussian_mu=0.50,
            gaussian_sigma=0.10
        )

        samples = [g_limiter.calculate_jitter() for _ in range(100)]
        for s in samples:
            self.assertGreaterEqual(s, 0.20, "Jitter should never be less than min_jitter")
            self.assertLessEqual(s, 0.80, "Jitter should never exceed max_jitter")

        mean_val = statistics.mean(samples)
        self.assertAlmostEqual(mean_val, 0.50, delta=0.08, msg="Sample mean should be close to gaussian mu")

    def test_03_aimd_adaptive_congestion_control(self):
        """۳. آزمون کنترل ازدحام تطبیقی AIMD (جریمه ضربی و ریکاوری جمعی)"""
        nominal = self.limiter.nominal_fill_rate
        self.assertEqual(self.limiter.fill_rate, nominal)

        # جریمه خطای ۴۲۹ (کاهش ۵۰ درصدی)
        penalized_rate = self.limiter.penalize(factor=0.5)
        self.assertEqual(penalized_rate, nominal * 0.5)
        self.assertEqual(self.limiter.throttle_events, 1)

        # جریمه تا حداقل مجاز (Clamp at min_fill_rate)
        self.limiter.penalize(factor=0.1)
        self.assertGreaterEqual(self.limiter.fill_rate, self.limiter.min_fill_rate)

        # ریکاوری پله‌ای با پاسخ‌های موفق
        initial_p = self.limiter.fill_rate
        for _ in range(3):
            self.limiter.on_success(step=0.2)
        self.assertGreater(self.limiter.fill_rate, initial_p)

    def test_04_domain_manager_partition_isolation(self):
        """۴. آزمون ایزولاسیون کامل سطل‌های توکن دیوار، شیپور و دامنه‌های متفرقه"""
        divar_l = self.mgr.get_limiter("https://divar.ir/s/tehran/buy-apartment")
        sheypoor_l = self.mgr.get_limiter("https://www.sheypoor.com/iran")
        default_l = self.mgr.get_limiter("https://example.com/api")

        self.assertIsNot(divar_l, sheypoor_l, "Divar and Sheypoor limiters must be distinct instances")
        self.assertIsNot(divar_l, default_l)

        # جریمه دیوار نباید نرخ شیپور را تغییر دهد
        original_sheypoor_rate = sheypoor_l.fill_rate
        self.mgr.penalize("https://divar.ir/s/tehran", factor=0.5)

        self.assertLess(divar_l.fill_rate, divar_l.nominal_fill_rate)
        self.assertEqual(sheypoor_l.fill_rate, original_sheypoor_rate)

    def test_05_concurrent_thread_safety(self):
        """۵. آزمون عملکرد بدون تداخل و ایمنی چندنخی تحت بار همزمان"""
        conc_limiter = TokenBucketRateLimiter(capacity=10.0, fill_rate=50.0, min_jitter=0.001, max_jitter=0.005)
        num_workers = 8
        tokens_per_worker = 10

        def worker_func(_):
            for _ in range(tokens_per_worker):
                conc_limiter.acquire(tokens=1, wait=False)
            return True

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            results = list(executor.map(worker_func, range(num_workers)))

        self.assertTrue(all(results))
        metrics = conc_limiter.get_metrics()
        self.assertEqual(metrics["total_acquired"], num_workers * tokens_per_worker)

    def test_06_metrics_telemetry(self):
        """۶. آزمون پایش و تله‌متری معیارهای سلامت کنترل نرخ"""
        metrics = self.limiter.get_metrics()
        expected_keys = [
            "capacity", "current_tokens", "fill_rate", "nominal_fill_rate",
            "jitter_strategy", "gaussian_mu", "gaussian_sigma",
            "throttle_events", "total_acquired", "total_waited_seconds"
        ]
        for k in expected_keys:
            self.assertIn(k, metrics)

        all_m = self.mgr.get_all_metrics()
        self.assertIn("divar.ir", all_m)
        self.assertIn("sheypoor.com", all_m)
        self.assertIn("default", all_m)


if __name__ == '__main__':
    unittest.main()
