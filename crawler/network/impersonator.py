import random
import time
from typing import Dict, Any, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

CHROME_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

class TLSImpersonatorClient:
    """
    کلاینت ضد ردیابی و جعل اثر انگشت TLS و فریم‌های HTTP/2 با استفاده از curl_cffi
    مخصوص عبور از WAFهای کلودفلر و ابرآروان بدون باز کردن مرورگر سنگین
    """
    def __init__(self, impersonate: str = "chrome120", proxy: Optional[str] = None):
        self.impersonate_target = impersonate
        self.proxy = proxy
        self._init_session()

    def _init_session(self):
        if HAS_CURL_CFFI:
            self.session = cffi_requests.Session(impersonate=self.impersonate_target)
        else:
            import requests
            self.session = requests.Session()

    def get_headers(self, origin: str = "https://divar.ir", referer: str = "https://divar.ir/") -> Dict[str, str]:
        ua = random.choice(CHROME_USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Origin": origin,
            "Referer": referer,
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "DNT": "1"
        }

    def request(self, method: str, url: str, **kwargs) -> Any:
        timeout = kwargs.pop('timeout', 12)
        headers = kwargs.pop('headers', None)
        if not headers:
            headers = self.get_headers()

        proxies = kwargs.pop('proxies', None)
        if not proxies and self.proxy:
            proxies = {"http": self.proxy, "https": self.proxy}

        try:
            if HAS_CURL_CFFI:
                return self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=timeout,
                    proxies=proxies,
                    **kwargs
                )
            else:
                return self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    timeout=timeout,
                    proxies=proxies,
                    **kwargs
                )
        except Exception as e:
            # Recreate session on network break
            self._init_session()
            raise e

    def get(self, url: str, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request('POST', url, **kwargs)
