"""
اجراکننده مستقل ربات تلگرام سقف (Saghf Telegram Bot Runner)
نحوه اجرا:
    python run_bot.py
"""
import os
import sys

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
from telegram_bot.bot import start_polling

if __name__ == '__main__':
    print("==================================================", flush=True)
    print("✨ سامانه جامع املاک و فایلینگ سقف (Saghf CRM)", flush=True)
    print("🤖 راه‌اندازی ربات تلگرام در حالت شنود زنده (Polling)...", flush=True)
    print("==================================================", flush=True)
    flask_app = create_app()
    start_polling(flask_app)
