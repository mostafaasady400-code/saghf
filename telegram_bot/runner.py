import argparse
import logging
import re

from config import Config
from telegram_bot.runtime import create_crm_context, check_database


class SecretSafeFormatter(logging.Formatter):
    def format(self, record):
        value = super().format(record)
        if Config.TELEGRAM_BOT_TOKEN:
            value = value.replace(Config.TELEGRAM_BOT_TOKEN, '[REDACTED]')
        if Config.TELEGRAM_PROXY:
            value = value.replace(Config.TELEGRAM_PROXY, '[PROXY]')
        return re.sub(r'(https?://)[^/\s@]+@', r'\1[REDACTED]@', value)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Standalone Telegram CRM worker (no web server).')
    parser.add_argument('--check', action='store_true', help='Read-only database and Telegram connectivity check')
    args = parser.parse_args(argv)
    if not Config.TELEGRAM_BOT_TOKEN:
        print('telegram_token_missing')
        return 2
    from telegram_bot.bot import get_bot, set_flask_app, start_polling
    try:
        app = create_crm_context()
        check_database(app)
        if not args.check:
            from telegram_bot.customer_panel import ensure_customer_schema
            from telegram_bot.office_access import ensure_office_schema
            from telegram_bot.workflow import ensure_schema
            with app.app_context():
                ensure_customer_schema()
                ensure_office_schema()
                ensure_schema()
                from telegram_bot.decision_support import DecisionStore
                DecisionStore()  # Additive, isolated decision journal; no CRM reset.
        set_flask_app(app)
        bot = get_bot()
        bot.get_me()
        if bot.get_webhook_info().url:
            print('telegram_webhook_active: migrate the webhook explicitly before polling')
            return 3
        print('telegram_crm_ready: database and Telegram API checked; pending updates preserved')
        if not args.check:
            from telegram_bot.operations import configure_commands, start_heartbeat
            with app.app_context(): configure_commands(bot)
            start_heartbeat(app, 'telegram')
            start_polling(app)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Never expose request URLs, tokens, proxies, or database connection strings.
        print('telegram_crm_failed:' + type(exc).__name__)
        return 1


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(SecretSafeFormatter('%(levelname)s:%(name)s:%(message)s'))
    import telebot
    for handler in telebot.logger.handlers:
        handler.setFormatter(SecretSafeFormatter('%(levelname)s:%(name)s:%(message)s'))
    raise SystemExit(main())
