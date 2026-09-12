import time
import random
import threading
from typing import Dict, Any, Optional, Callable, List

class FallbackSolver:
    """
    سیستم بازیابی اضطراری و صف Dead Letter Queue (DLQ)
    تشخیص پاسخ‌های مسدودشده توسط WAF و اعمال عقب‌نشینی نمایی با Jitter (Exponential Backoff)
    """
    def __init__(self, max_retries: int = 3, base_delay: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.dlq: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

    def is_blocked_response(self, status_code: int, response_text: str = "") -> bool:
        """تشخیص خطاهای امنیتی یا چالش‌های WAF"""
        if status_code in [403, 429, 503]:
            return True
        lowered = response_text.lower() if response_text else ""
        if "captcha" in lowered or "turnstile" in lowered or "challenge" in lowered or "just a moment" in lowered:
            return True
        return False

    def execute_with_resilience(self, task_name: str, func: Callable, *args, **kwargs) -> Any:
        """اجرای درخواست با قابلیت تلاش مجدد هوشمند و تأخیر تصادفی"""
        attempt = 0
        while attempt < self.max_retries:
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                attempt += 1
                delay = (self.base_delay ** attempt) + random.uniform(0.5, 1.5)
                print(f"[FallbackSolver] خطا در {task_name} (تلاش {attempt}/{self.max_retries}): {e}. تاخیر {delay:.2f} ثانیه...")
                time.sleep(delay)

        # در صورت شکست تمام تلاش‌ها، تسک به DLQ اضافه می‌شود
        with self.lock:
            self.dlq.append({
                "task": task_name,
                "timestamp": time.time(),
                "args": str(args)[:200]
            })
            if len(self.dlq) > 200:
                self.dlq.pop(0)
        return None

fallback_solver = FallbackSolver()
