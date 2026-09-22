import time
import random
import re
import threading
import logging
from typing import Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)

class FallbackResponse:
    """ساختار پاسخ شبیه‌سازی‌شده لایه دوم (Tier 2) مرورگر جهت سازگاری کامل با کلاینت‌های HTTP و پارسرها"""
    def __init__(self, status_code: int = 200, text: str = "", url: str = ""):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = {"content-type": "text/html; charset=utf-8"}

    def json(self):
        import json
        return json.loads(self.text)


class PlaywrightStealthSolver:
    """
    موتور حل‌کننده اضطراری مرورگر پنهان‌کار لایه دوم (Tier 2 Stealth Headless Browser)
    استفاده از کروم رسمی سیستم‌عامل با تکنیک‌های پیشرفته ضدردیابی اتوماسیون (Anti-CDP Stealth Evasions)
    و شتاب‌دهی رندر با مسدودسازی هوشمند ترافیک رسانه‌ای غیرضروری (Resource Route Interception)
    """
    def __init__(self):
        self._available = None
        self._chrome_channel = None
        self.invocations_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_render_time_ms = 0.0
        self.last_render_time_ms = 0.0
        self.blocked_resources_count = 0

    @property
    def channel(self) -> str:
        """کانال مرورگر معتبر سیستم‌عامل (chrome یا msedge)"""
        if self._chrome_channel is None:
            self._check_availability()
        return self._chrome_channel or "chrome"

    def _check_availability(self) -> bool:
        """بررسی در دسترس بودن مرورگر سیستم‌عامل برای Playwright"""
        if self._available is not None:
            return self._available

        try:
            from playwright.sync_api import sync_playwright
            for ch in ['chrome', 'msedge']:
                try:
                    with sync_playwright() as p:
                        b = p.chromium.launch(
                            channel=ch,
                            headless=True,
                            args=['--disable-blink-features=AutomationControlled']
                        )
                        b.close()
                    self._chrome_channel = ch
                    self._available = True
                    logger.info(f"[PlaywrightStealthSolver] مرورگر سیستم ({ch}) جهت حل‌کننده Tier 2 فعال است.")
                    return True
                except Exception:
                    continue

            # تلاش برای مرورگر پیش‌فرض Chromium
            try:
                with sync_playwright() as p:
                    b = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
                    b.close()
                self._chrome_channel = "chromium"
                self._available = True
                return True
            except Exception:
                pass

            self._available = False
            return False
        except Exception as e:
            logger.warning(f"[PlaywrightStealthSolver] کتابخانه Playwright در دسترس نیست: {e}")
            self._available = False
            return False

    @staticmethod
    def get_stealth_init_script() -> str:
        """
        اسکریپت جامع تزریق در چرخه حیات DOM جهت پنهان‌سازی اثر انگشت‌های CDP و اتوماسیون
        شامل خنثی‌سازی navigator.webdriver، شبیه‌سازی WebGL، تصحیح Permissions و شیء window.chrome
        """
        return """
            // 1. خنثی‌سازی کامل اثر انگشت WebDriver
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            try {
                delete navigator.__proto__.webdriver;
            } catch (e) {}

            // 2. بازسازی کامل ساختار شیء رسمی window.chrome
            window.chrome = {
                app: {
                    isInstalled: false,
                    InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                    RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
                },
                runtime: {
                    OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                    PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                    PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                    PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
                    RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
                },
                csi: function() { return {}; },
                loadTimes: function() { return {}; }
            };

            // 3. تصحیح استعلام مجوز اعلانات (Permissions Query Evasion)
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // 4. جعل سخت‌افزاری WebGL (جایگزینی SwiftShader با پردازنده گرافیکی واقعی اینتل/انویدیا)
            const getParameterProto = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }
                if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                    return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return getParameterProto.apply(this, [parameter]);
            };
            if (typeof WebGL2RenderingContext !== 'undefined') {
                const getParameterProto2 = WebGL2RenderingContext.prototype.getParameter;
                WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                    return getParameterProto2.apply(this, [parameter]);
                };
            }

            // 5. متغیرهای محیطی و سخت‌افزاری مرورگر واقعی
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['fa-IR', 'fa', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
        """

    def fetch_page_html(
        self,
        url: str,
        wait_until: str = 'domcontentloaded',
        timeout_ms: int = 25000,
        block_media: bool = True,
        cookies: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        """
        بارگذاری صفحه در مرورگر هدلس با اعمال اسکریپت‌های استلث، مسدودسازی ترافیک رسانه و استخراج HTML
        """
        if not self._check_availability():
            logger.error("[PlaywrightStealthSolver] مرورگر سیستم در دسترس نیست.")
            return None

        self.invocations_count += 1
        t_start = time.perf_counter()

        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                launch_kwargs = {
                    "headless": True,
                    "args": [
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-infobars',
                        '--disable-gpu'
                    ]
                }
                if self._chrome_channel and self._chrome_channel != "chromium":
                    launch_kwargs["channel"] = self._chrome_channel

                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    locale='fa-IR'
                )

                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception as e:
                        logger.warning(f"[PlaywrightStealthSolver] خطا در تزریق کوکی: {e}")

                context.add_init_script(self.get_stealth_init_script())
                page = context.new_page()

                # مسدودسازی بهینه درخواست‌های رسانه‌ای سنگین جهت تسریع ۷۰ درصدی بارگذاری
                if block_media:
                    def _route_filter(route):
                        req = route.request
                        res_type = req.resource_type
                        url_lowered = req.url.lower()
                        media_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.woff', '.woff2', '.ttf', '.mp4')
                        if res_type in ('image', 'media', 'font') or any(url_lowered.endswith(ext) for ext in media_extensions):
                            self.blocked_resources_count += 1
                            route.abort()
                        else:
                            route.continue_()
                    page.route("**/*", _route_filter)

                try:
                    page.goto(url, wait_until='commit', timeout=timeout_ms)
                    try:
                        page.wait_for_load_state(wait_until, timeout=8000)
                    except Exception:
                        pass
                except Exception as goto_err:
                    logger.warning(f"[PlaywrightStealthSolver] هشدار در ناوبری ({url}): {goto_err}")

                # مکث کوتاه ارگونومیک جهت رندر کامل State اولیه جاوااسکریپت
                time.sleep(random.uniform(0.4, 0.8))
                content = page.content()
                browser.close()

                elapsed_ms = (time.perf_counter() - t_start) * 1000
                self.last_render_time_ms = elapsed_ms
                self.total_render_time_ms += elapsed_ms
                self.success_count += 1
                return content

        except Exception as ex:
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            self.last_render_time_ms = elapsed_ms
            self.failure_count += 1
            logger.warning(f"[PlaywrightStealthSolver] خطا در رندر صفحه ({url}): {ex}")
            return None

    def fetch_contact_phone(
        self,
        url: str,
        timeout_ms: int = 25000,
        cookies: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        """
        ناوبری تعاملی به صفحه آگهی، کلیک روی دکمه اطلاعات تماس و استخراج شماره تلفن همراه مالک با Regex
        """
        if not self._check_availability():
            return None

        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                launch_kwargs = {
                    "headless": True,
                    "args": ['--disable-blink-features=AutomationControlled', '--no-sandbox']
                }
                if self._chrome_channel and self._chrome_channel != "chromium":
                    launch_kwargs["channel"] = self._chrome_channel

                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    locale='fa-IR'
                )
                if cookies:
                    try:
                        context.add_cookies(cookies)
                    except Exception:
                        pass

                context.add_init_script(self.get_stealth_init_script())
                page = context.new_page()

                # جلوگیری از دانلود رسانه‌های سنگین
                page.route('**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2}', lambda r: r.abort())
                page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)

                try:
                    page.wait_for_selector('button', timeout=6000)
                except Exception:
                    pass

                # یافتن و کلیک روی دکمه اطلاعات تماس
                buttons = page.query_selector_all('button')
                contact_btn = None
                for b in buttons:
                    try:
                        txt = b.inner_text().strip()
                        if any(k in txt for k in ['اطلاعات تماس', 'تماس با آگهی‌دهنده', 'تماس']):
                            contact_btn = b
                            break
                    except Exception:
                        continue

                if contact_btn:
                    try:
                        contact_btn.click()
                        time.sleep(1.2)
                    except Exception as click_err:
                        logger.debug(f"[PlaywrightStealthSolver] خطا در کلیک دکمه تماس: {click_err}")

                # استخراج شماره تلفن همراه از متن یا مدال بازشده
                full_text = page.content()
                browser.close()

                # جستجوی الگوی شماره تلفن‌های ایرانی
                persian_digits = {'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'}
                normalized = "".join(persian_digits.get(ch, ch) for ch in full_text)
                match = re.search(r'09\d{9}', normalized)
                if match:
                    return match.group(0)

                return None

        except Exception as ex:
            logger.warning(f"[PlaywrightStealthSolver] خطا در استخراج شماره تماس ({url}): {ex}")
            return None

    def get_metrics(self) -> Dict[str, Any]:
        """دریافت آمارهای تله‌متری و سلامت عملیاتی لایه دوم"""
        avg_render = (self.total_render_time_ms / self.invocations_count) if self.invocations_count > 0 else 0.0
        return {
            "available": self._check_availability(),
            "channel": self._chrome_channel,
            "invocations_count": self.invocations_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_render_time_ms": round(self.last_render_time_ms, 2),
            "avg_render_time_ms": round(avg_render, 2),
            "blocked_resources_count": self.blocked_resources_count
        }


