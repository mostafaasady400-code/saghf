"""
ماژول کنترل تاب‌آوری، طبقه‌بندی خطا و مدارشکن (Circuit Breaker & Error Classifier)
جهت مدیریت خودکار قطعی‌ها، پایان سهمیه، خطاهای احراز هویت و جابه‌جایی امن بین سطوح دستیار سقف
"""

import time
import logging
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class ErrorType(str, Enum):
    QUOTA_EXHAUSTED = "quota_exhausted"           # پایان سهمیه یا لیمیت توکن (HTTP 429)
    AUTH_ERROR = "auth_error"                     # کلید نامعتبر، لغوشده یا عدم دسترسی (HTTP 400/401/403)
    MODEL_NOT_FOUND = "model_not_found"           # مدل ناموجود یا منسوخ‌شده (HTTP 404)
    SERVICE_UNAVAILABLE = "service_unavailable"   # خطای سرور گوگل یا بار ترافیکی شدید (HTTP 503)
    TIMEOUT = "timeout"                           # پایان مهلت درخواست
    NETWORK_ERROR = "network_error"               # قطعی اتصال شبکه یا DNS
    CONTEXT_OVERFLOW = "context_overflow"         # سرریز طول کانتکست پرامپت
    MALFORMED_RESPONSE = "malformed_response"     # پاسخ ناقص یا نامعتبر
    TOOL_EXECUTION_ERROR = "tool_execution_error" # خطای اجرای ابزار
    UNKNOWN = "unknown"

class ErrorClassification:
    def __init__(
        self,
        error_type: ErrorType,
        message: str,
        is_retryable: bool,
        is_permanent: bool,
        failover_immediately: bool,
        http_status: Optional[int] = None
    ):
        self.error_type = error_type
        self.message = message
        self.is_retryable = is_retryable
        self.is_permanent = is_permanent
        self.failover_immediately = failover_immediately
        self.http_status = http_status

    def to_dict(self) -> Dict[str, Any]:
        return {
            'error_type': self.error_type.value,
            'message': self.message,
            'is_retryable': self.is_retryable,
            'is_permanent': self.is_permanent,
            'failover_immediately': self.failover_immediately,
            'http_status': self.http_status
        }

class ErrorClassifier:
    """طبقه‌بندی دقیق خطاهای API گوگل و ارتباطات شبکه بدون افشای کلیدها"""

    @classmethod
    def classify(cls, error_obj: Any, http_status: Optional[int] = None, response_text: str = "") -> ErrorClassification:
        err_str = str(error_obj).lower() if error_obj else ""
        resp_lower = response_text.lower() if response_text else ""
        combined = f"{err_str} {resp_lower}"

        # ۱. خطاهای احراز هویت (کلید نامعتبر، لغوشده یا خطای دسترسی)
        if (
            http_status in (401, 403) or
            'api_key_invalid' in combined or
            'invalid api key' in combined or
            'api key not valid' in combined or
            'key not valid' in combined or
            'permission_denied' in combined
        ):
            return ErrorClassification(
                error_type=ErrorType.AUTH_ERROR,
                message="کلید API نامعتبر، منقضی یا فاقد دسترسی است.",
                is_retryable=False,
                is_permanent=True,
                failover_immediately=True,
                http_status=http_status or 401
            )

        # ۲. پایان سهمیه یا لیمیت توکن
        if http_status == 429 or 'quota exceeded' in combined or 'resource_exhausted' in combined or 'rate limit' in combined or 'limit: 0' in combined:
            return ErrorClassification(
                error_type=ErrorType.QUOTA_EXHAUSTED,
                message="سقف درخواست یا سهمیه توکن مدل به پایان رسیده است.",
                is_retryable=False,
                is_permanent=True,
                failover_immediately=True,
                http_status=429
            )

        # ۳. مدل ناموجود یا منسوخ‌شده
        if http_status == 404 or 'is not found' in combined or 'no longer available' in combined or 'model_not_found' in combined:
            return ErrorClassification(
                error_type=ErrorType.MODEL_NOT_FOUND,
                message="مدل انتخابی در دسترس نیست یا برای این حساب منسوخ شده است.",
                is_retryable=False,
                is_permanent=True,
                failover_immediately=True,
                http_status=404
            )

        # ۴. سرریز پنجره متنی
        if 'max_tokens' in combined or 'context length' in combined or 'maximum context' in combined:
            return ErrorClassification(
                error_type=ErrorType.CONTEXT_OVERFLOW,
                message="طول مکالمه از حداکثر ظرفیت مدل فراتر رفته است.",
                is_retryable=False,
                is_permanent=False,
                failover_immediately=True,
                http_status=http_status
            )

        # ۵. خطای موقت سرور گوگل (High Demand Spikes / 503 / 500)
        if http_status in (500, 502, 503, 504) or 'high demand' in combined or 'unavailable' in combined:
            return ErrorClassification(
                error_type=ErrorType.SERVICE_UNAVAILABLE,
                message="سرور مدل به دلیل بار ترافیکی بالا موقتاً پاسخگو نیست (503).",
                is_retryable=True,
                is_permanent=False,
                failover_immediately=False,
                http_status=http_status or 503
            )

        # ۶. مهلت درخواست (Timeout)
        if 'timeout' in combined or 'timed out' in combined:
            return ErrorClassification(
                error_type=ErrorType.TIMEOUT,
                message="مهلت ارتباط با مدل زبانی به پایان رسید.",
                is_retryable=True,
                is_permanent=False,
                failover_immediately=False,
                http_status=408
            )

        # ۷. قطعی شبکه
        if 'connectionerror' in combined or 'connection refused' in combined or 'failed to establish a new connection' in combined:
            return ErrorClassification(
                error_type=ErrorType.NETWORK_ERROR,
                message="ارتباط شبکه با سرور خارجی برقرار نشد.",
                is_retryable=True,
                is_permanent=False,
                failover_immediately=True,
                http_status=None
            )

        # پیش‌فرض
        return ErrorClassification(
            error_type=ErrorType.UNKNOWN,
            message="خطای ناشناخته در پردازش مدل زبانی رخ داد.",
            is_retryable=False,
            is_permanent=False,
            failover_immediately=True,
            http_status=http_status
        )


