"""
اجراکننده هماهنگ ربات‌های بله و تلگرام سقف (Saghf Dual Bots Runner)
نحوه اجرا:
    python run_bot.py
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
from services.dual_bot_runner import start_dual_polling, stop_dual_polling, get_dual_bot_status

if __name__ == '__main__':
    print("==================================================", flush=True)
    print("✨ سامانه جامع املاک و فایلینگ سقف (Saghf CRM)", flush=True)
    print("🤖 راه‌اندازی همزمان ربات‌های بله و تلگرام (@Saghf_bot)...", flush=True)
    print("==================================================", flush=True)
    flask_app = create_app()
    with flask_app.app_context():
        status = get_dual_bot_status()
        bale_status = "🟢 پیکربندی شده با توکن رسمی" if status['bale']['configured'] else "🟡 حالت آماده‌باش/شبیه‌سازی (BALE_BOT_TOKEN خالی)"
        tg_status = "🟢 پیکربندی شده با توکن رسمی" if status['telegram']['configured'] else "🟡 حالت آماده‌باش (TELEGRAM_BOT_TOKEN خالی)"
        print(f"📡 وضعیت بات بله:    {bale_status}", flush=True)
        print(f"📡 وضعیت بات تلگرام: {tg_status}", flush=True)

    start_dual_polling(flask_app)
    print("--------------------------------------------------", flush=True)
    print("🟢 ربات‌ها در پس‌زمینه فعال هستند. برای خروج Ctrl+C را بزنید.", flush=True)
    print("==================================================", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 درخواست توقف ربات‌ها دریافت شد...", flush=True)
        stop_dual_polling()
        print("✅ ربات‌ها متوقف شدند.", flush=True)

