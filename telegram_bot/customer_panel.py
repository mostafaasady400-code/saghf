"""Customer-owned recommendations and follow-ups in the shared CRM."""
import html
import os
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.db import db
from database.models import CustomerLead, Interaction, Visit, Property, PropertyListing
from telegram_bot.workflow import search_enabled, current_case


class PanelSelection(db.Model):
    __tablename__ = 'telegram_panel_selections'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), nullable=False, index=True)
    source_type = db.Column(db.String(20), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    saved = db.Column(db.Boolean, default=False, nullable=False)
    rejected = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('telegram_id', 'source_type', 'source_id'),)


class PanelSetting(db.Model):
    __tablename__ = 'telegram_panel_settings'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(100), nullable=False)


def ensure_customer_schema():
    PanelSelection.__table__.create(db.engine, checkfirst=True)
    PanelSetting.__table__.create(db.engine, checkfirst=True)


def own_lead(telegram_id):
    return CustomerLead.query.filter_by(contact_key=f'telegram:{telegram_id}').first()


def route_client(client):
    if client.assigned_agent_id:
        return
    from telegram_bot.office_access import OfficeMembership, principal_for
    value = os.environ.get('TELEGRAM_DEFAULT_AGENT_ID', '')
    if not value:
        setting = db.session.get(PanelSetting, 'default_agent_id')
        value = setting.value if setting else ''
    if not value.isdigit():
        return
    member = OfficeMembership.query.filter_by(agent_id=int(value), active=True).first()
    if member and principal_for(member.telegram_id):
        client.assigned_agent_id = int(value)
        db.session.commit()


def registered_data(telegram_id):
    lead = own_lead(telegram_id)
    if not lead or not lead.crm_client:
        return None
    client = lead.crm_client
    return dict(deal_type=lead.deal_type, district='، '.join(lead.preferred_districts), districts=lead.preferred_districts,
        phone_shared=lead.has_real_phone,
        max_budget=lead.max_budget or 0, max_deposit=lead.max_deposit or 0, max_rent=lead.max_rent or 0,
        min_area=client.min_area or 0, max_area=client.max_area or 0, min_rooms=client.min_rooms or 0,
        preferred_features=[x for x in lead.preferred_features if x != 'رهن کامل'],
        urgency=client.urgency, urgency_label={'immediate': 'فوری', 'normal': 'تا یک ماه',
        'looking': 'فعلاً بررسی می‌کنم'}.get(client.urgency, 'مشخص نشده'))


def customer_home(telegram_id):
    lead = own_lead(telegram_id)
    if not lead or not lead.crm_client:
        return 'هنوز نیاز ملکی ثبت نکرده‌اید. از «جست‌وجوی ملک» شروع کنید.'
    pending = Interaction.query.filter_by(client_id=lead.client_id, outcome='pending').count()
    visits = Visit.query.filter_by(client_id=lead.client_id, status='scheduled').count()
    saved = PanelSelection.query.filter_by(telegram_id=str(telegram_id), saved=True).count()
    label = 'فعال' if search_enabled(lead) else 'متوقف'
    case = current_case(lead)
    request = f'درخواست #{case.id}\n' if case else ''
    responsible = 'مشاور تخصیص یافته' if lead.crm_client.assigned_agent_id else 'منتظر تخصیص مسئول'
    return f'{request}جست‌وجوی شما: {label} | {responsible}\nنشان‌شده‌ها: {saved} | بازدید برنامه‌ریزی‌شده: {visits}\nدرخواست‌های منتظر رسیدگی: {pending}'


