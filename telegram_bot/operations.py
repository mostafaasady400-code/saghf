"""Independent notification worker, bounded retries, health and verified SQLite backups."""
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeChat, MenuButtonCommands
from database.db import db
from database.models import Interaction, Visit
from telegram_bot.workflow import (MessageOutbox, ServiceHeartbeat, VisitProposal,
    audit, enqueue_message, ensure_schema, valid_proposal)


def heartbeat(service, state='ready'):
    row = db.session.get(ServiceHeartbeat, service)
    if row is None:
        row = ServiceHeartbeat(service=service)
        db.session.add(row)
    row.seen_at, row.state = datetime.utcnow(), state
    db.session.commit()


def start_heartbeat(app, service):
    def run():
        while True:
            try:
                with app.app_context(): heartbeat(service)
            except Exception:
                pass  # A stale heartbeat remains visible to the health check.
            time.sleep(30)
    threading.Thread(target=run, daemon=True, name=f'{service}-heartbeat').start()


def restore_menu_button(bot, chat_id):
    """Restore Telegram's command menu; a UI API failure must not lose the draft."""
    try:
        bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())
        return True
    except Exception as exc:
        logging.getLogger(__name__).warning('telegram_menu_restore_failed:%s', type(exc).__name__)
        return False


def configure_commands(bot):
    from telegram_bot.office_access import OfficeMembership, principal_for
    common = [BotCommand('start', 'شروع یا ادامه درخواست'), BotCommand('customer', 'پنل مشتری'),
              BotCommand('menu', 'باز کردن منوی اصلی'), BotCommand('help', 'راهنما'), BotCommand('cancel', 'بازگشت به منو')]
    bot.set_my_commands(common)
    bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    for member in OfficeMembership.query.all():
        from telegram_bot.office_access import _telegram_key
        if _telegram_key(member.telegram_id) is None:
            continue
        commands = common + [BotCommand('office', 'میزکار املاک')] if principal_for(member.telegram_id) else common
        bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=int(member.telegram_id)))
        restore_menu_button(bot, int(member.telegram_id))


def enqueue_due_reminders(now=None):
    # Follow-ups are visible on demand in the office dashboard, never pushed.
    return 0


def delivery_valid(row):
    from telegram_bot.office_access import principal_for
    from telegram_bot.office_flow import OfficeFlow
    if row.kind == 'operations_probe':
        principal = principal_for(row.recipient)
        return bool(principal and principal.office_role == 'manager' and principal.membership_id == row.target_id)
    if row.kind == 'reminder':
        principal = principal_for(row.recipient)
        item = OfficeFlow(None, None).interactions(principal).filter_by(id=row.target_id).first() if principal else None
        if not item or item.outcome not in ('pending', 'call_back') or not item.next_followup_date:
            return False
        return row.event_key.startswith(f'reminder:{item.id}:{item.next_followup_date.isoformat()}:')
    if row.kind == 'visit_offer':
        proposal = db.session.get(VisitProposal, row.target_id)
        return bool(proposal and proposal.customer_id == row.recipient and valid_proposal(proposal))
    if row.kind == 'visit_answer':
        proposal = db.session.get(VisitProposal, row.target_id)
        principal = principal_for(row.recipient)
        return bool(proposal and principal and proposal.agent_id == principal.agent_id
            and OfficeFlow(None, None).interactions(principal).filter_by(id=proposal.interaction_id).first())
    if row.kind == 'visit_review':
        from telegram_bot.workflow import customer_for_client
        visit = db.session.get(Visit, row.target_id)
        return bool(visit and visit.status == 'completed' and customer_for_client(visit.client_id).contact_key == f'telegram:{row.recipient}')
    return False


def dispatch_one(bot):
    """Suppress legacy pending work without sending, retrying or deleting history."""
    db.session.expire_all()
    now = datetime.utcnow()
    row = MessageOutbox.query.filter_by(state='pending').order_by(MessageOutbox.id).first()
    if row is not None:
        row.state, row.updated_at, row.error_type = 'suppressed', now, 'PullOnlyPolicy'
    MessageOutbox.query.filter(MessageOutbox.state == 'sending', MessageOutbox.updated_at < now-timedelta(minutes=5)).update(
        {'state': 'unknown', 'error_type': 'InterruptedSend'}, synchronize_session=False)
    db.session.commit()
    return row is not None


