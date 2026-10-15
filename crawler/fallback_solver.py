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
            from crawler.selenium_scraper.browser import get_chrome_binary_path
            
            # ۱. اولویت با باینری بومی و نصب‌شده کروم در سیستم
            native_chrome = get_chrome_binary_path()
            if native_chrome:
                try:
                    with sync_playwright() as p:
                        b = p.chromium.launch(
                            executable_path=native_chrome,
                            headless=True,
                            args=['--disable-blink-features=AutomationControlled']
                        )
                        b.close()
                    self._executable_path = native_chrome
                    self._chrome_channel = "chrome"
                    self._available = True
                    logger.info(f"[PlaywrightStealthSolver] مرورگر سیستم ({native_chrome}) جهت حل‌کننده Tier 2 فعال است.")
                    return True
                except Exception as ex:
                    logger.debug(f"[PlaywrightStealthSolver] خطا در راه‌اندازی با باینری کروم: {ex}")

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
        بارگذاری صفحه در مرورگر با اعمال اسکریپت‌های استلث یا اتصال سریع CDP به کروم زنده
        """
        self.invocations_count += 1
        t_start = time.perf_counter()

        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                if not self._check_availability():
                    logger.error("[PlaywrightStealthSolver] مرورگر سیستم در دسترس نیست.")
                    return None
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
                if getattr(self, '_executable_path', None):
                    launch_kwargs["executable_path"] = self._executable_path
                elif self._chrome_channel and self._chrome_channel not in ("chromium", "custom"):
                    launch_kwargs["channel"] = self._chrome_channel
                browser = p.chromium.launch(**launch_kwargs)
                try:
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

                    # مسدودسازی بهینه درخواست‌های رسانه‌ای سنگین جهت تسریع بارگذاری
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
                        try:
                            page.route("**/*", _route_filter)
                        except Exception:
                            pass

                    try:
                        page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                    except Exception as goto_err:
                        logger.warning(f"[PlaywrightStealthSolver] هشدار در ناوبری ({url}): {goto_err}")

                    # مکث کوتاه جهت رندر کامل State اولیه جاوااسکریپت
                    time.sleep(random.uniform(0.6, 1.1))
                    content = page.content()
                    try:
                        page.close()
                    except Exception:
                        pass
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass

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
        import requests as req_lib

        # ۱. تلاش نخست: اتصال مستقیم به Chrome CDP در صورت فعال بودن
        try:
            vr = req_lib.get('http://localhost:9222/json/version', timeout=1.5)
            if vr.status_code == 200:
                with sync_playwright() as p:
                    cdp_browser = p.chromium.connect_over_cdp('http://localhost:9222')
                    cdp_context = cdp_browser.contexts[0] if cdp_browser.contexts else cdp_browser.new_context()
                    cdp_page = cdp_context.new_page()
                    cdp_extracted = [None]

                    def on_cdp_resp(resp):
                        if 'contact_info_v2' in resp.url or 'postcontact' in resp.url:
                            try:
                                rjson = resp.json()
                                from crawler.contact_extractor import ContactExtractor
                                ph = ContactExtractor.extract_from_json_recursive(rjson)
                                if ph:
                                    cdp_extracted[0] = ph
                            except Exception:
                                pass

                    cdp_page.on('response', on_cdp_resp)
                    try:
                        cdp_page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                        try:
                            cdp_page.wait_for_selector('button', timeout=6000)
                        except Exception:
                            pass

                        for b in cdp_page.query_selector_all('button'):
                            try:
                                txt = b.inner_text().strip()
                                if 'برو به' in txt:
                                    continue
                                if 'اطلاعات تماس' in txt or 'تماس با آگهی‌دهنده' in txt:
                                    b.click()
                                    break
                            except Exception:
                                continue

                        cdp_page.wait_for_timeout(2500)
                        if cdp_extracted[0]:
                            cdp_page.close()
                            return cdp_extracted[0]

                        tel_a = cdp_page.query_selector('a[href^="tel:"]')
                        if tel_a:
                            href = tel_a.get_attribute('href') or ''
                            from crawler.contact_extractor import ContactExtractor
                            val = ContactExtractor.validate_and_normalize(href)
                            if val and val.get('is_valid'):
                                cdp_page.close()
                                return val['normalized']

                        # بررسی دیالوگ اطلاعات تماس بازشده
                        try:
                            dialog = cdp_page.query_selector('[role="dialog"]') or cdp_page.query_selector('.post-page__section--contact')
                            if dialog:
                                d_text = dialog.inner_text()
                                from crawler.contact_extractor import ContactExtractor
                                phone_from_dlg = ContactExtractor.extract_primary_phone(d_text)
                                if phone_from_dlg:
                                    val = ContactExtractor.validate_and_normalize(phone_from_dlg)
                                    if val and val.get('is_valid') and not val.get('is_suspicious'):
                                        cdp_page.close()
                                        return val['normalized']
                        except Exception:
                            pass
                    finally:
                        try:
                            cdp_page.close()
                        except Exception:
                            pass
        except Exception as cdp_err:
            logger.debug(f"[PlaywrightStealthSolver] رد CDP یا عدم دسترسی: {cdp_err}")

        # ۲. تلاش دوم: راه‌اندازی مرورگر ایزوله پنهان‌کار با کوکی‌های ذخیره‌شده
        try:
            with sync_playwright() as p:
                launch_kwargs = {
                    "headless": True,
                    "args": ['--disable-blink-features=AutomationControlled', '--no-sandbox']
                }
                if self._chrome_channel and self._chrome_channel != "chromium":
                    launch_kwargs["channel"] = self._chrome_channel

                browser = p.chromium.launch(**launch_kwargs)
                full_text = ""
                api_phone = [None]
                try:
                    context = browser.new_context(
                        viewport={'width': 1280, 'height': 800},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        locale='fa-IR'
                    )
                    if not cookies:
                        try:
                            storage_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_storage_state.json')
                            if os.path.exists(storage_file):
                                with open(storage_file, 'r', encoding='utf-8') as sf:
                                    sdata = json.load(sf)
                                    cookies = sdata.get('cookies', [])
                        except Exception:
                            pass

                    if cookies:
                        try:
                            context.add_cookies(cookies)
                        except Exception:
                            pass

                    context.add_init_script(self.get_stealth_init_script())
                    page = context.new_page()

                    # استراق‌سمع پاسخ شبکه اندپوینت اطلاعات تماس
                    def on_stealth_resp(resp):
                        if 'contact_info_v2' in resp.url or 'postcontact' in resp.url:
                            try:
                                rjson = resp.json()
                                from crawler.contact_extractor import ContactExtractor
                                ph = ContactExtractor.extract_from_json_recursive(rjson)
                                if ph:
                                    api_phone[0] = ph
                            except Exception:
                                pass

                    page.on('response', on_stealth_resp)

                    # جلوگیری از دانلود رسانه‌های سنگین
                    page.route('**/*.{png,jpg,jpeg,webp,svg,gif,woff,woff2}', lambda r: r.abort())
                    page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)

                    try:
                        page.wait_for_selector('button', timeout=6000)
                    except Exception:
                        pass

                    # یافتن و کلیک روی دکمه اطلاعات تماس (با رد لینک دسترسی‌پذیری "برو به اطلاعات تماس")
                    buttons = page.query_selector_all('button')
                    contact_btn = None
                    for b in buttons:
                        try:
                            txt = b.inner_text().strip()
                            if 'برو به' in txt:
                                continue
                            if txt == 'اطلاعات تماس' or any(k in txt for k in ['تماس با آگهی‌دهنده', 'اطلاعات تماس']):
                                contact_btn = b
                                break
                        except Exception:
                            continue

                    if contact_btn:
                        try:
                            contact_btn.click()
                            time.sleep(2.5)
                        except Exception as click_err:
                            logger.debug(f"[PlaywrightStealthSolver] خطا در کلیک دکمه تماس: {click_err}")

                    if api_phone[0]:
                        return api_phone[0]

                    tel_el = page.query_selector('a[href^="tel:"]')
                    if tel_el:
                        href = tel_el.get_attribute('href') or ''
                        from crawler.contact_extractor import ContactExtractor
                        val = ContactExtractor.validate_and_normalize(href)
                        if val and val.get('is_valid'):
                            return val['normalized']

                    # بررسی دیالوگ اطلاعات تماس بازشده
                    try:
                        dialog = page.query_selector('[role="dialog"]') or page.query_selector('.post-page__section--contact')
                        if dialog:
                            d_text = dialog.inner_text()
                            # اطمینان از این‌که دیالوگ درخواست ورود نیست
                            if 'ورود به حساب' not in d_text and 'کد تأیید' not in d_text:
                                from crawler.contact_extractor import ContactExtractor
                                phone_from_dlg = ContactExtractor.extract_primary_phone(d_text)
                                if phone_from_dlg:
                                    val = ContactExtractor.validate_and_normalize(phone_from_dlg)
                                    if val and val.get('is_valid') and not val.get('is_suspicious'):
                                        return val['normalized']
                    except Exception:
                        pass
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass

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
    def __init__(self, max_retries: int = 1, base_delay: float = 1.0):
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
            # اگر ویجت‌های آگهی در پاسخ موجود باشد، پاسخ به هیچ وجه مسدود نیست
            if 'post_row' in lowered or ('listwidgets' in lowered and '"listwidgets":[]' not in lowered):
                return False

            waf_markers = [
                'cf-challenge', 'cf-browser-verification', '<title>just a moment...',
                'attention required! | cloudflare', '<title>access denied</title>',
                'challenge-platform', 'turnstile-wrapper',
                'کد امنیتی', 'ارسال بیش از حد مجاز', 'human-challenge',
                'bot-detected', 'کد امنیتی را وارد کنید',
                '"hasssrunauthorizederror":true', '"hasssrunauthorizederror": true'
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