def _fits(item, lead):
    client = lead.crm_client
    if not client or not search_enabled(lead):
        return False
    if item.get('deal_type') != lead.deal_type or item.get('city') not in ('تهران', 'tehran'):
        return False
    if (item.get('area') is None or client.min_area is None or client.max_area is None
            or not client.min_area <= item['area'] <= client.max_area):
        return False
    if client.min_rooms and (item.get('rooms') is None or item['rooms'] < client.min_rooms):
        return False
    from data.tehran_districts import REGION_2_DISTRICT_NAMES, REGION_5_DISTRICT_NAMES
    names = []
    for name in lead.preferred_districts or []:
        names.extend(REGION_2_DISTRICT_NAMES if name in ('منطقه ۲', 'منطقه 2') else
            REGION_5_DISTRICT_NAMES if name in ('منطقه ۵', 'منطقه 5') else [name])
    district = (item.get('district') or '').replace('\u200c', ' ')
    if not names or not any(name.replace('\u200c', ' ') in district for name in names):
        return False
    budgets = [('total_price', lead.max_budget)] if lead.deal_type == 'sale' else [
        ('deposit', lead.max_deposit), ('monthly_rent', lead.max_rent)]
    if any(item.get(key) is None or item[key] < 0 or item[key] > (limit or 0) for key, limit in budgets):
        return False
    from telegram_bot.amenities import extra_features_match
    return extra_features_match(item, lead.preferred_features) and all(not getattr(client, required) or bool(item.get(column)) for required, column in (
        ('must_have_parking', 'has_parking'), ('must_have_elevator', 'has_elevator'),
        ('must_have_warehouse', 'has_warehouse')))


def _source_visible(item, lead):
    """A score never grants access to another office's private files."""
    kind = item.get('source_type')
    if kind == 'archive':
        return True  # archive_matches enforces freshness and owner guards.
    model = Property if kind == 'property' else PropertyListing
    row = db.session.get(model, item.get('id'))
    if not row or row.property_type != 'apartment' or row.is_personal_owner is not True:
        return False
    if kind == 'listing':
        from crawler.strict_owner_guard import strict_decision
        return bool(row.published_at and datetime.utcnow() - timedelta(hours=24) <= row.published_at <= datetime.utcnow()
                    and strict_decision(row.title, row.description).allowed)
    if row.status not in ('verified', 'available') or row.owner_type != 'personal':
        return False
    # Public website-extracted rows are shared inventory, not private office files.
    parsed = urlsplit(row.source_url or '')
    if (row.source == 'divar' and row.assigned_agent_id is None
            and parsed.scheme == 'https' and parsed.hostname in ('divar.ir', 'www.divar.ir')
            and parsed.path.startswith('/v/')):
        from crawler.strict_owner_guard import strict_decision
        return strict_decision(row.title, row.description).allowed
    client_agent = lead.crm_client.assigned_agent_id
    if not client_agent:
        return False
    from telegram_bot.office_access import OfficeMembership, principal_for
    member = OfficeMembership.query.filter_by(agent_id=client_agent, active=True).first()
    principal = principal_for(member.telegram_id) if member else None
    if not principal:
        return False
    team = [x.agent_id for x in OfficeMembership.query.filter_by(office_key=member.office_key, active=True)
            if principal_for(x.telegram_id)]
    return row.assigned_agent_id in team


def recommendations(telegram_id):
    lead = own_lead(telegram_id)
    if not search_enabled(lead):
        return []
    from services.regional_matching import RegionalPropertyMatcher
    from telegram_bot.extraction_jobs import archive_matches
    client = lead.crm_client
    criteria = dict(deal_type=lead.deal_type, preferred_districts=lead.preferred_districts,
        min_area=client.min_area, max_area=client.max_area, min_rooms=client.min_rooms,
        max_budget=lead.max_budget, max_deposit=lead.max_deposit, max_rent=lead.max_rent,
        preferred_features=lead.preferred_features)
    items = RegionalPropertyMatcher.match_lead(lead, limit=30)
    for listing in archive_matches(criteria):
        item = {key: getattr(listing, key, None) for key in ('title', 'district', 'city', 'deal_type',
            'area', 'rooms', 'total_price', 'deposit', 'monthly_rent', 'source_url',
            'has_parking', 'has_elevator', 'has_warehouse')}
        item.update(source_type='archive', id=listing.id)
        item.update(images=listing.images, features=listing.features, has_balcony=listing.has_balcony,
            published_at=listing.published_at.isoformat() if listing.published_at else None)
        items.append(item)
    result, seen, urls = [], set(), set()
    for item in items:
        if item.get('source_type') in ('property', 'listing'):
            model = Property if item['source_type'] == 'property' else PropertyListing
            row = db.session.get(model, item.get('id'))
            if row is not None:
                item['features'] = getattr(row, 'features', [])
        key = (item.get('source_type'), item.get('id'))
        if key[0] not in ('property', 'listing', 'archive') or not key[1] or key in seen or not _fits(item, lead) or not _source_visible(item, lead):
            continue
        url = item.get('source_url')
        if url and url in urls:
            continue
        selection = PanelSelection.query.filter_by(telegram_id=str(telegram_id), source_type=key[0], source_id=key[1]).first()
        if not selection or not selection.rejected:
            result.append(item)
            seen.add(key)
            if url:
                urls.add(url)
    return result


