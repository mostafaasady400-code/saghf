"""Requested completion/daily notices: isolated journal and mocked Telegram only."""
import json
import sqlite3
import time
from datetime import datetime
from types import SimpleNamespace as N
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo
import pytest
from telebot import apihelper
from telegram_bot.outbound_policy import ReplyOnlyTeleBot
from telegram_bot.search_delivery import NotificationStore, fingerprint, delivery_scope, DAILY_TEXT, item_key
from tests.test_telegram_customer_flow import app


@pytest.fixture
def store(app,tmp_path):
    return NotificationStore(tmp_path/'notices.sqlite3')


def valid_patch():
    return patch('telegram_bot.search_delivery.valid_event',return_value=True)


def issue(store,kind='daily_update',key='daily:777:day',recipient=777):
    store.issue(key,recipient,1,fingerprint({}),kind)
    return store.pending(kind=kind)[0]


def state(store,key):
    with sqlite3.connect(store.path) as conn:
        return conn.execute('SELECT state FROM events WHERE event_key=?',(key,)).fetchone()[0]


def test_daily_is_text_only_same_recipient_and_once(store):
    event=issue(store)
    bot=ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')
    response={'message_id':1,'date':1,'chat':{'id':777,'type':'private'}}
    with valid_patch(),patch.object(apihelper,'send_message',return_value=response) as network:
        with delivery_scope(store,event) as allowed:
            assert allowed
            with pytest.raises(PermissionError):bot.send_message(888,DAILY_TEXT)
            with pytest.raises(PermissionError):bot.send_message(777,'arbitrary text')
            with pytest.raises(PermissionError):bot.send_photo(777,'photo')
            with pytest.raises(PermissionError):bot.send_document(777,'document')
            bot.send_message(777,DAILY_TEXT)
        with delivery_scope(store,event) as allowed:
            assert not allowed
        assert network.call_count==1
    assert state(store,event['event_key'])=='sent'
    with pytest.raises(PermissionError):bot.send_message(777,DAILY_TEXT)


def test_requested_result_allows_photo_but_never_documents(store):
    event=issue(store,'search_result','search:1')
    bot=ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')
    response={'message_id':1,'date':1,'chat':{'id':777,'type':'private'}}
    with valid_patch(),patch.object(apihelper,'send_photo',return_value=response) as network:
        with delivery_scope(store,event) as allowed:
            assert allowed
            with pytest.raises(PermissionError):bot.send_document(777,'file')
            with pytest.raises(PermissionError):bot.send_photo(888,'photo')
            bot.send_photo(777,'https://s100.divarcdn.com/test.jpg')
        assert network.call_count==1


def test_unknown_send_is_not_retried_after_restart(store):
    event=issue(store)
    with valid_patch():
        with pytest.raises(TimeoutError):
            with delivery_scope(store,event):
                raise TimeoutError('transport unknown')
    assert state(store,event['event_key'])=='unknown'
    restarted=NotificationStore(store.path)
    with delivery_scope(restarted,event) as allowed:
        assert not allowed


def test_expired_or_changed_request_cannot_deliver(store):
    event=issue(store)
    assert store.claim(event['event_key'],now=time.time()+301) is None
    assert state(store,event['event_key'])=='expired'
    event=issue(store,key='daily:changed')
    with patch('telegram_bot.search_delivery.valid_event',return_value=False):
        with delivery_scope(store,event) as allowed:
            assert not allowed
    assert state(store,event['event_key'])=='cancelled'

def test_requested_search_can_finish_after_queue_wait(store):
    store.issue('search:wait',777,1,fingerprint({}),'search_result',now=1000)
    assert store.claim('search:wait',now=1600) is not None

def test_page_order_stays_stable_and_never_replays_removed_files(store):
    items=[{'source_type':'archive','id':index,'source_url':'https://divar.ir/v/shared'} for index in range(1,10)]
    assert [row['id'] for row in store.ordered_page_items(777,'criteria',items,refresh=True)]==list(range(1,10))
    fresh=[{'source_type':'archive','id':10},*reversed(items)]
    assert [row['id'] for row in store.ordered_page_items(777,'criteria',fresh)]==list(range(1,10))
    assert 1 not in [row['id'] for row in store.ordered_page_items(777,'criteria',fresh[:-1])]
    assert [row['id'] for row in store.ordered_page_items(777,'changed',fresh)]==[10,*range(9,0,-1)]

def test_mark_seen_suppresses_daily_repeat_without_enabling_subscription(store):
    store.subscribe(777,1,{},[])
    store.disable(777)
    store.mark_seen(777,['divar:seen'])
    with sqlite3.connect(store.path) as conn:
        known,enabled=conn.execute('SELECT known,enabled FROM subscriptions WHERE recipient="777"').fetchone()
    assert json.loads(known)==['divar:seen'] and enabled==0

