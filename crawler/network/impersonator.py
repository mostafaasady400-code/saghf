import random
import time
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

# ==============================================================================
# ماتریس پروفایل‌های اثر انگشت TLS و هدرهای متناظر (Synced Profile Matrix)
# هماهنگی دقیق بین نسخه دست‌تکانی TLS (JA3/JA4) و Client Hints در لایه HTTP/2
# ==============================================================================
FINGERPRINT_PROFILES: Dict[str, Dict[str, Any]] = {
    "chrome124": {
        "impersonate": "chrome124",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_platform": '"Windows"',
        "sec_ch_ua_mobile": "?0"
    },
    "chrome120": {
        "impersonate": "chrome120",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec_ch_ua_platform": '"Windows"',
        "sec_ch_ua_mobile": "?0"
    },
    "chrome131": {
        "impersonate": "chrome131",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"Windows"',
        "sec_ch_ua_mobile": "?0"
    }
}


class TLSImpersonatorClient:
    """
    کلاینت تندرو، ضد ردیابی و جعل اثر انگشت TLS و فریم‌های HTTP/2 (Tier 1 High-Throughput)
    مجهز به:
    - همگام‌سازی کامل اثر انگشت TLS و Client Hints (JA3/JA4 Spoofer)
    - چرخش پویای اثر انگشت (Dynamic Entropy & Profile Rotation)
    - تولیدکننده تطبیقی هدرها متناسب با بستر هدف و احراز هویت (Context-Aware Synthesizer)
    - مدیریت چرخه حیات نشست، انتقال کوکی‌ها و بازنشانی ادواری (Stateful CookieJar Preservation)
    - میکرو-تلاش مجدد با تاخیر شبه‌انسانی (Transient Glitch Retry & Jitter)
    """

    def __init__(
        self,
        impersonate: str = "chrome124",
        proxy: Optional[str] = None,
        max_requests_per_session: int = 60,
        auto_rotate_profile: bool = False
    ):
        self.target_key = impersonate if impersonate in FINGERPRINT_PROFILES else "chrome124"
        self.profile = FINGERPRINT_PROFILES[self.target_key]
        self.impersonate_target = self.profile["impersonate"]
        self.proxy = proxy
        self.max_requests_per_session = max_requests_per_session
        self.auto_rotate_profile = auto_rotate_profile

        self.session_request_count = 0
        self.total_requests = 0
        self.recycle_count = 0
        self.glitch_retries = 0
        self.total_latency_ms = 0.0
        self.last_latency_ms = 0.0
        self.session = None

        self._init_session(preserve_cookies=False)

    def _init_session(self, preserve_cookies: bool = True):
        """راه‌اندازی نشست با اثر انگشت انتخابی و نگهداری/انتقال CookieJar"""
        old_cookies = None
        if preserve_cookies and self.session and hasattr(self.session, 'cookies'):
            old_cookies = self.session.cookies

        if HAS_CURL_CFFI:
            self.session = cffi_requests.Session(impersonate=self.impersonate_target)
        else:
            import requests
            self.session = requests.Session()

        if old_cookies and hasattr(self.session, 'cookies'):
            try:
                self.session.cookies.update(old_cookies)
            except Exception:
                pass

        self.session_request_count = 0

    def rotate_profile(self, target_key: Optional[str] = None):
        """چرخش دینامیک اثر انگشت برای افزایش آنتروپی و ممانعت از شناسایی الگوی ثابت شبکه"""
        if target_key and target_key in FINGERPRINT_PROFILES:
            self.target_key = target_key
        else:
            available = [k for k in FINGERPRINT_PROFILES if k != self.target_key]
            self.target_key = random.choice(available) if available else "chrome124"

        self.profile = FINGERPRINT_PROFILES[self.target_key]
        self.impersonate_target = self.profile["impersonate"]
        self._init_session(preserve_cookies=True)

    def generate_context_headers(
        self,
        url: str,
        method: str = 'GET',
        custom_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        تولید هوشمند و خودکار هدرهای منطبق با مرورگر واقعی بر اساس URL هدف
        تفکیک بین صفحات HTML وب و اندپوینت‌های REST API + تزریق توکن احراز هویت در صورت وجود
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        is_api = 'api.' in domain or '/api/' in parsed.path or 'postcontact' in parsed.path

        headers: Dict[str, str] = {
            "User-Agent": self.profile["user_agent"],
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Sec-Ch-Ua": self.profile["sec_ch_ua"],
            "Sec-Ch-Ua-Mobile": self.profile["sec_ch_ua_mobile"],
            "Sec-Ch-Ua-Platform": self.profile["sec_ch_ua_platform"],
            "DNT": "1"
        }

        if is_api:
            # هدرهای درخواست‌های API و XHR/Fetch
            headers.update({
                "Accept": "application/json, text/plain, */*",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site" if ('api.' in domain and 'divar.ir' in domain) else "same-origin",
            })
            if 'divar.ir' in domain:
                headers["Origin"] = "https://divar.ir"
                headers["Referer"] = "https://divar.ir/"
            elif 'sheypoor.com' in domain:
                headers["Origin"] = "https://www.sheypoor.com"
                headers["Referer"] = "https://www.sheypoor.com/"
        else:
            # هدرهای ناوبری و صفحات HTML اصلی وب
            headers.update({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin" if ('/s/' in parsed.path or '/v/' in parsed.path) else "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            })
            if 'divar.ir' in domain:
                headers["Referer"] = "https://divar.ir/s/tehran/real-estate"
            elif 'sheypoor.com' in domain:
                headers["Referer"] = "https://www.sheypoor.com/s/tehran/real-estate"

        # تزریق توکن احراز هویت دیوار در صورت وجود برای دسترسی به شماره تماس‌ها
        if 'divar.ir' in domain:
            try:
                from crawler.divar_session_manager import DivarSessionManager
                api_key = DivarSessionManager.get_open_platform_key()
                auth_tok = DivarSessionManager.get_token()
                if api_key:
                    headers["x-api-key"] = api_key
                    headers["Authorization"] = f"Bearer {api_key}"
                elif auth_tok:
                    headers["Authorization"] = f"Bearer {auth_tok}"
            except Exception:
                pass

        # اعمال هدرهای سفارشی با حفظ یکپارچگی هدرهای اثر انگشت
        if custom_headers:
            headers.update(custom_headers)

        return headers

    def get_headers(self, origin: str = "https://divar.ir", referer: str = "https://divar.ir/") -> Dict[str, str]:
        """سازگاری با فراخوانی‌های قدیمی"""
        return self.generate_context_headers(origin)

    def request(self, method: str, url: str, **kwargs) -> Any:
        """
        ارسال درخواست HTTP امن با جعل کامل اثر انگشت، بازنشانی دوره‌ای نشست و میکرو-تلاش مجدد
        """
        # بازنشانی دوره‌ای نشست جهت جلوگیری از ردگیری توسط سامانه‌های WAF
        if self.session_request_count >= self.max_requests_per_session:
            logger.debug(f"[TLSImpersonator] بازنشانی دوره‌ای نشست پس از {self.session_request_count} درخواست.")
            self.recycle_count += 1
            if self.auto_rotate_profile:
                self.rotate_profile()
            else:
                self._init_session(preserve_cookies=True)

        timeout = kwargs.pop('timeout', 14)
        custom_headers = kwargs.pop('headers', None)
        headers = self.generate_context_headers(url, method=method, custom_headers=custom_headers)

        proxies = kwargs.pop('proxies', None)
        if not proxies and self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}

        max_glitch_retries = 2
        for attempt in range(max_glitch_retries + 1):
            t_start = time.time()
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=timeout,
                    proxies=proxies,
                    **kwargs
                )
                self.last_latency_ms = (time.time() - t_start) * 1000
                self.total_latency_ms += self.last_latency_ms
                self.total_requests += 1
                self.session_request_count += 1
                return resp

            except Exception as e:
                self.last_latency_ms = (time.time() - t_start) * 1000
                self.glitch_retries += 1
                if attempt < max_glitch_retries:
                    # تاخیر تصادفی کوتاه در صورت خطای گذرا
                    delay = random.uniform(0.2, 0.5) * (attempt + 1)
                    time.sleep(delay)
                    # بازنشانی سوکت نشست با حفظ کوکی‌ها
                    self._init_session(preserve_cookies=True)
                else:
                    self._init_session(preserve_cookies=True)
                    raise e

    def get(self, url: str, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request('POST', url, **kwargs)

    def get_metrics(self) -> Dict[str, Any]:
        """دریافت آمارهای کارایی و مانیتورینگ لایه اول"""
        avg_latency = (self.total_latency_ms / self.total_requests) if self.total_requests > 0 else 0.0
        return {
            "impersonate_profile": self.impersonate_target,
            "target_profile_key": self.target_key,
            "has_curl_cffi": HAS_CURL_CFFI,
            "total_requests": self.total_requests,
            "session_request_count": self.session_request_count,
            "recycle_count": self.recycle_count,
            "glitch_retries": self.glitch_retries,
            "last_latency_ms": round(self.last_latency_ms, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "proxy_active": bool(self.proxy),
            "auto_rotate_profile": self.auto_rotate_profile
        }