def formatted_amount(value):
    if value is None or isinstance(value,bool):
        return 'نامشخص'
    try:
        amount = int(value)
    except (ValueError,TypeError,OverflowError):
        return 'نامشخص'
    if amount < 0:
        return 'نامشخص'
    if amount >= 1_000_000_000:
        text = f'{amount / 1_000_000_000:g} میلیارد'
    elif amount >= 1_000_000:
        text = f'{amount / 1_000_000:g} میلیون'
    else:
        text = f'{amount:,}'
    return text.translate(str.maketrans('0123456789,','۰۱۲۳۴۵۶۷۸۹٬'))


def card(bot, telegram_id, item, saved=False):
    def esc(value):
        return html.escape(str(value if value is not None else 'نامشخص'))
    text = f"{esc(item['title'])}\n{esc(item.get('district'))} | {esc(item.get('area'))} متر | {esc(item.get('rooms'))} خواب\n"
    if item.get('deal_type') == 'sale':
        text += f"قیمت: {formatted_amount(item.get('total_price'))} تومان"
    else:
        text += f"ودیعه: {formatted_amount(item.get('deposit'))} | اجاره: {formatted_amount(item.get('monthly_rent'))} تومان"
    text += '\nمنبع: ' + ('آرشیو آگهی؛ نتیجه زنده نیست' if item['source_type'] != 'property' or urlsplit(item.get('source_url') or '').hostname in ('divar.ir', 'www.divar.ir') else 'فایل داخلی سقف')
    from telegram_bot.decision_support import match_explanation
    text += '\nدلیل پیشنهاد: '+esc(match_explanation(item))
    url = item.get('source_url') or ''
    parsed = urlsplit(url)
    if parsed.scheme == 'https' and parsed.hostname in ('divar.ir', 'www.divar.ir'):
        text += f'\n<a href="{html.escape(url, quote=True)}">لینک آگهی</a>'
    token = f"{item['source_type']}:{item['id']}"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton('حذف نشان' if saved else 'پسندیدم', callback_data=f"customer:{'unsave' if saved else 'save'}:{token}"),
        InlineKeyboardButton('مناسب نیست', callback_data=f'customer:reject:{token}'))
    markup.add(InlineKeyboardButton('درخواست بازدید', callback_data=f'customer:visit:{token}'))
    images = item.get('images') or []
    photo = next((value for value in images if isinstance(value, str)
        and urlsplit(value).scheme == 'https'
        and not urlsplit(value).username and not urlsplit(value).password
        and urlsplit(value).hostname and any(urlsplit(value).hostname == host or
            urlsplit(value).hostname.endswith('.'+host) for host in ('divarcdn.com', 'divarcdn.ir', 'divar.ir'))), None)
    if photo:
        try:
            if len(text) <= 1024:
                bot.send_photo(telegram_id, photo, caption=text, parse_mode='HTML', reply_markup=markup)
                return
            bot.send_photo(telegram_id, photo)
        except Exception:
            from telegram_bot.telemetry import record_event
            record_event('photo_fallback')
            text += '\nتصویر در دسترس نبود؛ مشخصات بدون تصویر نمایش داده می‌شود.'
    else:
        text += '\nتصویر قابل نمایش در دسترس نیست.'
    bot.send_message(telegram_id, text, parse_mode='HTML', reply_markup=markup)


from telegram_bot.outbound_policy import matching_response


