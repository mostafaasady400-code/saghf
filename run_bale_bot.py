"""
اجراکننده مستقل ربات بله سامانه سقف (Saghf Bale Bot Runner)
نحوه اجرا:
    python run_bale_bot.py
"""
import os
import sys
import time

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from bale_bot import start_bale_polling

if __name__ == '__main__':
    print("==================================================", flush=True)
    print("✨ سامانه جامع املاک و فایلینگ سقف (Saghf CRM)", flush=True)
    print("🤖 راه‌اندازی ربات رسمی پیام‌رسان بله (Bale Polling)...", flush=True)
    print("==================================================", flush=True)
    flask_app = create_app()
    while True:
        try:
            start_bale_polling(flask_app)
        except KeyboardInterrupt:
            print("\n👋 ربات بله توسط کاربر متوقف شد.", flush=True)
            break
        except Exception as e:
            print(f"⚠️ وقفه در اتصال بله: {e}. تلاش مجدد تا ۵ ثانیه دیگر...", flush=True)
        time.sleep(5)
