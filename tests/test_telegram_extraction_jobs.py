from datetime import datetime, timedelta
from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch

from tests.test_telegram_customer_flow import app
from telegram_bot.extraction_jobs import ExtractionJobs, criteria_from_payload, archive_matches, run_job


def payload():
    return {'deal_type': 'rent', 'preferred_districts': ['پونک'], 'min_area': 70, 'max_area': 90,
            'min_rooms': 2, 'max_budget': 0, 'max_deposit': 500000000, 'max_rent': 15000000,
            'preferred_features': ['پارکینگ']}


def test_queue_dedup_claim_restart_and_no_contact_data(tmp_path):
    queue = ExtractionJobs(tmp_path / 'queue.sqlite3')
    data = dict(payload(), phone='09120000000', full_name='Private')
    job_id = queue.enqueue(1, 777, data)
    assert queue.enqueue(1, 777, data) == job_id
    job = ExtractionJobs(queue.path).claim()
    assert 'phone' not in job['criteria'] and 'full_name' not in job['criteria']
    assert queue.claim() is None
    queue.finish(job_id, 'ready')
    assert queue.status(job_id) == 'ready'


def test_archive_rejects_old_expensive_and_intermediary(app):
    from database.db import db
    from database.models import AccessibleListing
    from crawler.publisher_classifier import LIKELY_OWNER
    def listing(index, **extra):
        fields = dict(source_id=str(index), source_url='https://divar.ir/v/test/' + str(index), title='آپارتمان پونک',
                      description='مالک هستم', city='تهران', district='پونک', property_type='apartment',
                      deal_type='rent', area=80, rooms=2, deposit=500000000, monthly_rent=10000000,
                      has_parking=True, published_at=datetime.utcnow()-timedelta(hours=1), publisher_category=LIKELY_OWNER)
        fields.update(extra)
        fields['publication_earliest_at'] = fields['published_at']
        fields['publication_latest_at'] = fields['published_at']
        return AccessibleListing(**fields)
    db.session.add_all([listing(1), listing(2, deposit=600000000), listing(3, rooms=1),
                        listing(4, published_at=datetime.utcnow()-timedelta(days=2)),
                        listing(5, description='مالک مستقیم هستم')])
    db.session.commit()
    assert [item.source_id for item in archive_matches(payload())] == ['1']
    db.session.add(listing(6, district='جنت آباد شمالی'))
    db.session.commit()
    assert [item.source_id for item in archive_matches(dict(payload(), preferred_districts=['جنت‌آباد شمالی']))] == ['6']


def test_job_connection_failure_does_not_claim_live_or_send_cards(app, tmp_path):
    from services.crm_dual_store import DualCRMStore
    lead, client = DualCRMStore.store_customer_lead(dict(payload(), contact_key='telegram:777', phone='09120000000'), channel='telegram')
    queue = ExtractionJobs(tmp_path / 'queue.sqlite3')
    job_id = queue.enqueue(lead.id, 777, payload())
    bot = MagicMock()
    with patch('telegram_bot.extraction_jobs.archive_matches', return_value=[]), patch('telegram_bot.inventory_bridge.refresh_inventory', side_effect=ConnectionError()):
        run_job(queue, queue.claim(), bot)
    assert queue.status(job_id) == 'failed'
    bot.send_message.assert_not_called()


def test_changed_request_cancels_old_job(app, tmp_path):
    from services.crm_dual_store import DualCRMStore
    lead, client = DualCRMStore.store_customer_lead(dict(payload(), contact_key='telegram:777'), channel='telegram')
    queue = ExtractionJobs(tmp_path / 'queue.sqlite3')
    job_id = queue.enqueue(lead.id, 777, dict(payload(), max_area=120))
    bot = MagicMock()
    run_job(queue, queue.claim(), bot)
    assert queue.status(job_id) == 'cancelled'
    bot.send_message.assert_not_called()


def test_ready_matches_are_stored_without_any_delivery(app, tmp_path):
    from services.crm_dual_store import DualCRMStore
    lead, client = DualCRMStore.store_customer_lead(dict(payload(), contact_key='telegram:777', phone='09120000000'), channel='telegram')
    queue = ExtractionJobs(tmp_path / 'queue.sqlite3')
    job_id = queue.enqueue(lead.id, 777, payload())
    item = N(source_url='https://divar.ir/v/test/example', title='آپارتمان پونک', area=80, rooms=2, published_at=datetime.utcnow())
    bot = MagicMock()
    bot.send_message.side_effect = TimeoutError()
    with patch('telegram_bot.extraction_jobs.archive_matches', return_value=[item]), patch('telegram_bot.inventory_bridge.refresh_inventory', return_value={'source_status':'partial','is_live':True}) as execute, patch('telegram_bot.customer_panel.recommendations', return_value=[item]):
        run_job(queue, queue.claim(), bot)
    assert queue.status(job_id) == 'ready'
    execute.assert_called_once()
    assert execute.call_args.args[0] == payload()
    bot.send_message.assert_not_called()
    assert queue.claim() is None
