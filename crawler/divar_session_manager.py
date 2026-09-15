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
            with open(TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump({
                    'token': token.strip(),
                    'phone': phone.strip(),
                    'saved_at': str(os.path.getmtime(TOKEN_FILE_PATH) if os.path.exists(TOKEN_FILE_PATH) else 0)
                }, f, ensure_ascii=False, indent=2)
            print(f"[DivarSessionManager] توکن دیوار با موفقیت ذخیره شد.")
            return True
        except Exception as e:
            print(f"[DivarSessionManager] خطا در ذخیره توکن: {e}")
            return False

    @classmethod
    def is_authenticated(cls) -> bool:
        """بررسی وجود توکن فعال"""
        return bool(cls.get_token())

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
        """جستجوی بازگشتی در کل ساختار داده جهت یافتن هرگونه شماره موبایل معتبر ایران"""
        import re
        from crawler.owner_filter import convert_persian_words_to_digits

        if isinstance(data, dict):
            # 1. Direct key checks
            for key in ['phone_number', 'phone', 'mobile', 'call_number']:
                if key in data and data[key]:
                    val = str(data[key])
                    m = re.search(r'09\d{9}', val)
                    if m:
                        return m.group(0)
            
            # 2. Check widget action payload specifically
            action = data.get('action', {})
            payload = action.get('payload', {}) if isinstance(action, dict) else {}
            for key in ['phone_number', 'phone']:
                if key in payload and payload[key]:
                    m = re.search(r'09\d{9}', str(payload[key]))
                    if m:
                        return m.group(0)

            # 3. Recurse into all dict values
            for v in data.values():
                res = cls._extract_phone_from_json(v)
                if res:
                    return res

        elif isinstance(data, list):
            for item in data:
                res = cls._extract_phone_from_json(item)
                if res:
                    return res

        elif isinstance(data, str):
            # Check string for standard or persian digits 09...
            p_text = convert_persian_words_to_digits(data)
            m = re.search(r'09\d{9}', p_text)
            if m:
                return m.group(0)

        return None

