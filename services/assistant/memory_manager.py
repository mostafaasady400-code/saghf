"""
مدیریت حافظهٔ پایدار، نشست‌ها و هماهنگی زمینه‌ها (Assistant Session & Memory Manager)
مدیریت نیازمندی‌های ساختاریافته مشتری، نگهداری تاریخچه، اعمال اصلاحات مرحله‌ای (Delta Updates)
و ایزولاسیون کامل بین نشست‌های کاربران
"""

import time
import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

@dataclass
class CustomerCriteria:
    """نیازمندی‌های ساختاریافته مشتری مستقل از ارائه‌دهنده مدل"""
    deal_type: str = "any"           # sale, rent, any
    city: str = "تهران"
    districts: List[str] = field(default_factory=list)
    min_budget: int = 0
    max_budget: int = 0              # برای خرید
    max_deposit: int = 0             # رهن
    max_rent: int = 0                # اجاره ماهانه
    min_area: int = 0
    max_area: int = 0
    rooms: int = 0
    has_parking: Optional[bool] = None
    has_elevator: Optional[bool] = None
    has_warehouse: Optional[bool] = None
    has_balcony: Optional[bool] = None
    semantic_desires: List[str] = field(default_factory=list) # موارد کیفی مانند "نورگیر", "آرام", "ویو ابدی"
    client_name: Optional[str] = None
    client_phone: Optional[str] = None

    def update_delta(self, delta: Dict[str, Any]):
        """اعمال اصلاحات تدریجی بدون پاک شدن سایر مشخصات"""
        for k, v in delta.items():
            if v is not None and v != "" and v != 0 and v != [] and hasattr(self, k):
                if k == 'districts' and isinstance(v, list) and v:
                    # ادغام هوشمند محله‌ها
                    for dist in v:
                        if dist not in self.districts:
                            self.districts.append(dist)
                elif k == 'semantic_desires' and isinstance(v, list) and v:
                    for s in v:
                        if s not in self.semantic_desires:
                            self.semantic_desires.append(s)
                else:
                    setattr(self, k, v)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def has_sufficient_info(self) -> bool:
        """بررسی اینکه آیا حداقل اطلاعات برای جستجوی معنی‌دار ملک وجود دارد"""
        has_deal = self.deal_type in ['sale', 'rent']
        has_loc = len(self.districts) > 0
        has_money = (self.max_budget > 0) or (self.max_deposit > 0) or (self.max_rent > 0)
        return has_deal and (has_loc or has_money)

    def get_missing_clarification_prompt(self) -> Optional[str]:
        """تولید سوال کوتاه و هدفمند در صورت ابهام اطلاعات اساسی"""
        if self.deal_type not in ['sale', 'rent']:
            return "قصد خرید آپارتمان دارید یا رهن و اجاره؟"
        if not self.districts:
            deal_name = "خرید" if self.deal_type == 'sale' else "رهن و اجاره"
            return f"برای {deal_name}، کدام محله یا منطقه تهران مد نظرتان است؟"
        if self.deal_type == 'sale' and self.max_budget == 0:
            return "حدود سقف بودجه مد نظرتان برای خرید چقدر است؟"
        if self.deal_type == 'rent' and self.max_deposit == 0 and self.max_rent == 0:
            return "حداکثر ودیعه و اجاره ماهانه‌ای که در نظر دارید چقدر است؟"
        return None


class SessionMemory:
    """حافظه یک نشست کاربری مشخص"""
    def __init__(self, session_id: str, max_history_turns: int = 30):
        self.session_id = session_id
        self.max_history_turns = max_history_turns
        self.criteria = CustomerCriteria()
        self.history: List[Dict[str, str]] = []
        self.scheduled_visit_keys: Set[str] = set() # کلیدهای یکتای قرار بازدید جهت جلوگیری از عملیات تکراری
        self.last_matched_properties: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.summary_note: str = ""

    def touch(self):
        self.updated_at = time.time()

    def add_turn(self, role: str, content: str):
        self.touch()
        clean_content = (content or '').strip()
        if clean_content:
            self.history.append({'role': role, 'content': clean_content})
            # مدیریت سرریز تاریخچه: اگر از سقف بگذرد، ترن‌های ابتدایی را فشرده می‌کنیم
            if len(self.history) > self.max_history_turns:
                overflow_count = len(self.history) - self.max_history_turns
                removed = self.history[:overflow_count]
                self.history = self.history[overflow_count:]
                # ثبت یادداشت خلاصه جهت حفظ زمینه بدون مصرف توکن
                topics = [m['content'][:30] for m in removed if m.get('role') == 'user']
                if topics:
                    self.summary_note = f"مکالمه قبلی درباره: {', '.join(topics)}"

    def get_recent_history(self, limit: int = 20) -> List[Dict[str, str]]:
        return self.history[-limit:]

    def is_visit_already_scheduled(self, idempotency_key: str) -> bool:
        return idempotency_key in self.scheduled_visit_keys

    def mark_visit_scheduled(self, idempotency_key: str):
        self.scheduled_visit_keys.add(idempotency_key)
        self.touch()

    def reset(self):
        """پاکسازی کامل حافظه این نشست"""
        self.criteria = CustomerCriteria()
        self.history.clear()
        self.scheduled_visit_keys.clear()
        self.last_matched_properties.clear()
        self.summary_note = ""
        self.touch()


class AssistantMemoryManager:
    """
    مدیر متمرکز و ایزوله حافظه مکالمات برای تمامی کاربران سامانه سقف
    """
    _sessions: Dict[str, SessionMemory] = {}
    SESSION_TTL_SECONDS = 86400 * 2 # ۲ روز اعتبار

    @classmethod
    def get_or_create(cls, session_id: Optional[str] = None) -> SessionMemory:
        clean_id = (session_id or 'default_web_session').strip()
        cls._cleanup_expired()

        if clean_id not in cls._sessions:
            cls._sessions[clean_id] = SessionMemory(session_id=clean_id)
        return cls._sessions[clean_id]

    @classmethod
    def reset_session(cls, session_id: str) -> bool:
        clean_id = (session_id or '').strip()
        if clean_id in cls._sessions:
            cls._sessions[clean_id].reset()
            return True
        return False

    @classmethod
    def get_all_active_sessions_count(cls) -> int:
        return len(cls._sessions)

    @classmethod
    def _cleanup_expired(cls):
        now = time.time()
        expired = [sid for sid, sess in cls._sessions.items() if (now - sess.updated_at) > cls.SESSION_TTL_SECONDS]
        for sid in expired:
            del cls._sessions[sid]
