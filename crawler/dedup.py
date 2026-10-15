import threading
from typing import Set, Optional

class DeduplicationEngine:
    """
    موتور حذف تکراری‌ها در زمان O(1) مبتنی بر Hash Set بهینه‌شده
    با قابلیت بارگذاری اولیه شناسه‌ها از دیتابیس و جلوگیری از کوئری‌های تکراری دیسک
    """
    def __init__(self):
        self._seen_tokens: Set[str] = set()
        self.lock = threading.Lock()
        self._is_initialized = False

    def initialize_from_db(self, db_model):
        """بارگذاری شناسه‌های موجود در پایگاه داده سقف برای ممانعت از کراول مجدد"""
        with self.lock:
            if self._is_initialized:
                return
            try:
                records = db_model.query.with_entities(db_model.source_id).all()
                for (sid,) in records:
                    if sid:
                        self._seen_tokens.add(sid)
                self._is_initialized = True
                print(f"[DeduplicationEngine] تعداد {len(self._seen_tokens)} شناسه از پایگاه داده در حافظه کش شد.")
            except Exception as e:
                print(f"[DeduplicationEngine] خطا در بارگذاری اولیه از دیتابیس: {e}")

    def is_duplicate(self, token: Optional[str] = None, *args, **kwargs) -> bool:
        t = token or kwargs.get('source_id') or kwargs.get('token') or (args[0] if args else None)
        if not t:
            return False
        with self.lock:
            return t in self._seen_tokens

    def mark_seen(self, token: Optional[str] = None, *args, **kwargs):
        t = token or kwargs.get('source_id') or kwargs.get('token') or (args[0] if args else None)
        if not t:
            return
        with self.lock:
            self._seen_tokens.add(t)

    def add_item(self, token: Optional[str] = None, *args, **kwargs):
        """نام مستعار سازگار برای mark_seen"""
        self.mark_seen(token, *args, **kwargs)

    def clear(self):
        with self.lock:
            self._seen_tokens.clear()
            self._is_initialized = False

    def size(self) -> int:
        with self.lock:
            return len(self._seen_tokens)

dedup_engine = DeduplicationEngine()
