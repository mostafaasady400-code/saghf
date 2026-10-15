"""
Privacy & Data Confidentiality Engine for Saghf Platform.
Provides phone number masking, text sanitization, owner confidentiality preservation,
and contact access audit logging.
Zero-Mock Implementation.
"""

import re
import time
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class PrivacyManager:
    """
    موتور مدیریت حریم خصوصی و حفظ محرمانگی اطلاعات مالکین در سامانه سقف
    ارائه‌دهنده ماسک‌گذاری هوشمند ارقام، پالایش امن متون و ثبت رخدادهای دسترسی (Audit Trail)
    """

    DEFAULT_MASK_CHAR = "*"
    
    @classmethod
    def mask_phone(cls, phone: Optional[str], style: str = "asterisk") -> str:
        """
        ماسک‌گذاری استاندارد شماره موبایل جهت نمایش عمومی، پیام‌رسان‌های غیر VIP و لاگ‌ها
        مثال:
            '09123456789' -> '0912***6789' (asterisk)
            '09123456789' -> '0912-XXX-6789' (hyphen)
            '09123456789' -> '0912•••••89' (dot)
        """
        if not phone or not isinstance(phone, str):
            return ""

        digits = re.sub(r'\D', '', phone)
        if not digits:
            return phone

        # اگر فرمت شماره ایرانی ۱۱ رقمی باشد (09xxxxxxxxx)
        if len(digits) == 11 and digits.startswith('09'):
            prefix = digits[:4]  # 0912
            suffix = digits[7:]  # 6789
            
            if style == "hyphen":
                return f"{prefix}-XXX-{suffix}"
            elif style == "dot":
                return f"{prefix}••••{suffix}"
            else:  # default "asterisk"
                return f"{prefix}***{suffix}"

        # اگر فرمت شماره ۱۰ رقمی بدون صفر باشد (9xxxxxxxxx)
        elif len(digits) == 10 and digits.startswith('9'):
            prefix = '0' + digits[:3]
            suffix = digits[6:]
            if style == "hyphen":
                return f"{prefix}-XXX-{suffix}"
            elif style == "dot":
                return f"{prefix}••••{suffix}"
            else:
                return f"{prefix}***{suffix}"

        # برای سایر طول‌ها، ۴ رقم اول و ۲ رقم آخر حفظ شده و مابقی ماسک می‌شود
        if len(digits) > 6:
            masked_middle = cls.DEFAULT_MASK_CHAR * (len(digits) - 6)
            return f"{digits[:4]}{masked_middle}{digits[-2:]}"

        return cls.DEFAULT_MASK_CHAR * len(digits)

    @classmethod
    def unmask_phone(cls, phone: str, viewer_role: str = "guest") -> str:
        """
        ارزیابی مجوز مشاهده شماره تلفن کامل بر اساس نقش کاربر (RBAC):
        - نقش‌های مجاز: 'admin', 'vip_broker', 'verified_agent', 'system'
        - نقش‌های عمومی: 'guest', 'user', 'public'
        """
        # این متد در لایه دسترسی جهت تصمیم‌گیری بازگشایی شماره استفاده می‌شود
        allowed_roles = {'admin', 'vip_broker', 'verified_agent', 'system', 'superuser'}
        if viewer_role in allowed_roles:
            return phone
        return cls.mask_phone(phone)

    @classmethod
    def sanitize_text(cls, text: Optional[str], replacement: str = "[شماره تماس محرمانه]") -> str:
        """
        پالایش امن متون آگهی و لاگ‌های سرور از شماره‌های همراه خام
        جلوگیری از انتشار تصادفی اطلاعات تماس مالکین در متن توضیحات
        """
        if not text:
            return ""

        # استانداردسازی ارقام فارسی/عربی به لاتین جهت شناسایی مطمئن
        fa_digits = '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'
        en_digits = '01234567890123456789'
        trans = str.maketrans(fa_digits, en_digits)
        normalized = str(text).translate(trans)

        # الگوهای متنوع شماره موبایل ایران در متن (فاصله‌دار، خط تیره، پیش‌شماره بین‌المللی)
        phone_patterns = [
            r'(?:(?:\+98|0098|98)\s*9\d{9})',                 # بین‌المللی
            r'(?:0\s*9(?:\s*[\d\-\.\_\*]){8,12}\d)',          # 09 همراه با فاصله یا کاراکتر جداکننده
            r'(?<!\d)(?:09\d{9})(?!\d)',                      # 09xxxxxxxxx ساده
            r'(?<!\d)(?:9\d{9})(?!\d)',                       # 9xxxxxxxxx ۱۰ رقمی
        ]

        sanitized = normalized
        for pat in phone_patterns:
            matches = list(re.finditer(pat, sanitized))
            for m in reversed(matches):
                start, end = m.span()
                raw_match = m.group(0)
                # بررسی اینکه آیا واقعاً فرمت موبایل ایران است
                digits = re.sub(r'\D', '', raw_match)
                if (len(digits) == 11 and digits.startswith('09')) or (len(digits) == 10 and digits.startswith('9')) or (len(digits) >= 12 and '989' in digits):
                    masked_ver = cls.mask_phone(digits)
                    sanitized = sanitized[:start] + f"({masked_ver})" + sanitized[end:]

        return sanitized

    @classmethod
    def anonymize_owner_name(cls, full_name: Optional[str]) -> str:
        """
        ناشناس‌سازی هویت مالک بر اساس استانداردهای حفظ حریم خصوصی
        مثال: 'محمد رضایی فر' -> 'آقای رضایی (مالک)'
        """
        if not full_name or not full_name.strip():
            return "مالک محترم"

        name = full_name.strip()
        parts = name.split()
        if len(parts) >= 2:
            return f"جناب/سرکار {parts[-1]} (مالک)"
        return f"{name} (مالک)"

    @classmethod
    def create_access_audit_event(cls, 
                                  property_id: Any, 
                                  user_id: Any, 
                                  user_role: str, 
                                  action: str = "VIEW_CONTACT",
                                  ip_address: Optional[str] = None) -> Dict[str, Any]:
        """
        تولید رکورد ممیزی دسترسی به هویت مالکین (Audit Trail Event)
        مطابق با استانداردهای رگولاتوری حفظ محرمانگی داده‌ها
        """
        event = {
            'event_type': 'OWNER_CONTACT_ACCESS',
            'action': action,
            'property_id': property_id,
            'user_id': user_id,
            'user_role': user_role,
            'is_authorized': user_role in {'admin', 'vip_broker', 'verified_agent', 'system'},
            'ip_address': ip_address or '127.0.0.1',
            'timestamp': int(time.time()),
            'time_iso': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        }
        
        # ثبت در لاگ‌های امنیتی
        logger.info(f"[AUDIT] Privacy Access Event: Property {property_id} accessed by User {user_id} ({user_role}) - Authorized: {event['is_authorized']}")
        return event
