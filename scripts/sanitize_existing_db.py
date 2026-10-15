import sqlite3
import os
import sys

# اطمینان از تنظیم خروجی کنسول روی UTF-8 در ویندوز
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, 'saghf_database.db')

def sanitize_database():
    if not os.path.exists(DB_PATH):
        print(f"❌ دیتابیس در مسیر {DB_PATH} یافت نشد.")
        return

    from crawler.schemas import sanitize_property_financials

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, deal_type, total_price, deposit, monthly_rent, property_type FROM properties")
    rows = cursor.fetchall()
    print(f"🔍 در حال بررسی {len(rows)} رکورد در جدول properties...")

    updated_count = 0
    for r in rows:
        pid, title, deal_type, total_price, deposit, monthly_rent, prop_type = r
        clean_price, clean_dep, clean_rent = sanitize_property_financials(
            deal_type=deal_type,
            total_price=total_price,
            deposit=deposit,
            monthly_rent=monthly_rent,
            property_type=prop_type or 'apartment'
        )

        if (clean_price != total_price) or (clean_dep != deposit) or (clean_rent != monthly_rent):
            cursor.execute(
                "UPDATE properties SET total_price = ?, deposit = ?, monthly_rent = ? WHERE id = ?",
                (clean_price, clean_dep, clean_rent, pid)
            )
            updated_count += 1
            print(f"✅ اصلاح رکورد {pid}:")
            print(f"   قبل: price={total_price:,} | dep={deposit:,} | rent={monthly_rent:,}")
            print(f"   بعد: price={clean_price:,} | dep={clean_dep:,} | rent={clean_rent:,}")

    conn.commit()
    conn.close()
    print(f"\n🎉 اصلاح دیتابیس تکمیل شد! تعداد {updated_count} رکورد با مقادیر پاک و معتبر جایگزین شدند.")

if __name__ == '__main__':
    sanitize_database()