class CircuitState(str, Enum):
    CLOSED = "closed"       # مدار بسته (سرویس سالم و آماده دریافت درخواست)
    OPEN = "open"           # مدار باز (سرویس موقتاً قطع و ایزوله‌شده، درخواست‌ها به پشتیبان می‌روند)
    HALF_OPEN = "half_open" # نیمه‌باز (ارسال درخواست آزمایشی جهت سنجش سلامت مجدد)

class CircuitBreaker:
    """
    مدارشکن مقاوم جهت جلوگیری از هدررفت منابع و انتظار کاربر هنگام اختلال سرویس
    """
    def __init__(
        self,
        name: str = "gemini_provider",
        failure_threshold: int = 3,
        recovery_timeout: float = 45.0,
        half_open_success_threshold: int = 1
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_error_reason: Optional[str] = None

    def can_attempt(self) -> bool:
        """بررسی اینکه آیا مجاز به ارسال درخواست به این مدل هستیم یا خیر"""
        now = time.time()
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (now - self.last_failure_time) >= self.recovery_timeout:
                logger.info(f"CircuitBreaker [{self.name}]: Transitioning from OPEN to HALF_OPEN for probing.")
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # در حالت نیمه‌باز فقط یک درخواست کاوشگر در هر لحظه فرستاده می‌شود
            return True

        return False

    def record_success(self):
        """ثبت موفقیت و بازنشانی وضعیت مدار"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_success_threshold:
                logger.info(f"CircuitBreaker [{self.name}]: Probe succeeded. Circuit is now CLOSED (healthy).")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.last_error_reason = None
        else:
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    def record_failure(self, error: ErrorClassification):
        """ثبت شکست و بررسی احتمال قطع موقت مدار"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.last_error_reason = error.message

        if error.is_permanent or self.failure_count >= self.failure_threshold or self.state == CircuitState.HALF_OPEN:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    f"CircuitBreaker [{self.name}]: Trip triggered! Circuit is now OPEN. "
                    f"Reason: {error.message} (Failures: {self.failure_count})"
                )
            self.state = CircuitState.OPEN

    def reset(self):
        """بازنشانی دستی مدار"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_error_reason = None

    def get_status(self) -> Dict[str, Any]:
        remaining_recovery = 0
        if self.state == CircuitState.OPEN and self.last_failure_time:
            elapsed = time.time() - self.last_failure_time
            remaining_recovery = max(0, int(self.recovery_timeout - elapsed))

        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'last_error': self.last_error_reason,
            'remaining_cooldown_sec': remaining_recovery
        }
