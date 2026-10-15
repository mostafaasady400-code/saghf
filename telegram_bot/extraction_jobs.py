# Durable extraction requests: no tokens, contacts, or customer phone numbers.
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import closing

from config import BASE_DIR


def criteria_from_payload(payload):
    return {key: payload.get(key) for key in ('deal_type', 'preferred_districts', 'min_area', 'max_area',
            'min_rooms', 'max_budget', 'max_deposit', 'max_rent', 'preferred_features')}


class ExtractionJobs:
    def __init__(self, path=None):
        self.path = Path(path or BASE_DIR / 'instance' / 'telegram-extraction-jobs.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, dedup TEXT UNIQUE NOT NULL, lead_id INTEGER NOT NULL, recipient TEXT NOT NULL, criteria TEXT NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL, report TEXT NOT NULL DEFAULT "{}")')

    def enqueue(self, lead_id, recipient, payload, request_key=None):
        criteria = json.dumps(criteria_from_payload(payload), sort_keys=True, ensure_ascii=False)
        key = hashlib.sha256(f'{lead_id}:{datetime.utcnow().date()}:{criteria}:{request_key or ""}'.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT OR IGNORE INTO jobs (dedup, lead_id, recipient, criteria, state, updated) VALUES (?, ?, ?, ?, ?, ?)',
                         (key, lead_id, str(recipient), criteria, 'queued', time.time()))
            # An explicit new submission can retry a failed extraction after cooldown.
            conn.execute('UPDATE jobs SET state="queued", updated=? WHERE dedup=? AND state="failed" AND updated<?',
                         (time.time(), key, time.time()-60))
            conn.execute('UPDATE jobs SET state="queued", updated=? WHERE dedup=? AND state="cancelled"',
                         (time.time(), key))
            return conn.execute('SELECT id FROM jobs WHERE dedup=?', (key,)).fetchone()[0]

    def claim(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE jobs SET state="queued" WHERE state="running" AND updated<?', (time.time()-300,))
            row = conn.execute('SELECT * FROM jobs WHERE state="queued" ORDER BY id LIMIT 1').fetchone()
            if not row:
                return None
            conn.execute('UPDATE jobs SET state="running", updated=? WHERE id=?', (time.time(), row['id']))
            job = dict(row)
            job['criteria'] = json.loads(job['criteria'])
            return job

    def finish(self, job_id, state, report=None):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE jobs SET state=?, updated=?, report=? WHERE id=?',
                         (state, time.time(), json.dumps(report or {}, ensure_ascii=False), job_id))

    def status(self, job_id):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            return conn.execute('SELECT state FROM jobs WHERE id=?', (job_id,)).fetchone()[0]

    def latest_status(self, recipient):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute('SELECT state FROM jobs WHERE recipient=? ORDER BY id DESC LIMIT 1', (str(recipient),)).fetchone()
            return row[0] if row else None

    def latest_job(self, recipient):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM jobs WHERE recipient=? ORDER BY id DESC LIMIT 1', (str(recipient),)).fetchone()
            if not row:
                return None
            value = dict(row)
            value['report'] = json.loads(value['report'])
            return value


def archive_matches(criteria):
    from database.models import AccessibleListing as Listing
    from services.assistant.crawler_bridge import CrawlerBridge
    from crawler.strict_owner_guard import strict_decision
    from sqlalchemy import or_, func
    now = datetime.utcnow()
    query = CrawlerBridge._base_owner_query(criteria['deal_type'], now - timedelta(hours=24))
    districts = list(criteria.get('preferred_districts') or [])
    expanded = []
    for district in districts:
        if district in ('منطقه ۲', 'منطقه 2', 'منطقه ۵', 'منطقه 5'):
            from data.tehran_districts import REGION_2_DISTRICT_NAMES, REGION_5_DISTRICT_NAMES
            expanded.extend(REGION_2_DISTRICT_NAMES if district in ('منطقه ۲', 'منطقه 2') else REGION_5_DISTRICT_NAMES)
        else:
            expanded.append(district)
    if expanded:
        normalized = func.replace(Listing.district, '\u200c', ' ')
        query = query.filter(or_(*(normalized.contains(name.replace('\u200c', ' '), autoescape=True) for name in expanded)))
    query = query.filter(Listing.city.in_(['تهران', 'tehran']), Listing.property_type == 'apartment', Listing.published_at <= now,
                         Listing.area >= criteria['min_area'], Listing.area <= criteria['max_area'])
    if criteria.get('min_rooms'):
        query = query.filter(Listing.rooms >= criteria['min_rooms'])
    budgets = [('total_price', 'max_budget')] if criteria['deal_type'] == 'sale' else [('deposit', 'max_deposit'), ('monthly_rent', 'max_rent')]
    for column, key in budgets:
        if criteria.get(key) or criteria['deal_type'] == 'rent':
            query = query.filter(getattr(Listing, column) <= (criteria.get(key) or 0))
    for feature, column in [('پارکینگ', 'has_parking'), ('آسانسور', 'has_elevator'), ('انباری', 'has_warehouse')]:
        if feature in (criteria.get('preferred_features') or []):
            query = query.filter(getattr(Listing, column).is_(True))
    # Apply the existing strict owner guard; do not collect contact numbers.
    output = []
    for listing in query.order_by(Listing.published_at.desc()).limit(100).all():
        from telegram_bot.amenities import extra_features_match
        if not extra_features_match(listing.to_dict(), criteria.get('preferred_features')):
            continue
        if not strict_decision(listing.title, listing.description).allowed or not CrawlerBridge._is_clean_personal_listing(listing):
            continue
        output.append(listing)
    return output


