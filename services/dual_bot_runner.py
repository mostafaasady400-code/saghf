"""
=============================================================================
راه‌انداز موازی و هماهنگ‌کننده ربات‌های تلگرام و بله سقف (Dual Bot Runner)
اجرای همزمان Polling برای @Saghf_bot در هر دو پلتفرم
امکان تست اتصال زنده و مانیتورینگ وضعیت هردو
=============================================================================
"""

import os
import sys
import logging
import threading
import time
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from telegram_bot.bot import get_bot, start_polling as start_tg_polling, get_webhook_info as get_tg_webhook_info
from bale_bot.client import bale_client
from bale_bot.bot import start_bale_polling, stop_bale_polling

logger = logging.getLogger(__name__)

_runner_running = False
_tg_thread = None
_bale_thread = None


def get_dual_bot_status() -> Dict[str, Any]:
    """
    دریافت وضعیت اتصال زنده هر دو ربات @Saghf_bot در تلگرام و بله
    """
    # ۱. وضعیت تلگرام
    tg_configured = bool(Config.TELEGRAM_BOT_TOKEN)
    tg_info = None
    tg_webhook = None
    if tg_configured:
        try:
            bot = get_bot()
            me = bot.get_me()
            tg_info = {
                'id': me.id,
                'username': me.username,
                'first_name': me.first_name,
                'can_join_groups': me.can_join_groups
            }
            tg_webhook = get_tg_webhook_info()
        except Exception as e:
            tg_info = {'error': str(e)}

    # ۲. وضعیت بله
    bale_configured = bool(Config.BALE_BOT_TOKEN)
    bale_info = None
    bale_webhook = None
    if bale_configured:
        try:
            bale_res = bale_client.get_me()
            bale_info = bale_res.get('result') if bale_res.get('ok') else {'error': bale_res.get('description', 'اتصال ناموفق')}
            bale_webhook = bale_client.get_webhook_info()
        except Exception as e:
            bale_info = {'error': str(e)}

    return {
        'timestamp': time.time(),
        'telegram': {
            'configured': tg_configured,
            'bot_username': getattr(Config, 'TELEGRAM_BOT_USERNAME', '@Saghf_bot'),
            'channel_id': Config.TELEGRAM_CHANNEL_ID or None,
            'webhook_url': Config.TELEGRAM_WEBHOOK_URL or None,
            'bot_info': tg_info,
            'webhook_info': tg_webhook
        },
        'bale': {
            'configured': bale_configured,
            'bot_username': '@Saghf_bot',
            'channel_id': Config.BALE_CHANNEL_ID or None,
            'webhook_url': Config.BALE_WEBHOOK_URL or None,
            'bot_info': bale_info,
            'webhook_info': bale_webhook
        }
    }


def start_dual_polling(flask_app=None):
    """
    راه‌اندازی همزمان Long Polling برای ربات تلگرام و ربات بله
    جهت استفاده در سرور توسعه یا حالتی که دامنه‌های وب‌هوک در دسترس نیستند
    """
    global _runner_running, _tg_thread, _bale_thread
    if _runner_running:
        logger.info("Dual bot runner is already active.")
        return

    _runner_running = True
    print("=" * 60)
    print("🤖 شروع راه‌اندازی همزمان ربات‌های دوگانه سقف (@Saghf_bot)")
    print("   • پلتفرم ۱: تلگرام (Telegram Bot API)")
    print("   • پلتفرم ۲: بله (Bale Bot API)")
    print("=" * 60, flush=True)

    # ۱. راه‌اندازی بله
    if Config.BALE_BOT_TOKEN:
        try:
            start_bale_polling(flask_app)
            print("✅ پروسه Polling بله فعال شد.")
        except Exception as e:
            logger.error(f"Failed to start Bale polling: {e}")
            print(f"⚠️ خطای راه‌اندازی بله: {e}")
    else:
        print("ℹ️ BALE_BOT_TOKEN تنظیم نشده است؛ کلاینت بله در حالت شبیه‌سازی آماده دریافت رویداد است.")

    # ۲. راه‌اندازی تلگرام در ترد اختصاصی
    if Config.TELEGRAM_BOT_TOKEN:
        def _run_tg():
            try:
                start_tg_polling(flask_app)
            except Exception as e:
                logger.error(f"Telegram polling thread error: {e}")

        _tg_thread = threading.Thread(target=_run_tg, daemon=True)
        _tg_thread.start()
        print("✅ پروسه Polling تلگرام فعال شد.")
    else:
        print("ℹ️ TELEGRAM_BOT_TOKEN تنظیم نشده است.")


def stop_dual_polling():
    """توقف ایمن حلقه‌های Polling"""
    global _runner_running
    _runner_running = False
    stop_bale_polling()
    logger.info("Dual bot runner stopped.")


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        status = get_dual_bot_status()
        import pprint
        print("وضعیت اتصال ربات‌ها:")
        pprint.pprint(status)