def test_new_pages_keep_unseen_baseline_after_first_page_seen(store):
    items=[{'source_type':'archive','id':index} for index in range(1,10)]
    store.subscribe(777,1,{},[])
    unseen=store.unseen_items(777,items)
    store.ordered_page_items(777,'same',unseen,saved=2,refresh=True)
    store.mark_seen(777,[item_key(item) for item in items[:4]])
    assert [item['id'] for item in store.ordered_page_items(777,'same',items,saved=2)[4:8]]==[5,6,7,8]
    assert [item['id'] for item in store.unseen_items(777,items)]==[5,6,7,8,9]


def test_daily_only_at_ten_with_new_matching_items_and_dedup(store):
    old={'source_type':'archive','id':1,'source_url':'https://divar.ir/v/old'}
    new={'source_type':'archive','id':2,'source_url':'https://divar.ir/v/new'}
    store.subscribe(777,1,{},[old])
    lead=N(id=1)
    morning=datetime.now(ZoneInfo('Asia/Tehran')).replace(hour=10,minute=0,second=0,microsecond=0)
    with patch('telegram_bot.customer_panel.own_lead',return_value=lead),patch('telegram_bot.workflow.lead_criteria',return_value={}),patch('telegram_bot.workflow.search_enabled',return_value=True),patch('telegram_bot.customer_panel.recommendations',return_value=[old,new]),patch('telegram_bot.extraction_jobs.ExtractionJobs') as queue:
        assert store.prepare_daily(morning.replace(hour=9))==0
        assert store.prepare_daily(morning)==1
        assert store.prepare_daily(morning)==1
        assert len(store.pending(kind='daily_update'))==1
        assert json.loads(store.pending(kind='daily_update')[0]['new_keys'])==[item_key(new)]
        queue.return_value.enqueue.assert_called()
    store.mark_seen(777,[item_key(new)])
    with patch('telegram_bot.customer_panel.own_lead',return_value=lead),patch('telegram_bot.workflow.lead_criteria',return_value={}),patch('telegram_bot.workflow.search_enabled',return_value=True),patch('telegram_bot.customer_panel.recommendations',return_value=[old,new]),patch('telegram_bot.extraction_jobs.ExtractionJobs'):
        assert store.prepare_daily(morning)==0
    store.disable(777)
    assert store.subscriptions()==[]


def test_paused_search_and_changed_filters_do_not_prepare_daily(store):
    store.subscribe(777,1,{},[])
    moment=datetime.now(ZoneInfo('Asia/Tehran')).replace(hour=10,minute=0)
    with patch('telegram_bot.customer_panel.own_lead',return_value=N(id=1)),patch('telegram_bot.workflow.search_enabled',return_value=False),patch('telegram_bot.customer_panel.recommendations') as matching:
        assert store.prepare_daily(moment)==0
        matching.assert_not_called()


def test_completion_without_a_grant_never_acquires_sender(store):
    from telegram_bot.search_delivery import deliver_search_result
    with patch('telegram_bot.search_delivery.NotificationStore',return_value=store),patch('telegram_bot.bot.get_bot') as sender:
        deliver_search_result(MagicMock(),{'id':1})
        sender.assert_not_called()


def test_completion_only_sends_new_items_under_explicit_grant(store):
    from telegram_bot.search_delivery import deliver_search_result
    old={'source_type':'archive','id':1,'source_url':'https://divar.ir/v/old'}
    new={'source_type':'archive','id':2,'source_url':'https://divar.ir/v/new'}
    store.issue('search:1',777,1,fingerprint({}),'search_result',new_keys=[item_key(old)],job_id=1,message_id=5)
    bot=MagicMock()
    queue=MagicMock()
    queue.status.return_value='ready'
    with valid_patch(),patch('telegram_bot.search_delivery.NotificationStore',return_value=store),patch('telegram_bot.customer_panel.recommendations',return_value=[old,new]),patch('telegram_bot.customer_panel.card') as card:
        deliver_search_result(queue,{'id':1},bot)
        deliver_search_result(queue,{'id':1},bot)
        card.assert_called_once_with(bot,'777',new)
        bot.edit_message_text.assert_called_once()


def test_journal_contains_no_phone_or_session_fields(store):
    with sqlite3.connect(store.path) as conn:
        fields={row[1] for row in conn.execute('PRAGMA table_info(events)')}
    assert not fields & {'phone','cookies','token','password'}
