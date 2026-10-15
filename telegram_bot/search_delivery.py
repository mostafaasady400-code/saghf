"""Durable, narrowly authorized search responses and once-daily new-match notices."""
import hashlib
import json
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from flask import current_app, has_app_context
from config import BASE_DIR

DAILY_TEXT = 'فایل‌های جدید متناسب با نیاز شما پیدا شد. برای مشاهده، تطبیق هوشمند را باز کنید.'


def fingerprint(criteria):
    return hashlib.sha256(json.dumps(criteria,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def item_key(item):
    from urllib.parse import urlsplit
    url = urlsplit(item.get('source_url') or '')
    if url.hostname in ('divar.ir','www.divar.ir') and '/v/' in url.path:
        return 'divar:'+url.path.rstrip('/').rsplit('/',1)[-1]
    return f"{item.get('source_type')}:{item.get('id')}"


class NotificationStore:
    def __init__(self,path=None):
        if path is None and has_app_context() and current_app.testing:
            import tempfile
            path=current_app.config.get('_TEST_NOTIFICATION_STORE')
            if path is None:
                path=str(Path(tempfile.mkdtemp(prefix='saghf-notice-test-'))/'delivery.sqlite3')
                current_app.config['_TEST_NOTIFICATION_STORE']=path
        self.path=Path(path or BASE_DIR/'instance'/'telegram-search-delivery.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('CREATE TABLE IF NOT EXISTS page_orders (recipient TEXT NOT NULL, saved INTEGER NOT NULL, signature TEXT NOT NULL, keys TEXT NOT NULL, PRIMARY KEY(recipient,saved))')
            conn.execute('CREATE TABLE IF NOT EXISTS subscriptions (recipient TEXT PRIMARY KEY, lead_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, known TEXT NOT NULL, enabled INTEGER NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS events (event_key TEXT PRIMARY KEY, recipient TEXT NOT NULL, lead_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, kind TEXT NOT NULL, job_id INTEGER, message_id INTEGER, expires REAL NOT NULL, state TEXT NOT NULL, new_keys TEXT NOT NULL, updated REAL NOT NULL)')
            conn.execute('UPDATE events SET state="unknown" WHERE state="sending" AND updated<?', (time.time()-300,))
            conn.execute('UPDATE events SET state="expired" WHERE state="pending" AND expires<?', (time.time(),))

    def subscribe(self,recipient,lead_id,criteria,items):
        known={item_key(item) for item in items}
        signature=fingerprint(criteria)
        with closing(sqlite3.connect(self.path)) as conn,conn:
            old=conn.execute('SELECT fingerprint,known FROM subscriptions WHERE recipient=?',(str(recipient),)).fetchone()
            if old and old[0]==signature:
                known.update(json.loads(old[1]))
            conn.execute('INSERT INTO subscriptions VALUES (?,?,?,?,1) ON CONFLICT(recipient) DO UPDATE SET lead_id=excluded.lead_id,fingerprint=excluded.fingerprint,known=excluded.known,enabled=1',
                (str(recipient),lead_id,signature,json.dumps(sorted(known))))

    def disable(self,recipient):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('UPDATE subscriptions SET enabled=0 WHERE recipient=?',(str(recipient),))

    def subscriptions(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory=sqlite3.Row
            return [dict(row) for row in conn.execute('SELECT * FROM subscriptions WHERE enabled=1')]

    def issue(self,key,recipient,lead_id,signature,kind,new_keys=(),job_id=None,message_id=None,now=None):
        if kind not in ('search_result','daily_update'):
            raise ValueError('invalid_delivery_kind')
        now=time.time() if now is None else now
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (key,str(recipient),lead_id,signature,kind,job_id,message_id,now+(3600 if kind=='search_result' else 300),'pending',json.dumps(sorted(new_keys)),now))

    def pending(self,job_id=None,kind=None):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory=sqlite3.Row
            query='SELECT * FROM events WHERE state="pending"'
            params=[]
            if job_id is not None:
                query+=' AND job_id=?'
                params.append(job_id)
            if kind is not None:
                query+=' AND kind=?'
                params.append(kind)
            return [dict(row) for row in conn.execute(query+' ORDER BY updated LIMIT 20',params)]

    def claim(self,key,now=None):
        now=time.time() if now is None else now
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.row_factory=sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM events WHERE event_key=?',(key,)).fetchone()
            if not row or row['state']!='pending':
                return None
            if row['expires']<now:
                conn.execute('UPDATE events SET state="expired",updated=? WHERE event_key=?',(now,key))
                return None
            conn.execute('UPDATE events SET state="sending",updated=? WHERE event_key=?',(now,key))
            return dict(row)

    def finish(self,key,state):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('UPDATE events SET state=?,updated=? WHERE event_key=?',(state,time.time(),key))

    def mark_seen(self,recipient,keys):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            row=conn.execute('SELECT known FROM subscriptions WHERE recipient=?',(str(recipient),)).fetchone()
            if row:
                known=set(json.loads(row[0]))
                known.update(keys)
                conn.execute('UPDATE subscriptions SET known=? WHERE recipient=?',(json.dumps(sorted(known)),str(recipient)))

    def unseen_items(self,recipient,items):
        with closing(sqlite3.connect(self.path)) as conn:
            row=conn.execute('SELECT known FROM subscriptions WHERE recipient=?',(str(recipient),)).fetchone()
        seen=set(json.loads(row[0])) if row else set()
        return [item for item in items if item_key(item) not in seen]

    def ordered_page_items(self,recipient,signature,items,saved=False,refresh=False):
        # Store identifiers only. Fresh candidates still enforce current access,
        # availability and criteria; deleted/rejected items are never replayed.
        page_key=lambda item: str(item.get('source_type'))+':'+str(item.get('id'))
        with closing(sqlite3.connect(self.path)) as conn,conn:
            row=conn.execute('SELECT signature,keys FROM page_orders WHERE recipient=? AND saved=?',(str(recipient),int(saved))).fetchone()
            if refresh or not row or row[0]!=signature:
                keys=[page_key(item) for item in items]
                conn.execute('INSERT INTO page_orders VALUES (?,?,?,?) ON CONFLICT(recipient,saved) DO UPDATE SET signature=excluded.signature,keys=excluded.keys',(str(recipient),int(saved),signature,json.dumps(keys)))
            else:
                keys=json.loads(row[1])
        current={page_key(item):item for item in items}
        return [current[key] for key in keys if key in current]

    def prepare_daily(self,now=None):
        from telegram_bot.customer_panel import own_lead,recommendations
        from telegram_bot.workflow import lead_criteria,search_enabled
        now=now or datetime.now(ZoneInfo('Asia/Tehran'))
        if now.tzinfo is None:
            raise ValueError('timezone_required')
        now=now.astimezone(ZoneInfo('Asia/Tehran'))
        if now.hour!=10:
            return 0
        count=0
        for sub in self.subscriptions():
            lead=own_lead(sub['recipient'])
            if not lead or lead.id!=sub['lead_id'] or not search_enabled(lead) or fingerprint(lead_criteria(lead))!=sub['fingerprint']:
                continue
            from telegram_bot.extraction_jobs import ExtractionJobs
            ExtractionJobs().enqueue(lead.id,sub['recipient'],lead_criteria(lead),request_key='daily:'+now.date().isoformat())
            keys={item_key(item) for item in recommendations(sub['recipient'])}
            new_keys=keys-set(json.loads(sub['known']))
            if new_keys:
                self.issue('daily:'+sub['recipient']+':'+now.date().isoformat(),sub['recipient'],lead.id,
                    sub['fingerprint'],'daily_update',new_keys=new_keys,now=now.timestamp())
                count+=1
        return count


def valid_event(event,store):
    from telegram_bot.customer_panel import own_lead
    from telegram_bot.workflow import lead_criteria,search_enabled
    lead=own_lead(event['recipient'])
    if not lead or lead.id!=event['lead_id'] or not search_enabled(lead) or fingerprint(lead_criteria(lead))!=event['fingerprint']:
        return False
    if event['kind']=='daily_update':
        return any(sub['recipient']==event['recipient'] and sub['fingerprint']==event['fingerprint'] for sub in store.subscriptions())
    return event['kind']=='search_result'


@contextmanager
def delivery_scope(store,event):
    from telegram_bot.outbound_policy import _authorized_delivery
    claimed=store.claim(event['event_key'])
    if not claimed:
        yield False
        return
    if not valid_event(claimed,store):
        store.finish(event['event_key'],'cancelled')
        yield False
        return
    scope={'recipient':event['recipient'],'kind':event['kind'],'text':DAILY_TEXT,'calls':0}
    token=_authorized_delivery.set(scope)
    try:
        yield True
    except Exception:
        store.finish(event['event_key'],'unknown')  # Never blindly retry an ambiguous send.
        raise
    else:
        store.finish(event['event_key'],'sent')
    finally:
        _authorized_delivery.reset(token)


def deliver_search_result(queue,job,bot=None):
    from telegram_bot.customer_panel import recommendations,card
    from telegram_bot.bot import get_bot
    from telebot.types import InlineKeyboardMarkup,InlineKeyboardButton
    store=NotificationStore()
    for event in store.pending(job['id']):
        if event['kind']!='search_result':
            continue
        with delivery_scope(store,event) as allowed:
            if not allowed:
                continue
            sender=bot or get_bot()
            state=queue.status(job['id'])
            items=recommendations(event['recipient'])
            baseline=set(json.loads(event['new_keys']))
            fresh=[item for item in items if item_key(item) not in baseline]
            text=('بررسی پایان یافت؛ موارد منطبقِ قابل نمایش را ببینید. پوشش کامل دیوار تضمین نشده است.'
                if state=='ready' else 'بررسی پایان یافت؛ فعلاً فایل جدید قابل نمایش پیدا نشد. این به معنی نبود ملک در بازار نیست.'
                if state=='empty' else 'استخراج زنده تأیید نشد؛ فایل‌های موجود جدا از نتیجه زنده‌اند. وضعیت اتصال نیازمند بررسی است.')
            markup=InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton('مشاهده تطبیق هوشمند',callback_data='customer:refresh'))
            if isinstance(event['message_id'],int):
                sender.edit_message_text(text,chat_id=event['recipient'],message_id=event['message_id'],reply_markup=markup)
            else:
                sender.send_message(event['recipient'],text,reply_markup=markup)
            for item in fresh[:4]:
                card(sender,event['recipient'],item)
            store.mark_seen(event['recipient'],[item_key(item) for item in fresh[:4]])


def notification_tick(bot):
    from telebot.types import InlineKeyboardMarkup,InlineKeyboardButton
    store=NotificationStore()
    store.prepare_daily()
    for event in store.pending(kind='daily_update'):
        if event['kind']!='daily_update':
            continue
        with delivery_scope(store,event) as allowed:
            if not allowed:
                continue
            markup=InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton('مشاهده موارد جدید',callback_data='customer:refresh'))
            markup.row(InlineKeyboardButton('قطع اعلان روزانه',callback_data='customer:daily_off'))
            bot.send_message(event['recipient'],DAILY_TEXT,reply_markup=markup)
            store.mark_seen(event['recipient'],json.loads(event['new_keys']))
        return 1
    return 0