@matching_response
def show_recommendations(bot, telegram_id, saved=False, page=0, refresh=True, new_only=False):
    items = recommendations(telegram_id)
    if saved:
        keys = {(row.source_type, row.source_id) for row in PanelSelection.query.filter_by(telegram_id=str(telegram_id), saved=True)}
        items = [item for item in items if (item['source_type'], item['id']) in keys]
    from telegram_bot.search_delivery import NotificationStore, fingerprint, item_key
    from telegram_bot.workflow import lead_criteria
    store = NotificationStore()
    lead = own_lead(telegram_id)
    if new_only and refresh:
        items = store.unseen_items(telegram_id,items)
    if lead:
        items = store.ordered_page_items(telegram_id, fingerprint(lead_criteria(lead)), items, 2 if new_only else saved, refresh)
    if not items:
        empty_markup=InlineKeyboardMarkup()
        empty_markup.row(InlineKeyboardButton('پیشنهاد اصلاح فیلتر',callback_data='decision:relax'),InlineKeyboardButton('اصلاح نیاز من',callback_data='customer:edit'))
        bot.send_message(telegram_id, 'فعلاً فایل منطبق و قابل نمایش ندارید؛ این پیام به معنی پوشش کامل جست‌وجو نیست.'
            if not saved else 'ملک نشان‌شده‌ای که هنوز با شرایط فعلی منطبق و قابل نمایش باشد ندارید.', reply_markup=empty_markup)
    if not isinstance(page, int) or not 0 <= page <= 100000:
        raise ValueError('صفحه معتبر نیست.')
    if not items and new_only:
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('همه پیشنهادها',callback_data='customer:refresh'),InlineKeyboardButton('اصلاح نیاز من',callback_data='customer:edit'))
        bot.send_message(telegram_id,'مورد مشاهده‌نشده‌ای ندارید؛ همه پیشنهادها همچنان قابل بررسی‌اند.',reply_markup=markup)
    page_size = 4
    page = min(page, max(0, (len(items)-1)//page_size))
    for item in items[page*page_size:(page+1)*page_size]:
        card(bot, telegram_id, item, saved)
        store.mark_seen(telegram_id, [item_key(item)])
    if items:
        markup = InlineKeyboardMarkup()
        buttons=[]
        if page:
            buttons.append(InlineKeyboardButton('صفحه قبل', callback_data=f'customer:new_page:{page-1}' if new_only else f'customer:page:{int(saved)}:{page-1}'))
        if (page+1)*page_size < len(items):
            buttons.append(InlineKeyboardButton('صفحه بعد', callback_data=f'customer:new_page:{page+1}' if new_only else f'customer:page:{int(saved)}:{page+1}'))
        if buttons: markup.row(*buttons)
        markup.row(InlineKeyboardButton('جدیدها', callback_data='customer:new'),InlineKeyboardButton('همه پیشنهادها', callback_data='customer:refresh'))
        markup.row(InlineKeyboardButton('مقایسه نشان‌شده‌ها',callback_data='decision:compare'),InlineKeyboardButton('پیشنهاد اصلاح فیلتر',callback_data='decision:relax'))
        markup.row(InlineKeyboardButton('اصلاح نیاز من', callback_data='customer:edit'))
        markup.row(InlineKeyboardButton('بازگشت به منوی مشتری', callback_data='customer:home'))
        bot.send_message(telegram_id, f'صفحه {page+1} از {max(1,(len(items)+page_size-1)//page_size)} | {len(items)} پیشنهاد قابل نمایش', reply_markup=markup)


def request_followup(telegram_id, kind='saghf_support', item=None):
    lead = own_lead(telegram_id)
    if not lead or not lead.crm_client:
        raise ValueError('ابتدا نیاز ملکی خود را ثبت کنید.')
    client = lead.crm_client
    if not search_enabled(lead):
        raise ValueError('جست‌وجو متوقف است؛ ابتدا درخواست را دوباره فعال کنید.')
    property_id = item['id'] if item and item['source_type'] == 'property' else None
    label = f"هماهنگی بازدید: {item['source_type']}:{item['id']}" if item else 'درخواست تماس مشتری از بات سقف'
    previous = Interaction.query.filter_by(client_id=client.id, type=kind, outcome='pending', property_id=property_id, summary=label).first()
    if previous:
        return previous, False
    row = Interaction(client_id=client.id, target_type='client', target_id=client.id,
        agent_id=client.assigned_agent_id, property_id=property_id, type=kind, outcome='pending',
        summary=label, next_followup_date=datetime.utcnow())
    db.session.add(row)
    db.session.flush()
    from telegram_bot.workflow import audit
    case = current_case(lead)
    audit(lead.contact_key, 'followup_requested', row.id, case_id=case.id if case else None, agent_id=client.assigned_agent_id)
    db.session.commit()
    return row, True


def tracking_text(telegram_id):
    lead = own_lead(telegram_id)
    if not lead or not lead.client_id:
        return 'هنوز درخواست ثبت‌شده‌ای ندارید.'
    lines = ['پیگیری‌های شما (زمان‌ها به وقت تهران):', 'مسئول پرونده تعیین شده است.' if lead.crm_client and lead.crm_client.assigned_agent_id else 'درخواست ثبت شده؛ منتظر تعیین مسئول پرونده.']
    case = current_case(lead)
    if case:
        lines.append(f"درخواست #{case.id}: {'فعال' if search_enabled(lead) else 'متوقف'}")
    from telegram_bot.extraction_jobs import ExtractionJobs
    extraction = ExtractionJobs().latest_status(telegram_id)
    if extraction:
        labels = {'queued': 'در صف استخراج', 'running': 'در حال بررسی', 'ready': 'بررسی انجام شد',
            'empty': 'فایل منطبق پیدا نشد؛ پوشش کامل تأیید نشده', 'failed': 'استخراج کامل نشد',
            'delivery_unknown': 'وضعیت تحویل نامعلوم', 'delivering': 'در حال تحویل', 'cancelled': 'لغو شده'}
        lines.append('استخراج: ' + labels.get(extraction, 'نیازمند بررسی'))
    rows = Interaction.query.filter_by(client_id=lead.client_id).filter(Interaction.type.in_(
        ['saghf_support', 'saghf_visit'])).order_by(Interaction.id.desc()).limit(8).all()
    labels = {'pending': 'ثبت شد؛ منتظر رسیدگی کارشناس', 'contacted': 'تماس ثبت شد', 'completed': 'رسیدگی شد', 'resolved': 'رسیدگی شد', 'cancelled': 'لغو شد'}
    for row in rows:
        lines.append(f"درخواست {row.id}: {labels.get(row.outcome, 'در حال پیگیری')}")
    from telegram_bot.workflow import VisitProposal, valid_proposal
    from telegram_bot.office_flow import _when
    for proposal in VisitProposal.query.filter_by(customer_id=str(telegram_id),state='pending').limit(5):
        if valid_proposal(proposal):
            lines.append(f'زمان بازدید پیشنهاد شده: {_when(proposal.scheduled_at)}؛ منتظر تأیید شما.')
    for visit in Visit.query.filter_by(client_id=lead.client_id).order_by(Visit.scheduled_time.desc()).limit(5):
        label = {'scheduled': 'برنامه‌ریزی‌شده', 'completed': 'انجام‌شده', 'cancelled': 'لغو شده', 'no_show': 'عدم حضور'}.get(visit.status, 'نامشخص')
        from telegram_bot.office_flow import _when
        lines.append(f'بازدید {visit.id}: {_when(visit.scheduled_time)} — {label}')
    return '\n'.join(lines) if len(lines) > 1 else 'هنوز درخواست تماس یا بازدید ثبت نشده است.'


def register_customer_callbacks(bot, app_provider):
    def callback(call):
        user = call.from_user
        if not user or user.is_bot or not call.message or call.message.chat.type != 'private' or call.message.chat.id != user.id:
            return bot.answer_callback_query(call.id, 'دسترسی مجاز نیست.')
        try:
            if call.data.startswith('decision:'):
                with app_provider().app_context():
                    from telegram_bot.decision_support import handle_callback
                    return handle_callback(bot,call)
            if call.data == 'customer:daily_off':
                with app_provider().app_context():
                    from telegram_bot.search_delivery import NotificationStore
                    NotificationStore().disable(user.id)
                return bot.answer_callback_query(call.id, 'اعلان روزانه قطع شد؛ جست‌وجو و تطبیق محفوظ‌اند.')
            if call.data == 'customer:search_status':
                with app_provider().app_context():
                    from telegram_bot.extraction_jobs import ExtractionJobs
                    import time
                    job = ExtractionJobs().latest_job(user.id)
                    labels = {'queued': 'در صف بررسی', 'running': 'جست‌وجوی آنلاین در حال بررسی',
                        'ready': 'موارد منطبق برای مشاهده آماده‌اند', 'empty': 'فایل جدید قابل نمایش پیدا نشد؛ پوشش کامل تأیید نشده',
                        'failed': 'استخراج زنده تأیید نشد؛ وضعیت اتصال نیازمند بررسی است', 'cancelled': 'این درخواست متوقف یا جایگزین شده'}
                    text = labels.get(job['state'], 'وضعیت نامشخص') if job else 'درخواست جست‌وجوی آنلاین ندارید.'
                    if job and job['state'] == 'running':
                        text += f'\nزمان سپری‌شده: {int(max(0, time.time()-job["updated"]))} ثانیه؛ بودجه اجرای موتور: حداکثر ۱۸۰ ثانیه.'
                    markup = InlineKeyboardMarkup()
                    markup.row(InlineKeyboardButton('به‌روزرسانی وضعیت', callback_data='customer:search_status'))
                    markup.row(InlineKeyboardButton('مشاهده تطبیق هوشمند', callback_data='customer:page:0:0'))
                    bot.edit_message_text(text, chat_id=user.id, message_id=call.message.message_id, reply_markup=markup)
                return bot.answer_callback_query(call.id)
            if call.data == 'customer:home':
                from telegram_bot.customer_flow import MAIN, keyboard
                with app_provider().app_context():
                    text = customer_home(user.id)
                bot.send_message(user.id, text, reply_markup=keyboard(MAIN))
                return bot.answer_callback_query(call.id)
            if call.data == 'customer:edit':
                from types import SimpleNamespace
                from telegram_bot.customer_flow import EDIT
                flow = getattr(bot,'saghf_customer_flow',None)
                if flow is None:
                    return bot.answer_callback_query(call.id,'برای اصلاح نیاز، منوی مشتری را باز کنید.')
                bot.answer_callback_query(call.id)
                return flow.handle(SimpleNamespace(from_user=user,chat=call.message.chat,text=EDIT,content_type='text'))
            if call.data == 'customer:new' or call.data.startswith('customer:new_page:'):
                page=0
                if call.data != 'customer:new':
                    raw=call.data.split(':')[-1]
                    if not raw.isascii() or not raw.isdigit():
                        raise ValueError('صفحه معتبر نیست.')
                    page=int(raw)
                with app_provider().app_context():
                    show_recommendations(bot,user.id,page=page,refresh=call.data=='customer:new',new_only=True)
                return bot.answer_callback_query(call.id)
            if call.data == 'customer:refresh':
                with app_provider().app_context():
                    show_recommendations(bot,user.id,refresh=True)
                return bot.answer_callback_query(call.id)
            if call.data.startswith('customer:page:'):
                parts=call.data.split(':')
                if len(parts)!=4 or parts[2] not in ('0','1') or not parts[3].isascii() or not parts[3].isdigit():
                    raise ValueError('صفحه معتبر نیست.')
                with app_provider().app_context():
                    show_recommendations(bot, user.id, parts[2]=='1', int(parts[3]), refresh=False)
                return bot.answer_callback_query(call.id)
            if call.data.startswith('customer:reason:'):
                _, _, source, raw_id, reason = call.data.split(':')
                from telegram_bot.workflow import REASONS, RecommendationFeedback, audit
                if source not in ('property', 'listing', 'archive') or not raw_id.isascii() or not raw_id.isdigit() or reason not in REASONS:
                    raise ValueError('گزینه معتبر نیست.')
                with app_provider().app_context():
                    selection = PanelSelection.query.filter_by(telegram_id=str(user.id), source_type=source, source_id=int(raw_id), rejected=True).first()
                    if not selection:
                        raise ValueError('ابتدا همین پیشنهاد را رد کنید.')
                    row = RecommendationFeedback.query.filter_by(telegram_id=str(user.id), source_type=source, source_id=int(raw_id)).first()
                    if row is None:
                        row = RecommendationFeedback(telegram_id=str(user.id), source_type=source, source_id=int(raw_id))
                        db.session.add(row)
                    row.reason, row.updated_at = reason, datetime.utcnow()
                    audit(f'telegram:{user.id}', 'recommendation_rejected', int(raw_id), reason=reason)
                    db.session.commit()
                return bot.answer_callback_query(call.id, 'علت رد ثبت شد؛ شرایط جست‌وجوی شما تغییر نکرد.')
            _, action, source, raw_id = call.data.split(':')
            if action not in ('save', 'unsave', 'reject', 'visit') or not raw_id.isdigit():
                raise ValueError('گزینه معتبر نیست.')
            with app_provider().app_context():
                item = next((item for item in recommendations(user.id) if item['source_type'] == source and item['id'] == int(raw_id)), None)
                if not item:
                    raise ValueError('این فایل دیگر برای درخواست شما قابل اقدام نیست.')
                if action == 'visit':
                    row, created = request_followup(user.id, 'saghf_visit', item)
                    text = f"درخواست {row.id} {'ثبت شد' if created else 'قبلاً ثبت شده'}؛ بازدید هنوز قطعی نشده است."
                    from telegram_bot.decision_support import show_slots
                    show_slots(bot,user.id,own_lead(user.id),row,item)
                else:
                    selection = PanelSelection.query.filter_by(telegram_id=str(user.id), source_type=source, source_id=item['id']).first()
                    if not selection:
                        selection = PanelSelection(telegram_id=str(user.id), source_type=source, source_id=item['id'])
                        db.session.add(selection)
                    if action in ('save', 'unsave'):
                        selection.saved = action == 'save'
                    else:
                        selection.rejected, selection.saved = True, False
                    selection.updated_at = datetime.utcnow()
                    db.session.commit()
                    text = 'انتخاب شما ثبت شد.'
                    if action == 'reject':
                        from telegram_bot.workflow import REASONS
                        markup = InlineKeyboardMarkup(row_width=2)
                        for reason, label in REASONS.items():
                            markup.add(InlineKeyboardButton(label, callback_data=f'customer:reason:{source}:{item["id"]}:{reason}'))
                        bot.send_message(user.id, 'چه چیزی در این پیشنهاد مناسب نبود؟', reply_markup=markup)
            bot.answer_callback_query(call.id, text[:180])
        except ValueError as exc:
            from telegram_bot.telemetry import record_event
            with app_provider().app_context(): record_event('invalid_callback')
            bot.answer_callback_query(call.id, str(exc)[:180])
        except Exception:
            from telegram_bot.telemetry import record_event
            with app_provider().app_context():
                record_event('callback_error')
                db.session.rollback()
            bot.answer_callback_query(call.id, 'عملیات کامل نشد؛ دوباره تلاش کنید.')
    bot.register_callback_query_handler(callback, func=lambda call: bool(call.data and call.data.startswith(('customer:','decision:'))))


def show_visit_actions(bot, telegram_id):
    from telegram_bot.workflow import VisitProposal, VisitReview, valid_proposal
    from telegram_bot.office_flow import _when
    lead = own_lead(telegram_id)
    if not lead:
        return
    for visit in Visit.query.filter_by(client_id=lead.client_id,status='scheduled').filter(Visit.scheduled_time>datetime.utcnow()).order_by(Visit.scheduled_time).limit(5):
        markup=InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('درخواست تغییر زمان',callback_data=f'decision:reschedule:{visit.id}'))
        bot.send_message(telegram_id,f'بازدید #{visit.id}: {_when(visit.scheduled_time)} تهران؛ وقت ثبت‌شده فعلی.',reply_markup=markup)
    for proposal in VisitProposal.query.filter_by(customer_id=str(telegram_id), state='pending').limit(5):
        if valid_proposal(proposal):
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton('تأیید زمان', callback_data=f'workflow:accept:{proposal.id}'),
                InlineKeyboardButton('زمان دیگر', callback_data=f'workflow:decline:{proposal.id}'))
            bot.send_message(telegram_id, f'پیشنهاد بازدید #{proposal.id}: {_when(proposal.scheduled_at)} تهران', reply_markup=markup)
    for visit in Visit.query.filter_by(client_id=lead.client_id, status='completed').order_by(Visit.id.desc()).limit(5):
        if db.session.get(VisitReview, visit.id):
            continue
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton('پسندیدم', callback_data=f'workflow:liked:{visit.id}'),
            InlineKeyboardButton('مناسب نبود', callback_data=f'workflow:not_suitable:{visit.id}'))
        bot.send_message(telegram_id, f'نتیجه بازدید #{visit.id} برای شما چگونه بود؟', reply_markup=markup)
