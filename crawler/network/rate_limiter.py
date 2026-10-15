import time
import random
import threading
from urllib.parse import urlparse
from typing import Dict, Any, Optional

class TokenBucketRateLimiter:
    """
    الگوریتم سطل توکن (Token Bucket) مجهز به تاخیر رفتاری شبه‌انسانی (Gaussian Human Jitter)
    و کنترل ازدحام تطبیقی شبکه (AIMD Adaptive Congestion Control).
    
    جلوگیری از شناسایی الگوهای متناوب توسط WAF از طریق توزیع تاخیر گوسی (غیریکنواخت).
    """
    def __init__(
        self,
        capacity: float = 4.0,
        fill_rate: float = 1.5,
        min_jitter: float = 0.15,
        max_jitter: float = 0.65,
        jitter_strategy: str = "gaussian",
        gaussian_mu: Optional[float] = None,
        gaussian_sigma: Optional[float] = None,
        min_fill_rate: float = 0.3
    ):
        self.capacity = float(capacity)
        self.nominal_fill_rate = float(fill_rate)
        self.fill_rate = float(fill_rate)
        self.min_fill_rate = float(min_fill_rate)
        self.max_fill_rate = float(capacity * 1.5)

        self.tokens = float(capacity)
        self.last_fill_time = time.perf_counter()

        self.min_jitter = float(min_jitter)
        self.max_jitter = float(max_jitter)
        self.jitter_strategy = jitter_strategy

        # تنظیمات توزیع گوسی جهت شبیه‌سازی زمان تفکر انسان
        self.gaussian_mu = float(gaussian_mu if gaussian_mu is not None else (min_jitter + max_jitter) / 2.0)
        self.gaussian_sigma = float(gaussian_sigma if gaussian_sigma is not None else (max_jitter - min_jitter) / 4.0)

        # متغیرهای کنترل ازدحام AIMD
        self.consecutive_successes = 0
        self.throttle_events = 0
        self.total_acquired = 0
        self.total_waited_seconds = 0.0

        self.lock = threading.Lock()

    def calculate_jitter(self) -> float:
        """محاسبه تاخیر تصادفی با توزیع گوسی یا یکنواخت جهت شکستن تقارن و امضای ترافیک"""
        if self.jitter_strategy == "gaussian":
            val = random.gauss(self.gaussian_mu, self.gaussian_sigma)
            return max(self.min_jitter, min(self.max_jitter, val))
        else:
            return random.uniform(self.min_jitter, self.max_jitter)

    def acquire(self, tokens: int = 1, wait: bool = True) -> float:
        """
        دریافت توکن از سطل با محاسبه وقفه لازم و اعمال تاخیر رفتاری گوسی
        بازگرداندن کل زمان انتظار به ثانیه
        """
        with self.lock:
            now = time.perf_counter()
            elapsed = now - self.last_fill_time
            # پر شدن پیوسته سطل بر مبنای نرخ لحظه‌ای
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last_fill_time = now

            if self.tokens < tokens:
                wait_needed = (tokens - self.tokens) / self.fill_rate
                self.tokens = 0.0
            else:
                self.tokens -= tokens
                wait_needed = 0.0

            jitter = self.calculate_jitter()
            total_sleep = wait_needed + jitter

            self.total_acquired += tokens
            self.total_waited_seconds += total_sleep

        if wait and total_sleep > 0:
            time.sleep(total_sleep)

        return total_sleep

    def penalize(self, factor: float = 0.5) -> float:
        """
        کاهش ضربی نرخ تزریق توکن (Multiplicative Decrease) در مواجهه با خطای ریت‌لیمیت WAF
        و افزایش موقت زمان انتظار برای عبور از پنجره انسداد
        """
        with self.lock:
            self.throttle_events += 1
            self.consecutive_successes = 0
            self.fill_rate = max(self.min_fill_rate, self.fill_rate * factor)
            self.tokens = 0.0  # تخلیه سطل برای تحمیل مکث اولیه
            return self.fill_rate

    def on_success(self, step: float = 0.05) -> float:
        """
        افزایش جمعی نرخ توکن (Additive Increase) به ازای پاسخ‌های موفق مستمر تا رسیدن به نرخ نامی
        """
        with self.lock:
            self.consecutive_successes += 1
            if self.consecutive_successes >= 3 and self.fill_rate < self.nominal_fill_rate:
                self.fill_rate = min(self.nominal_fill_rate, self.fill_rate + step)
                self.consecutive_successes = 0
            return self.fill_rate

    def get_metrics(self) -> Dict[str, Any]:
        """دریافت آمارهای وضعیت و سلامت کنترل نرخ"""
        with self.lock:
            now = time.perf_counter()
            elapsed = now - self.last_fill_time
            current_tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            return {
                "capacity": self.capacity,
                "current_tokens": round(current_tokens, 2),
                "fill_rate": round(self.fill_rate, 2),
                "nominal_fill_rate": round(self.nominal_fill_rate, 2),
                "jitter_strategy": self.jitter_strategy,
                "gaussian_mu": round(self.gaussian_mu, 3),
                "gaussian_sigma": round(self.gaussian_sigma, 3),
                "throttle_events": self.throttle_events,
                "total_acquired": self.total_acquired,
                "total_waited_seconds": round(self.total_waited_seconds, 2)
            }