def verified_backup(app, directory=None):
    if db.engine.url.get_backend_name() != 'sqlite':
        raise RuntimeError('backup_requires_configured_database_adapter')
    source = Path(db.engine.url.database).resolve()
    if not source.is_file():
        raise RuntimeError('backup_source_missing')
    directory = Path(directory or Path(app.instance_path)/'backups')
    directory.mkdir(parents=True, exist_ok=True)
    target = directory/('crm-'+datetime.utcnow().strftime('%Y%m%d')+'.sqlite3')
    if not target.exists():
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(target)) as dst:
            src.backup(dst)
    with sqlite3.connect(str(target)) as saved, sqlite3.connect(':memory:') as restored:
        saved.backup(restored)
        if restored.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise RuntimeError('backup_restore_integrity_failed')
        names = {row[0] for row in restored.execute('SELECT name FROM sqlite_master WHERE type="table"')}
        if not {'clients', 'properties', 'customer_leads'}.issubset(names):
            raise RuntimeError('backup_restore_schema_failed')
    return target.name


def health_report():
    from telegram_bot.telemetry import metric_counts
    now = datetime.utcnow()
    services = {}
    for name in ('telegram', 'telegram_api', 'extraction', 'operations', 'backup'):
        row = db.session.get(ServiceHeartbeat, name)
        ttl = timedelta(hours=26) if name == 'backup' else timedelta(seconds=90)
        services[name] = {'state': row.state if row else 'not_seen',
                         'healthy': bool(row and row.state == 'ready' and now-row.seen_at < ttl)}
    return {'services': services, 'bot_metrics':metric_counts(), 'divar_session': 'not_checked_by_operations_worker',
        'outbox': {state: MessageOutbox.query.filter_by(state=state).count()
            for state in ('pending', 'sending', 'sent', 'unknown', 'failed', 'cancelled', 'suppressed')},
        'unassigned_requests': Interaction.query.filter(Interaction.outcome == 'pending', Interaction.agent_id.is_(None)).count()}


def main():
    import argparse
    from telegram_bot.runtime import create_crm_context, check_database, polling_lock
    from telegram_bot.bot import get_bot
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    app = create_crm_context(); check_database(app)
    if args.check:
        with app.app_context(): print(json.dumps(health_report(), ensure_ascii=False))
        return
    with app.app_context(): ensure_schema()
    with polling_lock('saghf-telegram-operations-worker'):
        print('operations_worker_ready', flush=True)
        backup_day = None
        api_checked_at = -60
        backup_checked_at = -300
        while True:
            with app.app_context():
                try:
                    heartbeat('operations')
                    if time.monotonic()-api_checked_at >= 60:
                        api_checked_at = time.monotonic()
                        try:
                            get_bot().get_me(); heartbeat('telegram_api')
                        except Exception:
                            heartbeat('telegram_api', 'degraded')
                    if backup_day != datetime.utcnow().date() and time.monotonic()-backup_checked_at >= 300:
                        backup_checked_at = time.monotonic()
                        try:
                            verified_backup(app); heartbeat('backup'); backup_day = datetime.utcnow().date()
                        except Exception as exc:
                            db.session.rollback(); heartbeat('backup', 'degraded')
                            print('backup_failed:'+type(exc).__name__, flush=True)
                    enqueue_due_reminders()
                    from telegram_bot.search_delivery import notification_tick
                    notification_tick(get_bot())
                    for _ in range(20):
                        if not dispatch_one(get_bot()): break
                except Exception as exc:
                    db.session.rollback()
                    try:
                        heartbeat('operations', 'degraded')
                    except Exception:
                        pass
                    print('operations_tick_failed:'+type(exc).__name__, flush=True)
            if args.once: break
            time.sleep(10)


if __name__ == '__main__':
    from telegram_bot.runner import SecretSafeFormatter
    import logging
    import telebot
    logging.basicConfig(level=logging.WARNING)
    for handler in [*logging.getLogger().handlers, *telebot.logger.handlers]:
        handler.setFormatter(SecretSafeFormatter('%(levelname)s:%(name)s:%(message)s'))
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('operations_worker_failed:'+type(exc).__name__)
        raise SystemExit(1)