def run_job(queue, job, bot):
    if time.time()-job.get('updated',time.time())>30:
        from telegram_bot.telemetry import record_event
        record_event('queue_delay')
    from database.db import db
    from database.models import CustomerLead
    from telegram_bot.inventory_bridge import refresh_inventory
    criteria = job['criteria']
    lead = db.session.get(CustomerLead, job['lead_id'])
    if not lead or not lead.crm_client or lead.contact_key != 'telegram:' + job['recipient']:
        queue.finish(job['id'], 'cancelled', {'reason': 'identity_changed'})
        return
    client = lead.crm_client
    from telegram_bot.workflow import search_enabled
    if not search_enabled(lead):
        queue.finish(job['id'], 'cancelled', {'reason': 'customer_search_stopped'})
        return
    current = {'deal_type': lead.deal_type, 'preferred_districts': lead.preferred_districts,
               'min_area': lead.min_area, 'max_area': client.max_area, 'min_rooms': client.min_rooms,
               'max_budget': lead.max_budget, 'max_deposit': lead.max_deposit, 'max_rent': lead.max_rent,
               'preferred_features': lead.preferred_features}
    if current != criteria:
        queue.finish(job['id'], 'cancelled', {'reason': 'criteria_changed'})
        return
    started=time.monotonic()
    report = {'data_source': 'persisted_archive', 'is_live': False}
    try:
        matches = archive_matches(criteria)
        db.session.refresh(client)
        db.session.refresh(lead)
        from telegram_bot.workflow import lead_criteria
        if not search_enabled(lead) or lead_criteria(lead) != criteria:
            queue.finish(job['id'], 'cancelled', {'reason': 'request_changed_before_live_search'})
            return
        report.update(refresh_inventory(criteria))
        queue.finish(job['id'], 'running', report)
        matches = archive_matches(criteria)
        db.session.refresh(client)
        db.session.refresh(lead)
        from telegram_bot.workflow import lead_criteria
        if lead_criteria(lead) != criteria:
            queue.finish(job['id'], 'cancelled', {'reason': 'criteria_changed_during_extraction'})
            return
        if not search_enabled(lead):
            queue.finish(job['id'], 'cancelled', {'reason': 'customer_search_stopped'})
            return
        report['delivery_mode'] = 'explicit_requested_completion'
        from telegram_bot.customer_panel import recommendations
        matches = recommendations(job['recipient'])
        queue.finish(job['id'], 'ready' if matches else 'empty', report)
    except Exception as exc:
        from telegram_bot.telemetry import record_event
        record_event('job_failed')
        db.session.rollback()
        state = 'delivery_unknown' if queue.status(job['id']) == 'delivering' else 'failed'
        queue.finish(job['id'], state, {**report, 'error_type': type(exc).__name__})
    finally:
        if time.monotonic()-started>180:
            from telegram_bot.telemetry import record_event
            record_event('slow_job')
        try:
            from telegram_bot.search_delivery import deliver_search_result
            deliver_search_result(queue, job, bot)
        except Exception as error:
            import logging
            logging.getLogger(__name__).warning('requested_search_delivery_failed:%s', type(error).__name__)


def main():
    import argparse
    from telegram_bot.runtime import create_crm_context, check_database, polling_lock
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    app = create_crm_context()
    check_database(app)
    from telegram_bot.workflow import ensure_schema
    from telegram_bot.operations import start_heartbeat
    with app.app_context(): ensure_schema()
    start_heartbeat(app, 'extraction')
    queue = ExtractionJobs()
    with polling_lock('saghf-telegram-extraction-worker'):
        print('extraction_worker_ready', flush=True)
        while True:
            job = queue.claim()
            if job:
                with app.app_context():
                    run_job(queue, job, None)  # Extraction has no Telegram sender.
            if args.once:
                break
            time.sleep(3)


if __name__ == '__main__':
    import logging
    import telebot
    from telegram_bot.runner import SecretSafeFormatter
    logging.basicConfig(level=logging.WARNING)
    for handler in [*logging.getLogger().handlers, *telebot.logger.handlers]:
        handler.setFormatter(SecretSafeFormatter('%(levelname)s:%(name)s:%(message)s'))
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('extraction_worker_failed:' + type(exc).__name__)
        raise SystemExit(1)
