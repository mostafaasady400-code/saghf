"""
ماژول مهاجرت خودکار اسکیما جهت حفظ سازگاری دیتابیس لوکال SQLite سقف
اطمینان از وجود فیلدهای فاز 2 در دیتابیس بدون نیاز به DROP TABLE یا حذف داده‌ها
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

MIGRATION_COLUMNS = {
    'customer_leads': [
        ('contact_key', 'VARCHAR(80)'),
        ('client_id', 'INTEGER'),
        ('source_channel', 'VARCHAR(30)'),
    ],
    'matching_records': [
        ('source_type', "VARCHAR(20) DEFAULT 'property'"),
        ('listing_id', 'INTEGER'),
        ('lead_id', 'INTEGER'),
        ('algorithm_version', "VARCHAR(20) DEFAULT 'v2.0'"),
    ],
    'outreach_logs': [
        ('idempotency_key', 'VARCHAR(64)'),
        ('match_record_id', 'INTEGER'),
        ('recipient_key', 'VARCHAR(80)'),
        ('delivery_status', "VARCHAR(20) DEFAULT 'sent'"),
        ('retry_count', 'INTEGER DEFAULT 0'),
    ],
}

def run_auto_migrations(db):
    """بررسی و اعمال ستون‌های جدید روی دیتابیس فعلی"""
    try:
        engine = db.engine
        with engine.connect() as conn:
            for table_name, columns in MIGRATION_COLUMNS.items():
                try:
                    res = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
                    existing_cols = {row[1] for row in res}
                    if not existing_cols:
                        continue  # Table doesn't exist yet, db.create_all will create it

                    for col_name, col_def in columns:
                        if col_name not in existing_cols:
                            logger.info(f"Adding missing column {col_name} to {table_name}")
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_def};"))
                            conn.commit()

                    # اگر contact_key مقداردهی نشده بود، بر اساس phone_number یا id مقداردهی اولیه شود
                    if table_name == 'customer_leads':
                        conn.execute(text("""
                            UPDATE customer_leads 
                            SET contact_key = COALESCE(phone_number, 'lead:' || id)
                            WHERE contact_key IS NULL OR contact_key = '';
                        """))
                        conn.commit()

                        # تبدیل ایندکس یونیک قدیمی به ایندکس معمولی
                        try:
                            conn.execute(text("DROP INDEX IF EXISTS ix_customer_leads_phone_number;"))
                            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_leads_phone_number ON customer_leads (phone_number);"))
                            conn.commit()
                        except Exception:
                            pass

                except Exception as ex:
                    logger.warning(f"Error checking table {table_name} during migration: {ex}")

    except Exception as e:
        logger.error(f"Migration error: {e}")
