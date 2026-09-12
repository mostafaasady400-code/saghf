import time
import random
import threading

class TokenBucketRateLimiter:
    """
    الگوریتم سطل توکن (Token Bucket) همراه با تاخیر تصادفی (Jitter)
    برای جلوگیری از ارسال ترافیک با ریتم مشخص و دور زدن شناسایی الگوهای ماشینی
    """
    def __init__(self, capacity: int = 4, fill_rate: float = 1.5, min_jitter: float = 0.2, max_jitter: float = 0.6):
        self.capacity = float(capacity)
        self.fill_rate = float(fill_rate) # توکن بر ثانیه
        self.tokens = float(capacity)
        self.last_fill_time = time.time()
        self.min_jitter = min_jitter
        self.max_jitter = max_jitter
        self.lock = threading.Lock()

    def acquire(self, tokens: int = 1):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_fill_time
            self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
            self.last_fill_time = now

            if self.tokens < tokens:
                wait_needed = (tokens - self.tokens) / self.fill_rate
                self.tokens = 0
            else:
                self.tokens -= tokens
                wait_needed = 0

        # اعمال وقفه با Jitter جهت رفتار شبه‌انسانی
        jitter = random.uniform(self.min_jitter, self.max_jitter)
        total_sleep = wait_needed + jitter
        if total_sleep > 0:
            time.sleep(total_sleep)
