import os
import json
import requests
from typing import Optional, Dict, Any

TOKEN_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_token.json')

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
        """خواندن توکن ذخیره شده از فایل محلی یا متغیر محیطی"""
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
        return None

    @classmethod
    def save_token(cls, token: str, phone: str = '') -> bool:
        """ذخیره توکن احراز هویت در فایل محلی"""
        try:
            existing_data = {}
            if os.path.exists(TOKEN_FILE_PATH):
                try:
                    with open(TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}
            existing_data['token'] = token.strip()
            existing_data['phone'] = phone.strip()
            existing_data['saved_at'] = str(os.path.getmtime(TOKEN_FILE_PATH) if os.path.exists(TOKEN_FILE_PATH) else 0)
            with open(TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            print(f"[DivarSessionManager] توکن دیوار با موفقیت ذخیره شد.")
            return True
        except Exception as e:
            print(f"[DivarSessionManager] خطا در ذخیره توکن: {e}")
            return False

    @classmethod
    def is_authenticated(cls) -> bool:
        """بررسی وجود توکن یا کلید فعال"""
        return bool(cls.get_token() or cls.get_open_platform_key())


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
        تأیید کد پیامکی و دریافت توکن نشست دیوار
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
                if token:
                    cls.save_token(token, phone=phone_number)
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
    def fetch_contact_phone(cls, post_token: str) -> Optional[str]:
        """
        استخراج شماره تماس واقعی مالک با استفاده از توکن احراز هویت دیوار
        پشتیبانی از چندین اندپوینت، هدرهای مختلف و جستجوی عمیق در پاسخ JSON دیوار
        """
        auth_token = cls.get_token()
        if not auth_token:
            return None

        clean_token = str(post_token).replace('divar_', '').strip()
        if '/' in clean_token:
            clean_token = clean_token.rstrip('/').split('/')[-1]

        if not clean_token:
            return None

        endpoints = [
            f"https://api.divar.ir/v8/postcontact/web/contact_info/{clean_token}",
            f"https://api.divar.ir/v8/postcontact/contact_info/{clean_token}",
            f"https://api.divar.ir/v5/posts/{clean_token}/contact"
        ]

        auth_variants = [
            {'Authorization': f"Basic {auth_token}"},
            {'Authorization': f"Bearer {auth_token}"},
            {'Authorization': auth_token}
        ]

        cookies = {'token': auth_token, 'did': auth_token}

        for url in endpoints:
            for auth_hdr in auth_variants:
                headers = dict(cls.HEADERS)
                headers.update(auth_hdr)
                try:
                    resp = requests.get(url, headers=headers, cookies=cookies, timeout=6)
                    if resp.status_code == 200:
                        data = resp.json()
                        phone = cls._extract_phone_from_json(data)
                        if phone:
                            print(f"[DivarSessionManager] 🎯 شماره واقعی استخراج شد ({clean_token}): {phone}")
                            return phone
                    elif resp.status_code == 403:
                        # Continue to next auth variant or endpoint
                        continue
                except Exception as e:
                    print(f"[DivarSessionManager] هشدار در استخراج شماره آگهی {clean_token}: {e}")

        return None

    @classmethod
    def _extract_phone_from_json(cls, data: Any) -> Optional[str]:
        """جستجوی بازگشتی در کل ساختار داده جهت یافتن هرگونه شماره موبایل معتبر ایران با ContactExtractor"""
        from crawler.contact_extractor import ContactExtractor
        return ContactExtractor.extract_from_json_recursive(data)

