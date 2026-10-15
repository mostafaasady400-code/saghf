"""Aggregate counters only: no identities, messages, tokens or exception text."""
import sqlite3
import time
from flask import has_app_context
from contextlib import closing
from telegram_bot.search_delivery import NotificationStore

ALLOWED={'customer_error','callback_error','office_error','photo_fallback','job_failed','slow_job','slow_customer','stale_button','queue_delay','invalid_callback'}

def record_event(kind):
    if kind not in ALLOWED: raise ValueError('invalid_metric')
    if not has_app_context(): return False
    try:
        store=NotificationStore()
        day=time.strftime('%Y-%m-%d',time.gmtime())
        with closing(sqlite3.connect(store.path)) as conn,conn:
            conn.execute('CREATE TABLE IF NOT EXISTS bot_metrics (day TEXT NOT NULL, kind TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(day,kind))')
            conn.execute('INSERT INTO bot_metrics VALUES (?,?,1) ON CONFLICT(day,kind) DO UPDATE SET count=count+1',(day,kind))
    except (sqlite3.Error,OSError):
        # Diagnostic storage must never stop a customer operation.
        return False
    return True

def metric_counts():
    store=NotificationStore()
    with closing(sqlite3.connect(store.path)) as conn:
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_metrics'").fetchone()
        if not exists:return {}
        return dict(conn.execute('SELECT kind,sum(count) FROM bot_metrics GROUP BY kind'))
