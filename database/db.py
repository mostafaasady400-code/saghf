import sqlite3
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    تنظیمات بهینه‌سازی و تسریع فوق‌العاده پایگاه داده SQLite:
    - فعال‌سازی WAL (Write-Ahead Logging) جهت همزمانی کامل خواندن و نوشتن بدون قفل شدن دیتابیس
    - تنظیم cache_size به 64MB حافظه رم جهت پاسخ‌دهی میلی‌ثانیه‌ای به کوئری‌ها
    - ذخیره جداول موقت در RAM (temp_store=MEMORY)
    - نگاشت مستقیم حافظه (mmap_size=256MB)
    - افزایش مهلت انتظار هنگام بار ترافیکی (busy_timeout=10000ms)
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("PRAGMA cache_size = -64000;")
            cursor.execute("PRAGMA temp_store = MEMORY;")
            cursor.execute("PRAGMA mmap_size = 536870912;")
            cursor.execute("PRAGMA threads = 4;")
            cursor.execute("PRAGMA busy_timeout = 10000;")
        except Exception:
            pass
        finally:
            cursor.close()
