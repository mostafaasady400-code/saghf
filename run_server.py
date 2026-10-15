import os
import sys

# Force UTF-8 on Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import Config
from app import create_app

def run_optimized_server():
    print("=" * 60)
    print("✨ سامانه جامع املاک و فایلینگ سقف (Saghf Real Estate OS)")
    print("🚀 اجرای فوق‌سریع در حالت Production-Grade High Performance")
    print("⚜️ دیتابیس: SQLite WAL + RAM Cache 64MB + Memory-Mapped IO")
    print(f"🌐 آدرس دسترسی محلی: http://127.0.0.1:5000")
    print(f"👤 نام کاربری ادمین: {Config.ADMIN_USERNAME}")
    print(f"🔑 گذرواژه پیش‌فرض: {Config.ADMIN_PASSWORD}")
    print(f"👑 پنل مدیریت:      http://127.0.0.1:5000/admin/login")
    print("=" * 60)

    app = create_app()

    try:
        from waitress import serve
        threads = int(os.environ.get('SERVER_THREADS', 16))
        print(f"⚡ وب‌سرور صنعتی Waitress با {threads} نخ موازی همزمان فعال شد.")
        serve(
            app,
            host='127.0.0.1',
            port=5000,
            threads=threads,
            connection_limit=300,
            channel_timeout=60,
            _quiet=False
        )
    except ImportError:
        print("⚠️ ماژول waitress یافت نشد؛ در حال اجرا با سرور استاندارد چندنخی...")
        app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)

if __name__ == '__main__':
    run_optimized_server()
