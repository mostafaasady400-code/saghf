"""On-demand, customer-scoped comparisons, filter drafts and visit preferences."""
import copy
import html
import json
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telegram_bot.search_delivery import NotificationStore, fingerprint, item_key


class DecisionStore(NotificationStore):
    def __init__(self,path=None):
        super().__init__(path)
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('CREATE TABLE IF NOT EXISTS decision_comparisons (recipient TEXT PRIMARY KEY, signature TEXT NOT NULL, keys TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS decision_actions (token TEXT PRIMARY KEY, recipient TEXT NOT NULL, signature TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0)')
            conn.execute('CREATE TABLE IF NOT EXISTS visit_preferences (interaction_id INTEGER PRIMARY KEY, recipient TEXT NOT NULL, starts TEXT NOT NULL, ends TEXT NOT NULL)')

    def comparison(self,user,signature,key=None,allowed=()):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT signature,keys FROM decision_comparisons WHERE recipient=?',(str(user),)).fetchone()
            keys=json.loads(row[1]) if row and row[0]==signature else []
            keys=[value for value in keys if value in allowed]
            if key is not None:
                if key not in allowed: raise ValueError('فایل دیگر قابل مقایسه نیست.')
                if key in keys: keys.remove(key)
                elif len(keys)>=3: raise ValueError('حداکثر سه ملک را مقایسه کنید.')
                else: keys.append(key)
            conn.execute('INSERT INTO decision_comparisons VALUES (?,?,?) ON CONFLICT(recipient) DO UPDATE SET signature=excluded.signature,keys=excluded.keys',(str(user),signature,json.dumps(keys)))
            return keys

    def issue_action(self,user,signature,kind,payload):
        if kind not in ('relax','slots'): raise ValueError('invalid_action')
        token=secrets.token_hex(8)
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('INSERT INTO decision_actions VALUES (?,?,?,?,?,?,0)',(token,str(user),signature,kind,json.dumps(payload),time.time()+900))
        return token

    def action(self,token,user,signature,kind):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT * FROM decision_actions WHERE token=?',(token,)).fetchone()
        if not row or row['recipient']!=str(user) or row['signature']!=signature or row['kind']!=kind or row['used'] or row['expires']<time.time():
            raise ValueError('این گزینه قدیمی است؛ دوباره از منوی جاری انتخاب کنید.')
        return json.loads(row['payload'])

    def consume(self,token):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('UPDATE decision_actions SET used=1 WHERE token=?',(token,))

    def set_preference(self,token,user,signature,index):
        payload=self.action(token,user,signature,'slots')
        if not 0<=index<len(payload['slots']): raise ValueError('گزینه معتبر نیست.')
        slot=payload['slots'][index]
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('BEGIN IMMEDIATE')
            changed=conn.execute('UPDATE decision_actions SET used=1 WHERE token=? AND used=0 AND expires>=?',(token,time.time())).rowcount
            if not changed: raise ValueError('این انتخاب قبلاً ثبت شده یا منقضی شده است.')
            conn.execute('INSERT INTO visit_preferences VALUES (?,?,?,?) ON CONFLICT(interaction_id) DO UPDATE SET recipient=excluded.recipient,starts=excluded.starts,ends=excluded.ends',
                         (payload['interaction_id'],str(user),slot['starts'],slot['ends']))
        return slot

    def preference(self,interaction_id):
        with closing(sqlite3.connect(self.path)) as conn:
            row=conn.execute('SELECT starts,ends FROM visit_preferences WHERE interaction_id=?',(interaction_id,)).fetchone()
        if row and datetime.fromisoformat(row[1])<=datetime.now(timezone.utc): return None
        return row