class DomainRateLimiterManager:
    """
    مدیریت سطل‌های توکن تفکیک‌شده بر اساس دامنه (Domain Partitioned Rate Limiting)
    تضمین عدم تداخل محدودیت‌های ترافیکی دیوار و شیپور با یکدیگر
    """
    def __init__(self):
        self._limiters: Dict[str, TokenBucketRateLimiter] = {
            "divar.ir": TokenBucketRateLimiter(
                capacity=4.0,
                fill_rate=1.8,
                min_jitter=0.20,
                max_jitter=0.65,
                jitter_strategy="gaussian",
                gaussian_mu=0.35,
                gaussian_sigma=0.08
            ),
            "sheypoor.com": TokenBucketRateLimiter(
                capacity=3.0,
                fill_rate=1.4,
                min_jitter=0.25,
                max_jitter=0.75,
                jitter_strategy="gaussian",
                gaussian_mu=0.45,
                gaussian_sigma=0.10
            ),
            "default": TokenBucketRateLimiter(
                capacity=4.0,
                fill_rate=2.0,
                min_jitter=0.15,
                max_jitter=0.50,
                jitter_strategy="gaussian"
            )
        }
        self.lock = threading.Lock()

    def _extract_domain(self, domain_or_url: str) -> str:
        """استخراج دامنه خالص از URL یا نام هاست"""
        if not domain_or_url:
            return "default"
        if "://" in domain_or_url:
            domain_or_url = urlparse(domain_or_url).netloc
        domain = domain_or_url.lower().split(':')[0]
        if "divar.ir" in domain:
            return "divar.ir"
        if "sheypoor.com" in domain:
            return "sheypoor.com"
        return "default"

    def get_limiter(self, domain_or_url: str) -> TokenBucketRateLimiter:
        """دریافت سطل توکن اختصاصی دامنه مورد نظر"""
        domain_key = self._extract_domain(domain_or_url)
        with self.lock:
            if domain_key not in self._limiters:
                self._limiters[domain_key] = TokenBucketRateLimiter(
                    capacity=4.0,
                    fill_rate=1.5,
                    min_jitter=0.2,
                    max_jitter=0.6
                )
            return self._limiters[domain_key]

    def acquire(self, domain_or_url: str, tokens: int = 1, wait: bool = True) -> float:
        """دریافت توکن برای یک دامنه مشخص"""
        limiter = self.get_limiter(domain_or_url)
        return limiter.acquire(tokens=tokens, wait=wait)

    def penalize(self, domain_or_url: str, factor: float = 0.5) -> float:
        """اعمال جریمه ریت‌لیمیت برای یک دامنه خاص"""
        limiter = self.get_limiter(domain_or_url)
        return limiter.penalize(factor=factor)

    def on_success(self, domain_or_url: str) -> float:
        """ثبت پاسخ موفق و بازیابی تدریجی نرخ برای دامنه"""
        limiter = self.get_limiter(domain_or_url)
        return limiter.on_success()

    def get_all_metrics(self) -> Dict[str, Any]:
        """گزارش آماری تمام سطل‌های توکن فعال"""
        with self.lock:
            return {domain: limiter.get_metrics() for domain, limiter in self._limiters.items()}


# نمونه سراسری جهت یکپارچگی خودکار در ماژول‌های شبکه
domain_rate_limiter = DomainRateLimiterManager()
