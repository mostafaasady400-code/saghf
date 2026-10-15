# Minimal database context and single-consumer guard for Telegram.
import hashlib
from contextlib import contextmanager
from pathlib import Path

from flask import Flask
from sqlalchemy import inspect

from config import BASE_DIR, Config
from database.db import db


def create_crm_context(config=Config):
    app = Flask('saghf_telegram_crm', instance_path=str(BASE_DIR / 'instance'))
    app.config.from_object(config)
    app.config['TELEGRAM_CRM_STANDALONE'] = True
    db.init_app(app)
    from database import models  # Register models without routes or web startup.
    from telegram_bot import customer_panel, office_access, workflow
    return app


def check_database(app):
    with app.app_context():
        required = {'owners', 'properties', 'clients', 'customer_leads', 'interactions', 'outreach_logs'}
        missing = required - set(inspect(db.engine).get_table_names())
        if missing:
            raise RuntimeError('crm_schema_missing')


@contextmanager
def polling_lock(token, directory=None):
    directory = Path(directory or BASE_DIR / 'instance')
    directory.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(token.encode()).hexdigest()[:16]
    stream = (directory / f'telegram-{name}.lock').open('a+b')
    if stream.tell() == 0:
        stream.write(b'0')
        stream.flush()
    stream.seek(0)
    try:
        if __import__('os').name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError('telegram_consumer_already_running') from None
    try:
        yield
    finally:
        stream.seek(0)
        if __import__('os').name == 'nt':
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def ingest_message(message):
    from services.omnichannel_engine import OmniChannelEngine
    if message.chat.type != 'private' or not message.from_user or message.from_user.is_bot:
        raise ValueError('private_human_message_required')
    return OmniChannelEngine.ingest_interaction(
        channel='telegram', sender_id=str(message.from_user.id), text=message.text,
        metadata={'source_external_id': str(message.from_user.id),
                  'message_id': message.message_id, 'chat_id': str(message.chat.id),
                  'sender_name': message.from_user.first_name},
    )
