import os
import json
import requests
from typing import Optional, Dict, Any

TOKEN_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_token.json')
STORAGE_STATE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_storage_state.json')
COOKIES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_cookies.json')

class DivarSessionManager:
    """
    مدیریت توکن و نشست احراز هویت در دیوار
    جهت استخراج ۱۰۰٪ رسمی و خودکار شماره تماس واقعی مالکان از طریق API دیوار:
    https://api.divar.ir/v8/postcontact/web/contact_info/{token}
    """

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json'
    }

    @classmethod
    def get_open_platform_key(cls) -> Optional[str]:
        """خواندن کلید OpenAPI پلتفرم باز دیوار"""
        env_key = os.environ.get('DIVAR_API_KEY') or os.environ.get('DIVAR_OPEN_PLATFORM_KEY')
        if env_key:
            return env_key.strip()
        if os.path.exists(TOKEN_FILE_PATH):
            try:
                with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    key = data.get('api_key') or data.get('open_platform_key')
                    if key:
                        return key.strip()
            except Exception as e:
                print(f"[DivarSessionManager] خطا در خواندن کلید OpenAPI: {e}")
        return None

    @classmethod
    def save_open_platform_key(cls, api_key: str) -> bool:
        """ذخیره کلید پلتفرم باز دیوار"""
        try:
            data = {}
            if os.path.exists(TOKEN_FILE_PATH):
                try:
                    with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data['api_key'] = api_key.strip()
            with open(TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[DivarSessionManager] کلید OpenAPI دیوار با موفقیت ذخیره شد.")
            return True
        except Exception as e:
            print(f"[DivarSessionManager] خطا در ذخیره کلید OpenAPI: {e}")
            return False

    @classmethod
    def fetch_finder_posts(cls, endpoint: str = "https://open-api.divar.ir/v2/open-platform/finder/post", 
                           category: str = "buy-apartment", city: str = "tehran", limit: int = 20) -> Dict[str, Any]:
        """
        فراخوانی رسمی اندپوینت پلتفرم باز دیوار:
        https://open-api.divar.ir/v2/open-platform/finder/post
        جهت استخراج مستقیم آگهی‌های واقعی همراه با شماره تماس واقعی
        """
        api_key = cls.get_open_platform_key()
        auth_token = cls.get_token()

        headers = dict(cls.HEADERS)
        if api_key:
            headers['x-api-key'] = api_key
            headers['x-access-token'] = api_key
            headers['Authorization'] = f"Bearer {api_key}"
        elif auth_token:
            headers['Authorization'] = f"Bearer {auth_token}"

        params = {
            'city': city,
            'category': category,
            'limit': limit
        }

        # تست همزمان با GET و POST مطابق مستندات پلتفرم باز
        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                return {'success': True, 'data': resp.json(), 'endpoint': endpoint}
            elif resp.status_code == 405: # Method Not Allowed -> تست POST
                resp_post = requests.post(endpoint, headers=headers, json=params, timeout=10)
                if resp_post.status_code == 200:
                    return {'success': True, 'data': resp_post.json(), 'endpoint': endpoint}
            return {
                'success': False, 
                'status_code': resp.status_code, 
                'message': resp.text[:250],
                'endpoint': endpoint
            }
        except Exception as e:
            return {'success': False, 'status_code': 0, 'message': str(e), 'endpoint': endpoint}

    @classmethod
    def get_token(cls) -> Optional[str]:
        """خواندن توکن ذخیره شده از فایل محلی، storage_state، یا متغیر محیطی"""
        env_token = os.environ.get('DIVAR_AUTH_TOKEN')
        if env_token:
            return env_token.strip()

        if os.path.exists(TOKEN_FILE_PATH):
            try:
                with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    token = data.get('token')
                    if token:
                        return token.strip()
            except Exception as e:
                print(f"[DivarSessionManager] خطا در خواندن فایل توکن: {e}")

        if os.path.exists(STORAGE_STATE_PATH):
            try:
                with open(STORAGE_STATE_PATH, 'r', encoding='utf-8') as f:
                    sdata = json.load(f)
                    for c in sdata.get('cookies', []):
                        if c.get('name') in ('sAccessToken', 'token', 'access_token', 'auth'):
                            return str(c.get('value', '')).strip()
            except Exception:
                pass

        if os.path.exists(COOKIES_PATH):
            try:
                with open(COOKIES_PATH, 'r', encoding='utf-8') as f:
                    cdata = json.load(f)
                    if isinstance(cdata, dict):
                        for k in ('token', 'sAccessToken', 'auth', 'access_token'):
                            if cdata.get(k):
                                return str(cdata[k]).strip()
            except Exception:
                pass

        return None

    @classmethod
    def get_cookies_dict(cls) -> Dict[str, str]:
        """استخراج تمام کوکی‌های نشست از storage_state یا cookies.json"""
        cookies = {}
        if os.path.exists(STORAGE_STATE_PATH):
            try:
                with open(STORAGE_STATE_PATH, 'r', encoding='utf-8') as f:
                    sdata = json.load(f)
                    for c in sdata.get('cookies', []):
                        dom = str(c.get('domain', '')).lower()
                        if 'divar.ir' in dom and c.get('name') and c.get('value'):
                            cookies[c['name']] = str(c['value'])
            except Exception:
                pass

        if not cookies and os.path.exists(COOKIES_PATH):
            try:
                with open(COOKIES_PATH, 'r', encoding='utf-8') as f:
                    cdata = json.load(f)
                    if isinstance(cdata, dict):
                        for k, v in cdata.items():
                            if v:
                                cookies[k] = str(v)
            except Exception:
                pass

        return cookies

    @classmethod
    def refresh_session(cls) -> bool:
        """ارسال درخواست ریفرش سشن به دیوار و به‌روزرسانی توکن و فایل محلی storage_state"""
        cookies = cls.get_cookies_dict()
        rt = cookies.get('refresh_token') or cookies.get('sRefreshToken')
        if not rt:
            # بررسی فایل ذخیره توکن
            if os.path.exists(TOKEN_FILE_PATH):
                try:
                    with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                        tdata = json.load(f)
                        rt = tdata.get('refresh_token')
                except Exception:
                    pass

        if not rt:
            return False

        # ۱. فراخوانی اندپوینت رسمی v5 ریفرش احراز هویت دیوار
        try:
            headers = dict(cls.HEADERS)
            headers['Referer'] = 'https://divar.ir/'
            res = requests.post(
                'https://api.divar.ir/v5/auth/refresh',
                json={'refresh_token': rt},
                headers=headers,
                timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                new_access_token = data.get('access_token')
                if new_access_token:
                    cls.save_token(new_access_token)
                    cookies['sAccessToken'] = new_access_token
                    cookies['refresh_token'] = rt
                    cls.save_cookies_dict(cookies)
                    print(f"[DivarSessionManager] ✅ توکن دسترسی دیوار با موفقیت تمدید شد.")
                    return True
        except Exception as e:
            print(f"[DivarSessionManager] هشدار در ریفرش با اندپوینت v5: {e}")

        # ۲. فال‌بک به اندپوینت v8
        try:
            s = requests.Session()
            s.headers.update(dict(cls.HEADERS))
            s.headers.update({'Referer': 'https://divar.ir/', 'Accept-Language': 'fa'})
            for k, v in cookies.items():
                s.cookies.set(k, v, domain='.divar.ir', path='/')
            s.cookies.set('sRefreshToken', rt, domain='.divar.ir', path='/v8/authenticate/session/refresh')

            res = s.post('https://api.divar.ir/v8/authenticate/session/refresh', json={}, timeout=10)
            if res.status_code == 200:
                for sc in s.cookies:
                    cookies[sc.name] = sc.value
                cls.save_cookies_dict(cookies)
                return True
        except Exception:
            pass

        return False

    @classmethod
    def save_cookies_dict(cls, cookies_dict: Dict[str, str]) -> bool:
        """ذخیره دیکشنری کوکی‌ها در فایل‌های storage_state و cookies.json"""
        if not cookies_dict:
            return False
        try:
            existing = {'cookies': []}
            if os.path.exists(STORAGE_STATE_PATH):
                try:
                    with open(STORAGE_STATE_PATH, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except Exception:
                    existing = {'cookies': []}
            cookie_map = {c['name']: c for c in existing.get('cookies', [])}
            for k, v in cookies_dict.items():
                if v:
                    path = '/v8/authenticate/session/refresh' if k == 'sRefreshToken' else '/'
                    cookie_map[k] = {
                        'name': k,
                        'value': str(v).strip(),
                        'domain': '.divar.ir',
                        'path': path,
                        'secure': True,
                        'httpOnly': True if 'Token' in k else False,
                        'sameSite': 'Lax'
                    }
            existing['cookies'] = list(cookie_map.values())
            with open(STORAGE_STATE_PATH, 'w', encoding='utf-8') as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)

            with open(COOKIES_PATH, 'w', encoding='utf-8') as f:
                json.dump(cookies_dict, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[DivarSessionManager] خطا در ذخیره کوکی‌ها: {e}")
            return False

    @classmethod
    def save_token(cls, token: str, phone: str = '') -> bool:
        """ذخیره توکن احراز هویت در فایل محلی و بروزرسانی sAccessToken در storage_state"""
        try:
            existing_data = {}
            if os.path.exists(TOKEN_FILE_PATH):
                try:
                    with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}
            clean_token = token.strip()
            existing_data['token'] = clean_token
            existing_data['phone'] = phone.strip()
            existing_data['saved_at'] = str(os.path.getmtime(TOKEN_FILE_PATH) if os.path.exists(TOKEN_FILE_PATH) else 0)
            with open(TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)

            # همگام‌سازی فوری با storage_state
            cls.save_cookies_dict({'sAccessToken': clean_token})
            print(f"[DivarSessionManager] توکن دیوار با موفقیت ذخیره و همگام شد.")
            return True
        except Exception as e:
            print(f"[DivarSessionManager] خطا در ذخیره توکن: {e}")
            return False

    @classmethod
    def is_authenticated(cls) -> bool:
        """بررسی وجود توکن یا کلید فعال"""
        return bool(cls.get_token() or cls.get_open_platform_key() or bool(cls.get_cookies_dict()))

    @classmethod
    def request_sms_code(cls, phone_number: str) -> Dict[str, Any]:
        """
        ارسال کد پیامکی ورود به شماره موبایل کاربر جهت فعال‌سازی نشست استخراج شماره‌ها
        """
        clean_phone = phone_number.strip()
        if not clean_phone.startswith('09') or len(clean_phone) != 11:
            return {'success': False, 'message': 'شماره موبایل وارد شده باید ۱۱ رقمی و با ۰۹ شروع شود.'}

        url = "https://api.divar.ir/v5/auth/authenticate"
        payload = {"phone": clean_phone}
        try:
            resp = requests.post(url, json=payload, headers=cls.HEADERS, timeout=10)
            if resp.status_code == 200:
                return {
                    'success': True,
                    'message': 'کد تأیید ورود از سوی دیوار به شماره شما پیامک شد. لطفاً کد را وارد نمایید.'
                }
            else:
                return {
                    'success': False,
                    'message': f'خطا در ارسال کد از سوی دیوار: {resp.text}'
                }
        except Exception as e:
            return {'success': False, 'message': f'خطای ارتباط با سرور دیوار: {str(e)}'}

    @classmethod
    def confirm_sms_code(cls, phone_number: str, code: str) -> Dict[str, Any]:
        """
        تأیید کد پیامکی و دریافت توکن و کوکی‌های نشست دیوار
        """
        url = "https://api.divar.ir/v5/auth/confirm"
        payload = {
            "phone": phone_number.strip(),
            "code": code.strip()
        }
        try:
            resp = requests.post(url, json=payload, headers=cls.HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                token = data.get('token')
                new_cookies = {}
                for c in resp.cookies:
                    new_cookies[c.name] = c.value
                if token:
                    new_cookies['sAccessToken'] = token
                    cls.save_token(token, phone=phone_number)
                if new_cookies:
                    cls.save_cookies_dict(new_cookies)
                return {
                    'success': True,
                    'message': 'نشست دیوار با موفقیت فعال شد! از این پس شماره واقعی تمامی آگهی‌ها به صورت خودکار استخراج می‌شود.'
                }
            return {
                'success': False,
                'message': f'کد وارد شده نامعتبر است یا منقضی شده است.'
            }
        except Exception as e:
            return {'success': False, 'message': f'خطای ارتباط با سرور دیوار: {str(e)}'}

    @classmethod
    def fetch_contact_phone(
        cls,
        post_token: str,
        custom_token: Optional[str] = None,
        custom_cookies: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        استخراج شماره تماس واقعی مالک با استفاده از توکن و کوکی‌های احراز هویت دیوار
        پشتیبانی از اندپوینت‌های جدید و قدیم (contact_info_v2)، فال‌بک تعاملی DOM و نرمال‌سازی با ContactExtractor
        """
        clean_token = str(post_token).replace('divar_', '').strip()
        if '/' in clean_token:
            clean_token = clean_token.rstrip('/').split('/')[-1]

        if not clean_token:
            return None

        cookies = dict(custom_cookies) if custom_cookies else cls.get_cookies_dict()
        auth_token = custom_token if custom_token else cls.get_token()

        if auth_token and not cookies.get('sAccessToken'):
            cookies['sAccessToken'] = auth_token

        access_token = cookies.get('sAccessToken') or auth_token

        # ۱. تلاش با اندپوینت رسمی جاری دیوار (contact_info_v2 با POST و هدر احراز هویت)
        if cookies or access_token:
            try:
                s = requests.Session()
                s.headers.update(dict(cls.HEADERS))
                s.headers.update({
                    'Referer': f'https://divar.ir/v/{clean_token}',
                    'Origin': 'https://divar.ir',
                    'Accept-Language': 'fa',
                    'Accept': 'application/json, text/plain, */*'
                })
                if access_token:
                    s.headers['authorization'] = f'Bearer {access_token}'
                    s.headers['x-access-token'] = access_token

                for k, v in cookies.items():
                    s.cookies.set(k, v, domain='.divar.ir', path='/')

                v2_url = f"https://api.divar.ir/v8/postcontact/web/contact_info_v2/{clean_token}"
                resp = s.post(v2_url, json={}, timeout=8)
                if resp.status_code in {401, 403}:
                    # تلاش برای ریفرش توکن و ارسال مجدد
                    if cls.refresh_session():
                        cookies = cls.get_cookies_dict()
                        access_token = cookies.get('sAccessToken') or auth_token
                        if access_token:
                            s.headers['authorization'] = f'Bearer {access_token}'
                            s.headers['x-access-token'] = access_token
                        for k, v in cookies.items():
                            s.cookies.set(k, v, domain='.divar.ir', path='/')
                        resp = s.post(v2_url, json={}, timeout=8)

                if resp.status_code == 200:
                    data = resp.json()
                    # در صورت عدم وجود چالش امنیتی (hip_action: CAPTCHA)، استخراج شماره
                    if isinstance(data, dict) and 'hip_action' not in data:
                        phone = cls._extract_phone_from_json(data)
                        if phone:
                            from crawler.contact_extractor import ContactExtractor
                            val = ContactExtractor.validate_and_normalize(phone)
                            if val and val.get('is_valid') and not val.get('is_suspicious'):
                                print(f"[DivarSessionManager] 🎯 شماره از اندپوینت v2 استخراج شد ({clean_token}): {val['normalized']}")
                                return val['normalized']
                        # آگهی چت‌محور یا بدون شماره عمومی است؛ نیازی به فال‌بک‌های سنگین نیست
                        return None
                elif resp.status_code == 404:
                    # آگهی در دیوار حذف یا منقضی شده است
                    return None
            except Exception as e:
                print(f"[DivarSessionManager] هشدار در استخراج اندپوینت v2: {e}")

        # ۲. بررسی اندپوینت‌های سنتی در صورت وجود auth_token
        if auth_token:
            legacy_endpoints = [
                f"https://api.divar.ir/v8/postcontact/web/contact_info/{clean_token}",
                f"https://api.divar.ir/v8/postcontact/contact_info/{clean_token}",
                f"https://api.divar.ir/v5/posts/{clean_token}/contact"
            ]
            auth_variants = [
                {'Authorization': f"Bearer {auth_token}"},
                {'Authorization': f"Basic {auth_token}"},
                {'Authorization': auth_token}
            ]
            c_cookies = dict(cookies)
            c_cookies.setdefault('token', auth_token)

            for url in legacy_endpoints:
                for auth_hdr in auth_variants:
                    headers = dict(cls.HEADERS)
                    headers.update(auth_hdr)
                    try:
                        resp = requests.get(url, headers=headers, cookies=c_cookies, timeout=6)
                        if resp.status_code == 200:
                            data = resp.json()
                            phone = cls._extract_phone_from_json(data)
                            if phone:
                                from crawler.contact_extractor import ContactExtractor
                                val = ContactExtractor.validate_and_normalize(phone)
                                if val and val.get('is_valid') and not val.get('is_suspicious'):
                                    print(f"[DivarSessionManager] 🎯 شماره واقعی استخراج شد ({clean_token}): {val['normalized']}")
                                    return val['normalized']
                        elif resp.status_code in {401, 403}:
                            continue
                    except Exception as e:
                        print(f"[DivarSessionManager] هشدار در استخراج شماره آگهی {clean_token}: {e}")

        # ۳. فال‌بک تعاملی پنهان‌کار DOM (PlaywrightStealthSolver)
        try:
            from crawler.fallback_solver import PlaywrightStealthSolver
            solver = PlaywrightStealthSolver()
            if solver._check_availability():
                ad_url = f"https://divar.ir/v/{clean_token}"
                pw_cookies = [{'name': k, 'value': str(v), 'domain': '.divar.ir', 'path': '/'} for k, v in cookies.items()] if cookies else None
                phone = solver.fetch_contact_phone(ad_url, timeout_ms=18000, cookies=pw_cookies)
                if phone:
                    from crawler.contact_extractor import ContactExtractor
                    val = ContactExtractor.validate_and_normalize(phone)
                    if val and val.get('is_valid') and not val.get('is_suspicious'):
                        print(f"[DivarSessionManager] 🎯 شماره از کلیک تعاملی استخراج شد ({clean_token}): {val['normalized']}")
                        return val['normalized']
        except Exception as e:
            print(f"[DivarSessionManager] هشدار در اجرای فال‌بک تعاملی: {e}")

        return None

    @classmethod
    def _extract_phone_from_json(cls, data: Any) -> Optional[str]:
        """جستجوی بازگشتی در کل ساختار داده جهت یافتن هرگونه شماره موبایل معتبر ایران با ContactExtractor"""
        from crawler.contact_extractor import ContactExtractor
        return ContactExtractor.extract_from_json_recursive(data)

