import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from database.db import db
from telegram_bot.runtime import create_crm_context, check_database, polling_lock, ingest_message


@pytest.fixture
def crm_app():
    class TestConfig:
        TESTING = True
        SQLALCHEMY_DATABASE_URI = 'sqlite://'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
    app = create_crm_context(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def test_context_does_not_boot_web():
    code = "from telegram_bot.runtime import create_crm_context; import sys; a=create_crm_context(); assert 'app' not in sys.modules; assert not any(x.startswith('routes.') for x in sys.modules); assert len(list(a.url_map.iter_rules())) == 1"
    subprocess.run([sys.executable, '-c', code], check=True, timeout=30)


def test_schema_validation(crm_app):
    check_database(crm_app)


def test_missing_schema_fails():
    class Empty:
        SQLALCHEMY_DATABASE_URI = 'sqlite://'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
    with pytest.raises(RuntimeError, match='crm_schema_missing'):
        check_database(create_crm_context(Empty))


def test_single_consumer_lock(tmp_path):
    with polling_lock('test-token', tmp_path):
        with pytest.raises(RuntimeError, match='already_running'):
            with polling_lock('test-token', tmp_path):
                pass
    with polling_lock('test-token', tmp_path):
        pass


def test_polling_preserves_backlog_and_webhook():
    from telegram_bot.bot import start_polling
    bot = MagicMock()
    bot.get_webhook_info.return_value.url = 'https://example.invalid/webhook'
    with patch('telegram_bot.bot.get_bot', return_value=bot), patch('telegram_bot.bot.Config.TELEGRAM_BOT_TOKEN', 'test-token'), patch('telegram_bot.runtime.polling_lock'):
        with pytest.raises(RuntimeError, match='webhook_active'):
            start_polling()
        bot.remove_webhook.assert_not_called()
        bot.infinity_polling.assert_not_called()
        bot.get_webhook_info.return_value.url = ''
        start_polling()
        assert bot.infinity_polling.call_args.kwargs['skip_pending'] is False


def test_real_crm_upsert_without_invented_phone(crm_app):
    from services.omnichannel_engine import OmniChannelEngine
    from database.models import CustomerLead, Client
    message = SimpleNamespace(chat=SimpleNamespace(type='private', id=12345),
                              from_user=SimpleNamespace(id=12345, is_bot=False, first_name='Test'),
                              message_id=19, text='آپارتمان اجاره می‌خواهم')
    with patch('services.omnichannel_engine.SemanticLLMRouter.classify_and_extract', return_value={'role': 'lead', 'lead_payload': {'full_name': 'Test', 'deal_type': 'rent'}}), patch('services.omnichannel_engine.nurturing_engine.handle_lead_matching_and_dispatch', return_value=[]), patch('services.omnichannel_engine.send_green_lead_alert', return_value=False), patch('services.omnichannel_engine.send_bale_green_lead_alert', return_value=False):
        assert ingest_message(message)['success']
        assert ingest_message(message)['success']
        assert CustomerLead.query.count() == 1
        assert Client.query.count() == 1
        lead = CustomerLead.query.one()
        assert lead.contact_key == 'telegram:12345'
        assert not lead.has_real_phone
        assert lead.phone_number == 'telegram:12345'
    message.chat.type = 'group'
    with pytest.raises(ValueError, match='private_human'):
        ingest_message(message)


def test_secret_safe_logging():
    import logging
    from telegram_bot.runner import SecretSafeFormatter
    with patch('telegram_bot.runner.Config.TELEGRAM_BOT_TOKEN', 'private-token'), patch('telegram_bot.runner.Config.TELEGRAM_PROXY', 'http://user:pass@localhost:8088'):
        record = logging.LogRecord('test', logging.ERROR, '', 0, 'private-token http://user:pass@localhost:8088', (), None)
        output = SecretSafeFormatter().format(record)
        assert 'private-token' not in output
        assert 'user:pass' not in output


def test_registered_text_handler_uses_crm_without_controller(crm_app):
    import telegram_bot.bot as module
    from telebot.types import Message
    message = Message.de_json({'message_id': 12, 'date': 1,
                               'chat': {'id': 67890, 'type': 'private'},
                               'from': {'id': 67890, 'is_bot': False, 'first_name': 'Test'},
                               'text': 'خانه اجاره می‌خواهم'})
    with patch.object(module, '_bot_instance', None), patch.object(module, '_flask_app_instance', crm_app), patch.object(module.Config, 'TELEGRAM_BOT_TOKEN', '123456:TEST'):
        bot = module.get_bot()
        handler = next(item['function'] for item in bot.message_handlers if item['function'].__name__ == 'handle_fallback_text')
        with patch('telegram_bot.runtime.ingest_message', return_value={'success': True}) as ingest, patch.object(bot, 'reply_to') as reply:
            handler(message)
            ingest.assert_called_once_with(message)
            reply.assert_called_once()