def match_explanation(item):
    known=[label for key,label in [('has_parking','پارکینگ'),('has_elevator','آسانسور'),('has_warehouse','انباری'),('has_balcony','بالکن')] if item.get(key) is True]
    unknown=[label for key,label in [('has_parking','پارکینگ'),('has_elevator','آسانسور'),('has_warehouse','انباری'),('has_balcony','بالکن')] if item.get(key) is None]
    return 'تطابق نوع معامله، محله، متراژ و سقف بودجه' + ('؛ امکانات ثبت‌شده: '+ '، '.join(known) if known else '') + ('؛ اطلاعات نامشخص: '+ '، '.join(unknown) if unknown else '')


def saved_items(user):
    from telegram_bot.customer_panel import PanelSelection,recommendations
    keys={(row.source_type,row.source_id) for row in PanelSelection.query.filter_by(telegram_id=str(user),saved=True,rejected=False)}
    return [item for item in recommendations(user) if (item['source_type'],item['id']) in keys]


def comparison_view(user,lead,key=None,page=0):
    from telegram_bot.workflow import lead_criteria
    from telegram_bot.customer_panel import formatted_amount
    items=saved_items(user)
    by_key={f"{item['source_type']}:{item['id']}":item for item in items}
    selected=DecisionStore().comparison(user,fingerprint(lead_criteria(lead)),key,by_key)
    lines=[f'مقایسه ملک‌های نشان‌شده | انتخاب {len(selected)} از ۳', 'دو یا سه ملک را انتخاب کنید؛ فایل نامعتبر یا خارج از دسترسی نمایش داده نمی‌شود.']
    for position,value in enumerate(selected,1):
        item=by_key[value]
        price='قیمت: '+formatted_amount(item.get('total_price')) if item['deal_type']=='sale' else 'رهن: '+formatted_amount(item.get('deposit'))+' | اجاره: '+formatted_amount(item.get('monthly_rent'))
        lines.append(f"\n{position}. {str(item.get('title') or 'ملک')[:100]}\n{item.get('district')} | {item.get('area')} متر | {item.get('rooms')} خواب\n{price} تومان\n{match_explanation(item)}")
    markup=InlineKeyboardMarkup()
    entries=list(by_key.items()); page=max(0,min(page,max(0,(len(entries)-1)//5)))
    lines.append(f'صفحه {page+1} از {max(1,(len(entries)+4)//5)}')
    for value,item in entries[page*5:(page+1)*5]:
        markup.row(InlineKeyboardButton(('✓ ' if value in selected else '')+str(item.get('title') or 'ملک')[:40],callback_data='decision:pick:'+value+':'+str(page)))
    navigation=[]
    if page: navigation.append(InlineKeyboardButton('قبلی',callback_data='decision:compare_page:'+str(page-1)))
    if (page+1)*5<len(entries): navigation.append(InlineKeyboardButton('بعدی',callback_data='decision:compare_page:'+str(page+1)))
    if navigation: markup.row(*navigation)
    if not items: lines.append('ابتدا حداقل دو ملک را از پیشنهادهای خود نشان کنید.')
    markup.row(InlineKeyboardButton('بازگشت به پیشنهادها',callback_data='customer:refresh'))
    text=html.escape('\n'.join(lines))
    from urllib.parse import urlsplit
    for value in selected:
        url=by_key[value].get('source_url') or ''
        parsed=urlsplit(url)
        if parsed.scheme=='https' and parsed.hostname in ('divar.ir','www.divar.ir') and not parsed.username and not parsed.password:
            text+='\n<a href="'+html.escape(url,quote=True)+'">لینک آگهی</a>'
    return text,markup


def proposed_lead(lead,changes):
    client=lead.crm_client
    client_fields=('assigned_agent_id','lead_status','min_area','max_area','min_rooms','must_have_parking','must_have_elevator','must_have_warehouse')
    fields={key:getattr(client,key,None) for key in client_fields}
    fields.update({key:value for key,value in changes.items() if key in fields})
    values={key:getattr(lead,key,None) for key in ('id','deal_type','preferred_districts','max_budget','max_deposit','max_rent','preferred_features')}
    values.update({key:value for key,value in changes.items() if key in values})
    return SimpleNamespace(**values,crm_client=SimpleNamespace(**fields))


def relaxation_pool(lead):
    from database.models import Property,PropertyListing
    from telegram_bot.customer_panel import _source_visible,PanelSelection
    from telegram_bot.extraction_jobs import archive_matches
    from telegram_bot.workflow import lead_criteria
    criteria=lead_criteria(lead)
    widened=dict(criteria,min_area=max(20,int(criteria['min_area']*.9)),max_area=int(criteria['max_area']*1.1))
    for key in ('max_budget','max_deposit','max_rent'): widened[key]=int((criteria.get(key) or 0)*1.1)
    output=[]
    user=lead.contact_key.split(':')[-1]
    rejected={(row.source_type,row.source_id) for row in PanelSelection.query.filter_by(telegram_id=user,rejected=True)}
    keys=('title','district','city','deal_type','area','rooms','total_price','deposit','monthly_rent','source_url','has_parking','has_elevator','has_warehouse','has_balcony')
    for model,kind in ((Property,'property'),(PropertyListing,'listing')):
        for row in model.query.filter(model.deal_type==lead.deal_type,model.city.in_(['تهران','tehran']),model.property_type=='apartment').order_by(model.id.desc()).limit(500):
            item={key:getattr(row,key,None) for key in keys}
            item.update(source_type=kind,id=row.id,features=getattr(row,'features',[]))
            if (kind,row.id) not in rejected and _source_visible(item,lead): output.append(item)
    for row in archive_matches(widened):
        item={key:getattr(row,key,None) for key in keys}
        item.update(source_type='archive',id=row.id,features=row.features)
        if ('archive',row.id) not in rejected: output.append(item)
    return output


def relaxation_options(lead,items):
    from telegram_bot.customer_panel import _fits
    from telegram_bot.workflow import lead_criteria
    criteria=lead_criteria(lead)
    options=[]
    financial=[('max_budget','total_price')] if lead.deal_type=='sale' else [('max_deposit','deposit'),('max_rent','monthly_rent')]
    possibilities=[]
    for key,column in financial:
        current=criteria.get(key) or 0
        amounts=sorted({item[column] for item in items if isinstance(item.get(column),(int,float)) and current<item[column]<=current*1.1
            and _fits(item,proposed_lead(lead,{key:item[column]}))})
        possibilities.extend({key:value} for value in amounts[:5])
    possibilities += [{'min_area':max(20,int(criteria['min_area']*.9))},{'max_area':int(criteria['max_area']*1.1)}]
    baseline={item_key(item) for item in items if _fits(item,lead)}
    for changes in possibilities:
        relaxed=proposed_lead(lead,changes)
        extra={item_key(item) for item in items if _fits(item,relaxed)}-baseline
        if extra: options.append({'changes':changes,'extra_count':len(extra)})
    # Show at most one minimal financial change per field, not an inflated menu.
    output=[];fields=set()
    for option in options:
        key=next(iter(option['changes']))
        if key not in fields: output.append(option);fields.add(key)
    return output[:3]


def show_relaxations(bot,user,lead):
    from telegram_bot.workflow import lead_criteria
    from telegram_bot.customer_panel import formatted_amount
    options=relaxation_options(lead,relaxation_pool(lead)); markup=InlineKeyboardMarkup()
    labels={'max_budget':'سقف خرید','max_deposit':'سقف رهن','max_rent':'سقف اجاره','min_area':'حداقل متراژ','max_area':'حداکثر متراژ'}
    for option in options:
        key,value=next(iter(option['changes'].items()))
        amount=f'{value} متر' if key in ('min_area','max_area') else formatted_amount(value)+' تومان'
        token=DecisionStore().issue_action(user,fingerprint(lead_criteria(lead)),'relax',option)
        markup.row(InlineKeyboardButton(f"{labels[key]}: {amount}؛ {option['extra_count']} فایل بیشتر",callback_data='decision:apply:'+token))
    markup.row(InlineKeyboardButton('شرایط فعلی حفظ شود',callback_data='customer:refresh'))
    text='پیشنهاد تغییر فقط یک فیلتر؛ شمارش از موجودی قابل دسترسی فعلی است، نه کل بازار. انتخاب شما فقط پیش‌نویس را تغییر می‌دهد؛ ثبت نهایی نیاز به تأیید دارد.' if options else 'در موجودی بررسی‌شده، تغییر محدود یک فیلتر فایل اضافه‌ای پیدا نکرد. شرایط شما تغییر نکرده است.'
    bot.send_message(user,text,reply_markup=markup)


def slot_options(now=None):
    if now is not None and now.tzinfo is None: raise ValueError('timezone_required')
    local=(now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Tehran'))
    output=[]
    for offset,label in ((1,'فردا'),(2,'پس‌فردا')):
        day=local+timedelta(days=offset)
        for start,end in ((10,13),(14,17),(17,20)):
            begins=day.replace(hour=start,minute=0,second=0,microsecond=0)
            finishes=day.replace(hour=end,minute=0,second=0,microsecond=0)
            output.append(dict(label=f'{label} ({begins:%Y/%m/%d})، {start} تا {end}',starts=begins.astimezone(timezone.utc).isoformat(),ends=finishes.astimezone(timezone.utc).isoformat()))
    return output


def show_slots(bot,user,lead,interaction,item=None):
    from telegram_bot.workflow import lead_criteria
    slots=slot_options()
    token=DecisionStore().issue_action(user,fingerprint(lead_criteria(lead)),'slots',{'interaction_id':interaction.id,'slots':slots,'item':[item['source_type'],item['id']] if item else None})
    markup=InlineKeyboardMarkup()
    for index,slot in enumerate(slots): markup.row(InlineKeyboardButton(slot['label'],callback_data=f'decision:slot:{token}:{index}'))
    markup.row(InlineKeyboardButton('بعداً انتخاب می‌کنم',callback_data='customer:home'))
    bot.send_message(user,'چه بازه‌ای برای بازدید مناسب‌تر است؟ زمان‌ها به وقت تهران است؛ این فقط ترجیح شماست و بازدید را قطعی نمی‌کند.',reply_markup=markup)


def request_reschedule(user,visit_id):
    from database.db import db
    from database.models import Visit,Interaction
    from telegram_bot.customer_panel import own_lead
    from telegram_bot.workflow import audit
    lead=own_lead(user);visit=db.session.get(Visit,visit_id)
    if not lead or not visit or visit.client_id!=lead.client_id or visit.status!='scheduled' or visit.scheduled_time<=datetime.utcnow() or visit.agent_id!=lead.crm_client.assigned_agent_id:
        raise ValueError('این بازدید برای تغییر زمان در دسترس نیست.')
    row=Interaction.query.filter_by(client_id=lead.client_id,type='saghf_visit',target_type='visit',target_id=visit.id,outcome='pending').first()
    if row:return row,False
    row=Interaction(client_id=lead.client_id,agent_id=visit.agent_id,property_id=visit.property_id,
        type='saghf_visit',target_type='visit',target_id=visit.id,outcome='pending',
        summary=f'درخواست تغییر زمان بازدید #{visit.id}؛ وقت قبلی تا تأیید جایگزین محفوظ است.',next_followup_date=datetime.utcnow())
    db.session.add(row);db.session.flush()
    audit(f'telegram:{user}','visit_reschedule_requested',visit.id)
    db.session.commit()
    return row,True


def handle_callback(bot,call):
    from database.db import db
    from database.models import Interaction
    from telegram_bot.customer_panel import own_lead
    from telegram_bot.workflow import lead_criteria,search_enabled
    user=call.from_user.id;lead=own_lead(user);parts=call.data.split(':')
    if not lead or (not search_enabled(lead) and not (len(parts)==3 and parts[1]=='reschedule')): raise ValueError('ابتدا یک نیاز فعال ثبت کنید.')
    store=DecisionStore();signature=fingerprint(lead_criteria(lead))
    if len(parts)==2 and parts[1]=='compare':
        text,markup=comparison_view(user,lead)
        bot.edit_message_text(text,chat_id=user,message_id=call.message.message_id,reply_markup=markup,parse_mode='HTML')
    elif len(parts)==3 and parts[1]=='compare_page' and parts[2].isascii() and parts[2].isdigit():
        text,markup=comparison_view(user,lead,page=min(int(parts[2]),10000))
        bot.edit_message_text(text,chat_id=user,message_id=call.message.message_id,reply_markup=markup,parse_mode='HTML')
    elif len(parts) in (4,5) and parts[1]=='pick' and parts[2] in ('property','listing','archive') and parts[3].isascii() and parts[3].isdigit():
        if len(parts)==5 and (not parts[4].isascii() or not parts[4].isdigit()): raise ValueError('صفحه معتبر نیست.')
        text,markup=comparison_view(user,lead,parts[2]+':'+parts[3],page=min(int(parts[4]),10000) if len(parts)==5 else 0)
        bot.edit_message_text(text,chat_id=user,message_id=call.message.message_id,reply_markup=markup,parse_mode='HTML')
    elif len(parts)==2 and parts[1]=='relax': show_relaxations(bot,user,lead)
    elif len(parts)==3 and parts[1]=='reschedule' and parts[2].isascii() and parts[2].isdigit():
        interaction,created=request_reschedule(user,int(parts[2]))
        bot.send_message(user,'درخواست تغییر زمان '+('ثبت شد' if created else 'قبلاً ثبت شده است')+'؛ وقت قبلی تا هماهنگی کارشناس و تأیید زمان جایگزین محفوظ می‌ماند.')
    elif len(parts)==3 and parts[1]=='apply':
        option=store.action(parts[2],user,signature,'relax')
        # Recheck inventory and access: a stale count must not be sold as available.
        options=relaxation_options(lead,relaxation_pool(lead))
        if not any(row['changes']==option['changes'] for row in options): raise ValueError('موجودی تغییر کرده؛ پیشنهاد تازه بگیرید.')
        flow=getattr(bot,'saghf_customer_flow',None)
        if flow is None: raise ValueError('فرم مشتری در دسترس نیست.')
        from telegram_bot.customer_panel import registered_data
        state=copy.deepcopy(flow.store.get(user)); data=registered_data(user)
        if not data: raise ValueError('نیاز ثبت‌شده‌ای ندارید.')
        data.update({key:value for key,value in state['data'].items() if key in ('phone','contact_shared_at')})
        data.update(option['changes'])
        step='review' if data.get('phone') and data.get('contact_shared_at') else 'contact'
        state.update(data=data,step=step,draft_dirty=True)
        flow.store.save(user,state);store.consume(parts[2])
        flow.show(SimpleNamespace(chat=call.message.chat,from_user=call.from_user),state)
    elif len(parts)==4 and parts[1]=='slot' and parts[3].isascii() and parts[3].isdigit():
        payload=store.action(parts[2],user,signature,'slots')
        interaction=db.session.get(Interaction,payload['interaction_id'])
        if not interaction or interaction.client_id!=lead.client_id or interaction.type!='saghf_visit' or interaction.outcome!='pending':
            raise ValueError('درخواست بازدید دیگر معتبر نیست.')
        from telegram_bot.customer_panel import recommendations
        if not any([item['source_type'],item['id']]==payload.get('item') for item in recommendations(user)):
            raise ValueError('فایل بازدید دیگر قابل دسترسی نیست.')
        slot=store.set_preference(parts[2],user,signature,int(parts[3]))
        bot.edit_message_text('ترجیح زمانی ثبت شد: '+slot['label']+' تهران. کارشناس باید زمان را پیشنهاد کند و شما تأیید کنید؛ بازدید هنوز قطعی نیست.',chat_id=user,message_id=call.message.message_id)
    else: raise ValueError('گزینه معتبر نیست.')
    return bot.answer_callback_query(call.id)