class FallbackSolver:
    """
    سیستم بازیابی اضطراری و صف Dead Letter Queue (DLQ)
    تشخیص پاسخ‌های مسدودشده توسط WAF، اعمال عقب‌نشینی نمایی با Jitter و سوئیچ خودکار به Tier 2
    """
    def __init__(self, max_retries: int = 3, base_delay: float = 1.5):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.dlq: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.stealth_browser = PlaywrightStealthSolver()

    def is_blocked_response(self, status_code: int, response_text: str = "") -> bool:
        """تشخیص خطاهای امنیتی، ریت‌لیمیت یا چالش‌های واقعی WAF (کلودفلر، دیوار و شیپور)"""
        if status_code in [403, 429, 503]:
            return True
        if status_code == 200:
            lowered = response_text.lower() if response_text else ""
            waf_markers = [
                'cf-challenge', 'cf-browser-verification', '<title>just a moment...',
                'attention required! | cloudflare', '<title>access denied</title>',
                'challenge-platform', 'turnstile-wrapper',
                'کد امنیتی', 'ارسال بیش از حد مجاز', 'human-challenge',
                'bot-detected', 'کد امنیتی را وارد کنید'
            ]
            if any(m in lowered for m in waf_markers):
                return True
            return False
        return False

    def execute_with_resilience(
        self,
        task_name: str,
        func: Callable,
        *args,
        fallback_url: Optional[str] = None,
        cookies: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> Any:
        """اجرای درخواست با قابلیت تلاش مجدد هوشمند، عقب‌نشینی نمایی و سوئیچ خودکار به لایه دوم استلث"""
        attempt = 0
        last_exception = None

        while attempt < self.max_retries:
            try:
                result = func(*args, **kwargs)
                if hasattr(result, 'status_code'):
                    if self.is_blocked_response(result.status_code, getattr(result, 'text', '')):
                        logger.warning(f"[FallbackSolver] وضعیت مسدودی ({result.status_code}) در {task_name}. تلاش مجدد...")
                        attempt += 1
                        delay = (self.base_delay ** attempt) + random.uniform(0.3, 0.8)
                        time.sleep(delay)
                        continue
                return result
            except Exception as e:
                last_exception = e
                attempt += 1
                delay = (self.base_delay ** attempt) + random.uniform(0.3, 0.8)
                logger.info(f"[FallbackSolver] تلاش {attempt}/{self.max_retries} در {task_name} با خطا مواجه شد: {e}. تاخیر {delay:.2f}s")
                time.sleep(delay)

        # در صورت عدم موفقیت در لایه اول، ورود به لایه دوم (Tier 2: Stealth Browser Solver)
        target_url = fallback_url or (args[0] if args and isinstance(args[0], str) and args[0].startswith('http') else kwargs.get('url'))
        if target_url:
            logger.info(f"[FallbackSolver] 🛡️ ورود به لایه دوم (Tier 2 Playwright Stealth) برای {task_name} -> {target_url}")
            html = self.stealth_browser.fetch_page_html(target_url, cookies=cookies)
            if html:
                logger.info(f"[FallbackSolver] ✅ لایه دوم موفق شد: استخراج {len(html):,} بایت از مرورگر پنهان‌کار.")
                return FallbackResponse(status_code=200, text=html, url=target_url)

        # در صورت شکست قطعی، ثبت در صف خطای مرده (DLQ)
        with self.lock:
            self.dlq.append({
                "task": task_name,
                "timestamp": time.time(),
                "error": str(last_exception) if last_exception else "WAF_BLOCKED",
                "url": target_url or "N/A"
            })
            if len(self.dlq) > 200:
                self.dlq.pop(0)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """آمارهای زنده صف DLQ و وضعیت لایه دوم"""
        with self.lock:
            return {
                "dlq_count": len(self.dlq),
                "max_retries": self.max_retries,
                "base_delay": self.base_delay,
                "tier2_metrics": self.stealth_browser.get_metrics()
            }

    def get_dlq(self) -> List[Dict[str, Any]]:
        """دریافت رکوردهای صف خطای مرده"""
        with self.lock:
            return list(self.dlq)

    def clear_dlq(self) -> None:
        """پاک‌سازی صف خطای مرده"""
        with self.lock:
            self.dlq.clear()


fallback_solver = FallbackSolver()

