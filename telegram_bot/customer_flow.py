# Telegram-native customer menu and persistent, validated property demand form.
import json
import sqlite3
import time
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path

from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from config import BASE_DIR
from services.inbound_identity import normalize_iran_phone

FIND = 'جست‌وجوی ملک'
EDIT = 'ویرایش نیاز من'
PROFILE = 'شرایط جست‌وجوی من'
SUGGESTIONS = 'تطبیق هوشمند من'
TRACKING = 'پیگیری و بازدید'
SUPPORT = 'ارتباط با کارشناس'
SAVED = 'ملک‌های نشان‌شده'
MAIN = [FIND, SUGGESTIONS, TRACKING, SAVED, SUPPORT]
BACK = 'برگشت'
CANCEL = 'منوی اصلی'
SHARE = 'اشتراک‌گذاری شماره خودم'
SKIP = 'ادامه بدون شماره'
CONFIRM = 'تأیید و تطبیق'
FEATURES = ['پارکینگ', 'آسانسور', 'انباری', 'بالکن', 'لابی', 'لابی‌من', 'سرایدار',
    'دوربین مداربسته', 'استخر', 'سونا', 'جکوزی', 'روف‌گاردن', 'سالن ورزش', 'سالن اجتماعات']
FEATURE_DONE = 'تأیید امکانات'
AREA_PRESETS = {
    '۵۰ تا ۷۰ متر، یک‌خواب': '50-70 / 1',
    '۷۰ تا ۹۰ متر، دوخواب': '70-90 / 2',
    '۹۰ تا ۱۲۰ متر، دوخواب': '90-120 / 2',
    '۱۲۰ تا ۱۶۰ متر، سه‌خواب': '120-160 / 3',
}
REGION_LABELS = {'منطقه ۱': '1', 'منطقه ۲': '2', 'منطقه ۵': '5'}
DISTRICT_DONE = 'تأیید محله‌ها'
CHANGE_REGION = 'تغییر منطقه'
DEPOSIT_TITLE = 'سقف رهن'
RENT_TITLE = 'سقف اجاره'
BUDGET_DONE = 'تأیید بودجه'
DEPOSIT_AMOUNTS = {'۵۰۰ میلیون تومان': 500000000, '۱ میلیارد تومان': 1000000000,
    '۲ میلیارد تومان': 2000000000, '۳ میلیارد تومان': 3000000000, '۴ میلیارد تومان': 4000000000,
    '۵ میلیارد تومان': 5000000000, '۶ میلیارد تومان': 6000000000, '۷ میلیارد تومان': 7000000000,
    '۸ میلیارد تومان': 8000000000, '۹ میلیارد تومان': 9000000000, '۱۰ میلیارد تومان': 10000000000}
RENT_AMOUNTS = {'بدون اجاره؛ رهن کامل': 0, '۱۵ میلیون تومان': 15000000,
    '۳۰ میلیون تومان': 30000000, '۴۵ میلیون تومان': 45000000,
    '۶۰ میلیون تومان': 60000000, '۸۰ میلیون تومان': 80000000,
    '۱۰ میلیون تومان': 10000000, '۲۰ میلیون تومان': 20000000, '۶۵ میلیون تومان': 65000000,
    '۷۵ میلیون تومان': 75000000, '۹۰ میلیون تومان': 90000000, '۱۰۰ میلیون تومان': 100000000,
    '۱۰۵ میلیون تومان': 105000000, '۱۲۰ میلیون تومان': 120000000,
    '۱۳۵ میلیون تومان': 135000000, '۱۵۰ میلیون تومان': 150000000}
RENT_AMOUNTS = dict(sorted(RENT_AMOUNTS.items(), key=lambda item: item[1]))


def district_options(region=None, selected=()):
    from data.tehran_districts import get_district_names
    if region not in REGION_LABELS.values():
        return list(REGION_LABELS)
    names = get_district_names(region)
    return [*[
        ('انتخاب‌شده: ' if name in selected else '') + name for name in names
    ], DISTRICT_DONE, CHANGE_REGION]


class FormStore:
    def __init__(self, path=None):
        self.path = Path(path or BASE_DIR / 'instance' / 'telegram-customer-forms.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS customer_forms (user_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL)')

    def get(self, user_id):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute('SELECT state, updated FROM customer_forms WHERE user_id=?', (str(user_id),)).fetchone()
        if not row or time.time() - row[1] > 30 * 86400:
            return {'step': 'menu', 'data': {}}
        return json.loads(row[0])

    def save(self, user_id, state):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO customer_forms VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, updated=excluded.updated',
                         (str(user_id), json.dumps(state, ensure_ascii=False), time.time()))


def keyboard(labels, contact=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, is_persistent=False, one_time_keyboard=False)
    if labels[:2] == [DEPOSIT_TITLE, RENT_TITLE]:
        markup.row(KeyboardButton(DEPOSIT_TITLE, style='primary'), KeyboardButton(RENT_TITLE, style='primary'))
        markup.row(KeyboardButton(BUDGET_DONE, style='success'))
        markup.row(KeyboardButton(BACK), KeyboardButton(CANCEL))
        for index in range(5, len(labels), 2):
            markup.row(*(KeyboardButton(label) for label in labels[index:index + 2]))
        return markup
    if labels[:len(REGION_LABELS)] == list(REGION_LABELS) or DISTRICT_DONE in labels or labels[:1] == [DEPOSIT_TITLE]:
        for label in labels:
            markup.row(KeyboardButton(label))
        return markup
    if labels[:len(MAIN)] == MAIN:
        markup.row(KeyboardButton(FIND))
        markup.row(KeyboardButton(SUGGESTIONS))
        markup.row(KeyboardButton(TRACKING))
        markup.row(KeyboardButton(SAVED), KeyboardButton(SUPPORT))
        for label in labels[len(MAIN):]:
            markup.row(KeyboardButton(label))
        return markup
    for index in range(0, len(labels), 2):
        markup.row(*(KeyboardButton(label, request_contact=(contact and label == SHARE)) for label in labels[index:index + 2]))
    return markup


def steps(data):
    budget = ['max_budget'] if data.get('deal_type') == 'sale' else ['max_deposit', 'max_rent']
    contact = [] if data.get('phone') else ['contact']
    return ['deal_type', 'area', 'min_rooms', 'district', *budget, 'features', 'urgency', *contact, 'review']


def money(text):
    cleaned = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).replace(',', '').replace('٬', '').replace('٫', '.')
    try:
        amount = Decimal(cleaned)
        if not amount.is_finite() or amount < 0 or amount > 1_000_000:
            raise ValueError()
        return int(amount * 1_000_000)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('مبلغ را فقط به عدد و با واحد میلیون تومان وارد کنید؛ مثلاً ۵۰۰ یا ۱۵٫۵.') from None


def summary(data):
    deal = 'خرید' if data.get('deal_type') == 'sale' else 'رهن کامل' if data.get('max_rent') == 0 else 'رهن و اجاره'
    financial = ('بودجه خرید: ' + format(data.get('max_budget', 0), ',') if data.get('deal_type') == 'sale'
                 else f"ودیعه: {data.get('max_deposit', 0):,} | اجاره ماهانه: {data.get('max_rent', 0):,}")
    return (f"نیاز شما: {deal} آپارتمان در تهران\nمحدوده: {data.get('district', 'ثبت نشده')}\n"
            f"{financial} تومان\nمتراژ: {data.get('min_area', 0)} تا {data.get('max_area', 0)} متر\n"
            f"حداقل خواب: {data.get('min_rooms', 0)}\nامکانات الزامی: {', '.join(data.get('preferred_features', [])) or 'ندارد'}\n"
            f"زمان اقدام: {data.get('urgency_label', 'مشخص نشده')}\n"
            f"شماره: {'ثبت شده؛ در چت نمایش داده نمی‌شود' if data.get('phone') or data.get('phone_shared') else 'ثبت نشده'}")


def validated_payload(data, user_id, name):
    if not normalize_iran_phone(data.get('phone')) or not data.get('contact_shared_at'):
        raise ValueError('شماره خودتان را با دکمه رسمی تلگرام ثبت کنید.')
    if data.get('deal_type') not in ('sale', 'rent') or not data.get('district'):
        raise ValueError('فرم ناقص است.')
    if not (20 <= data.get('min_area', 0) <= data.get('max_area', 0) <= 2000):
        raise ValueError('بازه متراژ معتبر نیست.')
    if data.get('deal_type') == 'sale' and data.get('max_budget', 0) <= 0:
        raise ValueError('بودجه خرید باید مثبت باشد.')
    if data.get('deal_type') == 'rent' and not (data.get('max_deposit', 0) or data.get('max_rent', 0)):
        raise ValueError('حداقل یکی از مبالغ ودیعه یا اجاره باید مثبت باشد.')
    payload = {key: data.get(key, 0) for key in ('max_budget', 'max_deposit', 'max_rent', 'min_area', 'max_area', 'min_rooms')}
    payload.update(deal_type=data['deal_type'], preferred_districts=data.get('districts') or [data['district']],
                   preferred_features=list(data.get('preferred_features', [])), urgency=data.get('urgency', 'normal'),
                   full_name=name or 'مشتری سقف', active_messenger='telegram', contact_key=f'telegram:{user_id}',
                   phone=data.get('phone', ''))
    if data['deal_type'] == 'rent' and data.get('max_rent') == 0:
        payload['preferred_features'].append('رهن کامل')
    return payload


def submit_request(message, data):
    from database.models import CustomerLead
    from services.omnichannel_engine import OmniChannelEngine
    payload = validated_payload(data, message.from_user.id, message.from_user.first_name)
    if payload['phone']:
        existing = CustomerLead.query.filter_by(phone_number=payload['phone']).first()
        if existing and existing.contact_key != payload['contact_key']:
            raise ValueError('contact_identity_conflict')
    # Keep a platform identity for delivery even when a phone is shared.
    result = OmniChannelEngine.ingest_interaction('telegram', str(message.from_user.id), text=summary(data),
        metadata={'source_external_id': str(message.from_user.id), 'defer_matching': True}, structured_lead_payload=payload)
    if result.get('success'):
        from telegram_bot.customer_panel import route_client
        lead = CustomerLead.query.filter_by(contact_key=payload['contact_key']).first()
        if lead and lead.crm_client:
            route_client(lead.crm_client)
            from telegram_bot.workflow import open_case
            case = open_case(lead)
            from database.db import db
            db.session.commit()
            result.setdefault('details', {})['search_case_id'] = case.id
    if result.get('success') and not result.get('details', {}).get('matched_dispatches'):
        from telegram_bot.extraction_jobs import ExtractionJobs
        try:
            queue = ExtractionJobs()
            result['details']['extraction_job_id'] = queue.enqueue(result['details']['lead_id'], message.from_user.id, payload,
                request_key=str(message.message_id))
            result['details']['extraction_job_status'] = queue.status(result['details']['extraction_job_id'])
        except Exception as exc:
            result['details']['extraction_queue_error'] = type(exc).__name__
    return result


class CustomerFlow:
    def __init__(self, bot, app_provider, store=None):
        self.bot, self.app_provider = bot, app_provider
        self.store = store or FormStore()

    def enabled(self, message):
        text = message.text or ''
        if text.startswith('/start '):
            return False  # Preserve property-code and web-login deep links.
        return (message.chat.type == 'private'
                and (message.content_type == 'contact' or not text.startswith('/') or text.split()[0] in ('/start', '/help', '/cancel', '/customer', '/menu')))

    def show(self, message, state, error=None):
        step, data = state['step'], state['data']
        if step != 'max_deposit':
            for key in ('budget_message_id', 'budget_token', 'budget_revision'):
                state.pop(key, None)
        if step != 'features':
            for key in ('feature_message_id', 'feature_token', 'feature_revision'):
                state.pop(key, None)
        if step == 'max_deposit':
            from telegram_bot.budget_picker import render
            return render(self, message.chat.id, state, error)
        if step == 'features':
            from telegram_bot.feature_picker import render
            return render(self, message.chat.id, state, error)
        for key in ('feature_message_id', 'feature_token', 'feature_revision'):
            state.pop(key, None)
        for key in ('budget_message_id', 'budget_token', 'budget_revision'):
            state.pop(key, None)
        if step == 'district':
            from telegram_bot.district_picker import render
            return render(self, message.chat.id, state, error)
        if step == 'menu':
            from telegram_bot.customer_panel import customer_home
            with self.app_provider().app_context():
                dashboard = customer_home(message.from_user.id)
            prompt = f"سلام {message.from_user.first_name or 'همراه عزیز'}، به پنل مشتری سقف خوش آمدید.\n{dashboard}\n\nتطبیق هوشمند: فایل‌های مناسب و درخواست بازدید\nجست‌وجوی ملک: ثبت یا ویرایش بودجه، محله و امکانات\nپیگیری و بازدید: وضعیت درخواست و زمان‌های پیشنهادی\nفایل یا اعلان خودکار ارسال نمی‌شود."
            options = MAIN
        elif step == 'search_menu':
            prompt = 'می‌خواهید فرم قبلی را ادامه دهید یا برای نیاز جدید جست‌وجو کنید؟ درخواست ثبت‌شده بدون تأیید نهایی تغییر نمی‌کند.'
            options = (['ادامه فرم'] if state.get('resume_step') else []) + ['شروع درخواست جدید', PROFILE, CANCEL]
        elif step == 'new_request_confirm':
            prompt = 'پاسخ‌های پیش‌نویس قبلی جایگزین شوند؟ شماره ثبت‌شده حفظ می‌شود؛ پرونده CRM فقط بعد از تأیید نهایی فرم جدید به‌روزرسانی می‌شود.'
            options = ['تأیید درخواست جدید', BACK, CANCEL]
        elif step == 'need_menu':
            from telegram_bot.customer_panel import registered_data
            with self.app_provider().app_context():
                registered = registered_data(message.from_user.id)
            prompt = 'شرایط ثبت‌شده در CRM:\n' + summary(registered) if registered else 'نیاز ثبت‌شده‌ای ندارید؛ پاسخ‌های فرم هنوز نهایی نشده‌اند.'
            if state.get('draft_dirty'):
                prompt += '\nتغییرات فرم هنوز ثبت نشده‌اند.'
            from telegram_bot.customer_panel import own_lead
            from telegram_bot.workflow import search_enabled
            with self.app_provider().app_context():
                lead = own_lead(message.from_user.id)
                enabled = bool(lead and search_enabled(lead))
            options = ([EDIT, 'توقف جست‌وجو' if enabled else 'فعال‌کردن جست‌وجو'] if registered else [FIND]) + [CANCEL]
        elif step == 'edit_menu':
            prompt, options = 'کدام بخش را تغییر می‌دهید؟ سایر پاسخ‌ها حفظ می‌شوند.', ['نوع معامله', 'بودجه', 'محله', 'متراژ', 'تعداد خواب', 'امکانات', 'زمان اقدام', CANCEL]
        elif step == 'resume':
            prompt, options = 'فرم نیمه‌تمام شما محفوظ است.', ['ادامه فرم', 'شروع درخواست جدید', CANCEL]
        elif step == 'suggestions':
            prompt, options = 'پیشنهادها با شرایط ثبت‌شده بررسی می‌شوند؛ آرشیو، نتیجه زنده معرفی نمی‌شود.', ['فایل‌های منطبق', SAVED, CANCEL]
        elif step == 'support':
            prompt, options = 'برای بررسی نیاز یا هماهنگی ملک، درخواست تماس ثبت کنید. زمان تماس بعد از رسیدگی کارشناس مشخص می‌شود.', ['درخواست تماس', 'راهنمای بازدید', 'چرا پیشنهادی ندارم؟', 'حریم خصوصی و اعلان‌ها', TRACKING, BACK, CANCEL]
        elif step == 'stop_confirm':
            prompt, options = 'جست‌وجو و کارهای استخراج در صف متوقف شوند؟ اطلاعات پرونده حذف نمی‌شود.', ['تأیید توقف', BACK, CANCEL]
        elif step == 'contact':
            prompt = 'برای تکمیل درخواست و هماهنگی کارشناس در پاسخ به درخواست شما، شماره خودتان را با دکمه رسمی تلگرام ثبت کنید. شماره در پرونده مشتری ذخیره می‌شود و در گروه یا کانال منتشر نمی‌شود. ارسال فایل فقط در پاسخ به درخواست شماست؛ اعلان روزانهٔ موارد جدید را هم می‌توانید قطع کنید.'
            options = [SHARE, BACK, CANCEL]
        elif step == 'review':
            prompt, options = summary(data) + '\nبا تأیید، فایل‌های موجود نمایش داده و جست‌وجوی آنلاین درخواست می‌شود. در صورت موارد جدید، حداکثر یک اعلان روزانه ساعت ۱۰ تهران دریافت می‌کنید؛ امکان قطع اعلان وجود دارد.', [CONFIRM, EDIT, CANCEL]
        else:
            fields = {
                'deal_type': ('نوع معامله را انتخاب کنید.', ['رهن و اجاره', 'خرید و فروش']),
                'district': ('منطقه را انتخاب کنید؛ محله‌های همان منطقه زیر آن نمایش داده می‌شوند.\nچند محله را انتخاب کنید؛ انتخاب دوباره یعنی حذف.\nانتخاب فعلی: ' + ('، '.join(data.get('districts') or []) or 'ندارد'), district_options(state.get('district_region'), data.get('districts') or [])),
                'max_budget': ('حداکثر بودجه خرید؟ عدد دلخواه را به میلیون تومان بنویسید.', ['۵ میلیارد تومان', '۱۰ میلیارد تومان', '۱۵ میلیارد تومان']),
                'max_deposit': ('حداکثر ودیعه؟ عدد دلخواه را به میلیون تومان بنویسید.', ['۵۰۰ میلیون تومان', '۱ میلیارد تومان', '۱٫۵ میلیارد تومان']),
                'max_rent': ('حداکثر اجاره ماهانه؟ عدد دلخواه را به میلیون تومان بنویسید.', ['رهن کامل؛ بدون اجاره', '۱۵ میلیون تومان', '۳۰ میلیون تومان', '۵۰ میلیون تومان']),
                'area': ('متراژ و حداقل تعداد خواب را با هم انتخاب کنید.\nبرای مقدار دلخواه بنویسید: 70-90 / 2 (۷۰ تا ۹۰ متر، دوخواب).', list(AREA_PRESETS)),
                'min_rooms': ('حداقل چند اتاق خواب؟', ['فرقی ندارد', 'یک‌خواب', 'دوخواب', 'سه‌خواب و بیشتر']),
                'features': ('امکانات الزامی را انتخاب کنید؛ انتخاب دوباره یعنی حذف. سپس «ادامه» را بزنید.\nانتخاب فعلی: ' + (', '.join(data.get('preferred_features', [])) or 'ندارد'), [*FEATURES, 'ادامه']),
                'urgency': ('چه زمانی قصد اقدام یا جابه‌جایی دارید؟', ['فوری', 'تا یک ماه', 'فعلاً بررسی می‌کنم']),
            }
            prompt, options = fields[step]
            if step == 'max_deposit':
                deposit = next((label for label, value in DEPOSIT_AMOUNTS.items() if value == data.get('max_deposit')),
                    f"{data['max_deposit']:,} تومان" if 'max_deposit' in data else 'انتخاب نشده')
                rent = next((label for label, value in RENT_AMOUNTS.items() if value == data.get('max_rent')),
                    f"{data['max_rent']:,} تومان" if 'max_rent' in data else 'انتخاب نشده')
                prompt = f'سقف بودجه خود را مشخص کنید.\nرهن: {deposit}\nاجاره ماهانه: {rent}\nروی سقف رهن یا سقف اجاره بزنید تا مبلغ‌های همان بخش باز شود. عدد دلخواه هم به میلیون تومان پذیرفته می‌شود؛ سپس تأیید بودجه را بزنید.'
                active = state.get('budget_field')
                options = [DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE, BACK, CANCEL,
                    *(list(DEPOSIT_AMOUNTS) if active == 'max_deposit' else list(RENT_AMOUNTS) if active == 'max_rent' else [])]
            if step == 'features':
                prompt += '\nبرای پایان این صفحه، زمان اقدام را هم انتخاب کنید.'
                options = [*FEATURES, 'فوری', 'تا یک ماه', 'فعلاً بررسی می‌کنم', 'ادامه']
            sequence = steps(data)
            prompt = f"گام {sequence.index(step) + 1} از {len(sequence) - 1}\n" + prompt
            if step != 'max_deposit':
                options = options + ([CANCEL] if step == 'deal_type' else [BACK, CANCEL])
        if error:
            prompt = error + '\n\n' + prompt
        self.bot.send_message(message.chat.id, prompt, reply_markup=keyboard(options, step == 'contact'))

    def handle(self, message):
        if not message.from_user or message.from_user.is_bot or message.chat.id != message.from_user.id:
            return
        state = self.store.get(message.from_user.id)
        data, text = state['data'], (message.text or '').strip()
        text = {'ثبت نیاز و تطبیق ملک': FIND, 'پیدا کردن ملک': FIND, 'خلاصه نیاز من': PROFILE,
                'شرایط ملک من': PROFILE, 'پیشنهادهای من': SUGGESTIONS, 'پیشنهادهای مناسب من': SUGGESTIONS,
                'بازدید و پیگیری': TRACKING, 'ارتباط با سقف': SUPPORT}.get(text, text)
        if text in MAIN and state['step'] in steps(data) and data.get('deal_type'):
            state['resume_step'] = state['step']
        if message.content_type == 'contact':
            phone = normalize_iran_phone(message.contact.phone_number)
            if message.contact.user_id != message.from_user.id or not phone:
                return self.show(message, state, 'فقط شماره خودتان را با دکمه رسمی تلگرام ارسال کنید؛ شماره شخص دیگر پذیرفته نیست.')
            data.update(phone=phone, contact_shared_at=time.time())
            if state['step'] == 'contact':
                state['step'] = 'review' if data.get('urgency') else 'deal_type'
            self.store.save(message.from_user.id, state)
            return self.show(message, state)
        if text in ('/start', '/customer', 'پنل مشتری'):
            from telegram_bot.operations import restore_menu_button
            restore_menu_button(self.bot, message.chat.id)
            if state['step'] in steps(data) and data:
                state['resume_step'] = state['step']
            state['step'] = 'menu'
        elif text in ('/help', '/cancel', '/menu', CANCEL):
            from telegram_bot.operations import restore_menu_button
            restore_menu_button(self.bot, message.chat.id)
            if state['step'] in steps(data) and data:
                state['resume_step'] = state['step']
            state['step'] = 'menu'
        elif text == 'ادامه فرم' and state['step'] in ('resume', 'search_menu'):
            state['step'] = state.pop('resume_step', 'deal_type')
        elif text == FIND:
            # Explicit search is always fresh; only the customer's own contact survives.
            data = {key: data[key] for key in ('phone', 'contact_shared_at') if key in data}
            state = {'step': 'deal_type', 'data': data, 'draft_dirty': True}
        elif text == 'شروع درخواست جدید':
            if state['step'] in steps(data) and data:
                state['resume_step'] = state['step']
            state['step'] = 'new_request_confirm'
        elif text == 'تأیید درخواست جدید' and state['step'] == 'new_request_confirm':
            state.pop('edit_field', None)
            state.pop('resume_step', None)
            state.pop('district_region', None)
            state.pop('budget_field', None)
            state['data'] = data = {key: data[key] for key in ('phone', 'contact_shared_at') if key in data}
            state['draft_dirty'] = True
            state['step'] = 'deal_type'
        elif text == EDIT:
            from telegram_bot.customer_panel import registered_data
            with self.app_provider().app_context():
                registered = registered_data(message.from_user.id)
            if registered and not state.get('draft_dirty'):
                data.update(registered)
            state['step'] = 'edit_menu' if data.get('deal_type') else 'deal_type'
        elif state['step'] == 'edit_menu' and text in ('نوع معامله', 'بودجه', 'محله', 'متراژ', 'تعداد خواب', 'امکانات', 'زمان اقدام'):
            field = {'نوع معامله': 'deal_type', 'بودجه': 'max_budget' if data.get('deal_type') == 'sale' else 'max_deposit',
                     'محله': 'district', 'متراژ': 'area', 'تعداد خواب': 'min_rooms', 'امکانات': 'features', 'زمان اقدام': 'urgency'}[text]
            state['step'], state['edit_field'], state['draft_dirty'] = field, field, True
        elif text == PROFILE:
            state['step'] = 'need_menu'
        elif text in (SUGGESTIONS, 'فایل‌های منطبق', SAVED):
            state['step'] = 'menu'
            self.store.save(message.from_user.id, state)
            from telegram_bot.customer_panel import show_recommendations
            self.bot.send_message(message.chat.id, 'ملک‌های نشان‌شده شما' if text == SAVED else 'پیشنهادهای متناسب با شرایط ثبت‌شده شما', reply_markup=keyboard(MAIN))
            with self.app_provider().app_context():
                show_recommendations(self.bot, message.from_user.id, text == SAVED)
            return
        elif text == TRACKING:
            state['step'] = 'menu'
            self.store.save(message.from_user.id, state)
            from telegram_bot.customer_panel import tracking_text
            with self.app_provider().app_context():
                tracking = tracking_text(message.from_user.id)
            self.bot.send_message(message.chat.id, tracking, reply_markup=keyboard(MAIN))
            from telegram_bot.customer_panel import show_visit_actions
            with self.app_provider().app_context(): show_visit_actions(self.bot, message.from_user.id)
            return
        elif text == SUPPORT:
            state['step'] = 'support'
        elif text == 'درخواست تماس':
            state['step'] = 'menu'
            self.store.save(message.from_user.id, state)
            from telegram_bot.customer_panel import request_followup
            with self.app_provider().app_context():
                try:
                    row, created = request_followup(message.from_user.id)
                    reply = f"درخواست تماس {row.id} {'ثبت شد' if created else 'قبلاً ثبت شده'}؛ زمان تماس هنوز قطعی نیست."
                    if not row.agent_id:
                        reply += '\nمنتظر تخصیص مسئول پشتیبانی است.'
                except ValueError as exc:
                    reply = str(exc)
            return self.bot.send_message(message.chat.id, reply, reply_markup=keyboard(MAIN))
        elif text == 'توقف جست‌وجو':
            state['step'] = 'stop_confirm'
        elif (text == 'تأیید توقف' and state['step'] == 'stop_confirm') or text == 'فعال‌کردن جست‌وجو':
            from telegram_bot.customer_panel import own_lead
            from database.db import db
            with self.app_provider().app_context():
                lead = own_lead(message.from_user.id)
                if lead and lead.crm_client:
                    from telegram_bot.workflow import set_search_active
                    try:
                        set_search_active(lead, text != 'تأیید توقف')
                    except ValueError as exc:
                        return self.bot.send_message(message.chat.id, str(exc), reply_markup=keyboard(MAIN))
            state['step'] = 'menu'
        elif text == 'راهنما':
            state['step'] = 'menu'
            self.store.save(message.from_user.id, state)
            return self.bot.send_message(message.chat.id, f'از «{FIND}» شروع کنید. شماره خودتان فقط برای ثبت نهایی و ارتباط تیم دریافت می‌شود. داخل «{FIND}» می‌توانید شرایط و بودجه را اصلاح کنید. پیشنهاد آرشیوی به معنی استخراج زنده یا اثبات مالکیت نیست.', reply_markup=keyboard(MAIN))
        elif text in ('راهنمای بازدید', 'چرا پیشنهادی ندارم؟', 'حریم خصوصی و اعلان‌ها'):
            reply = ('روی «درخواست بازدید» زیر پیشنهاد مناسب بزنید. کارشناس زمان پیشنهاد می‌دهد؛ بازدید فقط پس از تأیید شما ثبت می‌شود. زمان‌ها و نتیجه را در «پیگیری و بازدید» ببینید.' if text == 'راهنمای بازدید' else
                     'فایل‌ها فقط در پاسخ به درخواست شما نمایش داده می‌شوند. پس از تأیید جست‌وجو، نتیجه همان درخواست و در صورت موارد جدید حداکثر یک اعلان متنی روزانه دریافت می‌کنید؛ اعلان را می‌توانید قطع کنید. پیام آزمایشی ارسال نمی‌شود. شماره خودتان برای ثبت نیاز و هماهنگی در CRM نگه‌داری می‌شود و در گروه یا کانال منتشر نمی‌شود.' if text == 'حریم خصوصی و اعلان‌ها' else
                     'ممکن است فایل معتبر منطبق موجود نباشد، جست‌وجو متوقف باشد یا استخراج هنوز تکمیل نشده باشد. «پیگیری و بازدید» را بررسی کنید؛ برای اصلاح بودجه یا محدوده، دکمه «اصلاح نیاز من» داخل تطبیق هوشمند را بزنید. نبود پیشنهاد اثبات نبود ملک در بازار نیست.')
            state['step'] = 'support'
            self.store.save(message.from_user.id, state)
            return self.show(message, state, reply)
        elif text == BACK and state.get('edit_field') and state['step'] in steps(data):
            state.pop('edit_field', None)
            state['step'] = 'edit_menu'
        elif text == BACK and state['step'] == 'new_request_confirm':
            state['step'] = 'search_menu'
        elif text == BACK and state['step'] in ('stop_confirm', 'edit_menu', 'suggestions', 'support', 'need_menu', 'resume', 'search_menu'):
            state['step'] = 'menu'
        elif text == BACK and state['step'] == 'features' and data.get('deal_type') == 'rent':
            state['step'] = 'max_deposit'
            state.pop('budget_field', None)
        elif text == BACK and state['step'] == 'max_deposit':
            if state.pop('budget_field', None):
                state['step'] = 'max_deposit'
            else:
                state['step'] = 'district'
                state.pop('district_region', None)
        elif text == BACK and state['step'] == 'district':
            if state.pop('district_region', None):
                state['district_page'] = 0
            else:
                state['step'] = 'area'
        elif state['step'] == 'contact':
            if text == BACK:
                state['step'] = 'urgency'
            else:
                return self.show(message, state, 'برای ثبت نهایی، دکمه اشتراک‌گذاری شماره خودتان را بزنید؛ می‌توانید درخواست را لغو کنید.')
        elif text == BACK and state['step'] in steps(data):
            sequence = steps(data)
            state['step'] = sequence[max(0, sequence.index(state['step']) - 1)]
        elif state['step'] == 'max_deposit' and (
                text in (DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE) or state.get('budget_field')):
            if text in (DEPOSIT_TITLE, RENT_TITLE):
                state['budget_field'] = 'max_deposit' if text == DEPOSIT_TITLE else 'max_rent'
            elif text == BUDGET_DONE:
                if 'max_deposit' not in data or 'max_rent' not in data:
                    return self.show(message, state, 'هر دو سقف رهن و اجاره را انتخاب کنید؛ برای رهن کامل، اجاره صفر را بزنید.')
                if not (data['max_deposit'] or data['max_rent']):
                    return self.show(message, state, 'حداقل یکی از مبالغ رهن یا اجاره باید مثبت باشد.')
                data['full_mortgage'] = data['max_rent'] == 0
                state.pop('budget_field', None)
                state['step'] = 'review' if state.pop('edit_field', None) else 'features'
            else:
                field = state['budget_field']
                amounts = DEPOSIT_AMOUNTS if field == 'max_deposit' else RENT_AMOUNTS
                try:
                    value = amounts[text] if text in amounts else money(text)
                except ValueError as exc:
                    return self.show(message, state, str(exc))
                data[field] = value
            self.store.save(message.from_user.id, state)
            return self.show(message, state)
        elif state['step'] == 'review' and text == CONFIRM:
            if not normalize_iran_phone(data.get('phone')) or not data.get('contact_shared_at'):
                state['step'] = 'contact'
                self.store.save(message.from_user.id, state)
                return self.show(message, state)
            try:
                self.bot.send_message(message.chat.id, 'در حال ثبت نیاز و بررسی فایل‌های موجود…', reply_markup=keyboard(MAIN))
                with self.app_provider().app_context():
                    result = submit_request(message, data)
                    if not result.get('success'):
                        raise RuntimeError('crm_ingestion_failed')
                state['step'] = 'menu'
                state['draft_dirty'] = False
                state.pop('edit_field', None)
                state.pop('resume_step', None)
                self.store.save(message.from_user.id, state)
                count = result.get('details', {}).get('matched_dispatches', 0)
                details = result.get('details', {})
                if details.get('search_case_id'):
                    self.bot.send_message(message.chat.id, f"شناسه درخواست شما: #{details['search_case_id']}")
                status = (f'پیشنهادها فقط در «{SUGGESTIONS}» نمایش داده می‌شوند.' if count else
                          'درخواست استخراج فایل متناسب با نیاز شما در صف قرار گرفت.' if details.get('extraction_job_status') in ('queued', 'running') else
                          f'این درخواست قبلاً بررسی شده؛ وضعیت را در «{TRACKING}» ببینید.' if details.get('extraction_job_id') else
                          'ثبت صف استخراج موفق نشد؛ پرونده CRM محفوظ است.')
                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                progress_markup = InlineKeyboardMarkup()
                progress_markup.row(InlineKeyboardButton('وضعیت جست‌وجوی آنلاین', callback_data='customer:search_status'))
                progress_markup.row(InlineKeyboardButton('قطع اعلان روزانه', callback_data='customer:daily_off'))
                progress = self.bot.send_message(message.chat.id,
                    'درخواست شما در حال بررسی است. فایل‌های موجود و منطبق را همین حالا نمایش می‌دهم.\n'
                    + ('جست‌وجوی آنلاین در صف قرار گرفت؛ نتیجهٔ آن هنوز تأیید نشده است.'
                       if details.get('extraction_job_id') else 'ثبت صف جست‌وجوی آنلاین تأیید نشد؛ موجودی ذخیره‌شده جدا بررسی می‌شود.'),
                    reply_markup=progress_markup)
                from telegram_bot.customer_panel import show_recommendations
                with self.app_provider().app_context():
                    from telegram_bot.customer_panel import own_lead, recommendations
                    from telegram_bot.search_delivery import NotificationStore, fingerprint, item_key
                    from telegram_bot.workflow import lead_criteria
                    lead = own_lead(message.from_user.id)
                    store = NotificationStore()
                    items = recommendations(message.from_user.id)
                    criteria = lead_criteria(lead)
                    store.subscribe(message.from_user.id, lead.id, criteria, items)
                    if details.get('extraction_job_id'):
                        message_id = getattr(progress, 'message_id', None)
                        store.issue(f'search:{details["extraction_job_id"]}:{message.message_id}', message.from_user.id,
                            lead.id, fingerprint(criteria), 'search_result', [item_key(item) for item in items],
                            job_id=details['extraction_job_id'], message_id=message_id if isinstance(message_id, int) else None)
                    show_recommendations(self.bot, message.from_user.id)
                return
            except Exception:
                from database.db import db
                with self.app_provider().app_context():
                    db.session.rollback()
                return self.show(message, state, 'ثبت یا تطبیق کامل نشد. اطلاعات فرم حفظ شد؛ دوباره تأیید کنید.')
        elif state['step'] in steps(data) and state['step'] != 'review':
            field = state['step']
            combined = None
            try:
                if field == 'deal_type':
                    state.pop('budget_field', None)
                    if text not in ('خرید و فروش', 'خرید', 'رهن کامل', 'رهن و اجاره'):
                        raise ValueError('نوع معامله را از گزینه‌ها انتخاب کنید.')
                    selected = 'sale' if text in ('خرید و فروش', 'خرید') else 'rent'
                    if data.get('deal_type') != selected:
                        for key in ('max_budget', 'max_deposit', 'max_rent'):
                            data.pop(key, None)
                    data['deal_type'] = selected
                    data['full_mortgage'] = text == 'رهن کامل'
                    if data['full_mortgage']:
                        data['max_rent'] = 0
                elif field == 'district':
                    from telegram_bot.district_picker import handle_text
                    if handle_text(self, message, state, text):
                        return
                    if text in REGION_LABELS:
                        state['district_region'] = REGION_LABELS[text]
                        from data.tehran_districts import get_district_names
                        allowed = get_district_names(state['district_region'])
                        selected = [name for name in data.get('districts', []) if name in allowed]
                        data['districts'], data['district'] = selected, '، '.join(selected)
                        self.store.save(message.from_user.id, state)
                        return self.show(message, state)
                    if text == CHANGE_REGION:
                        state.pop('district_region', None)
                        self.store.save(message.from_user.id, state)
                        return self.show(message, state)
                    if state.get('district_region'):
                        from data.tehran_districts import get_district_names
                        name = text.removeprefix('انتخاب‌شده: ')
                        selected = list(data.get('districts') or [])
                        if name in get_district_names(state['district_region']):
                            selected.remove(name) if name in selected else selected.append(name)
                            data['districts'] = selected
                            data['district'] = '، '.join(selected)
                            self.store.save(message.from_user.id, state)
                            return self.show(message, state)
                        if text != DISTRICT_DONE:
                            raise ValueError('محله را از فهرست منطقه انتخاب کنید؛ برای منطقه دیگر دکمه همان منطقه را بزنید.')
                        if not selected:
                            raise ValueError('حداقل یک محله انتخاب کنید.')
                    elif text == DISTRICT_DONE:
                        raise ValueError('ابتدا منطقه و حداقل یک محله را انتخاب کنید.')
                    else:
                        from telegram_bot.district_picker import names
                        if text not in [name for region in REGION_LABELS.values() for name in names(region)]:
                            raise ValueError('ابتدا منطقه را از منوی پایین انتخاب کنید.')
                        data['district'] = text
                        data.pop('districts', None)
                elif field in ('max_budget', 'max_deposit', 'max_rent'):
                    amounts = {'۵ میلیارد تومان': '5000', '۱۰ میلیارد تومان': '10000', '۱۵ میلیارد تومان': '15000',
                        '۵۰۰ میلیون تومان': '500', '۱ میلیارد تومان': '1000', '۱٫۵ میلیارد تومان': '1500',
                        'رهن کامل؛ بدون اجاره': '0', '۱۵ میلیون تومان': '15', '۳۰ میلیون تومان': '30', '۵۰ میلیون تومان': '50'}
                    if field == 'max_deposit' and '/' in text and not data.get('full_mortgage'):
                        parts = text.split('/')
                        if len(parts) != 2:
                            raise ValueError('ودیعه و اجاره را مثل 500 / 15 به میلیون تومان وارد کنید.')
                        deposit, rent = (money(part.strip()) for part in parts)
                        data.update(max_deposit=deposit, max_rent=rent)
                        combined = 'features'
                    else:
                        data[field] = money(amounts.get(text, text))
                    if field == 'max_budget' and not data[field]:
                        raise ValueError('بودجه خرید باید مثبت باشد.')
                elif field == 'area':
                    text = AREA_PRESETS.get(text, text)
                    parts = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')).split('/')
                    if len(parts) > 2 or (len(parts) == 2 and parts[1].strip() not in tuple(str(x) for x in range(11))):
                        raise ValueError('متراژ و خواب را مثل 70-90 / 2 وارد کنید؛ خواب بین صفر تا ۱۰ است.')
                    bounds = parts[0].split('-')
                    if len(bounds) != 2 or not all(x.strip().isdigit() for x in bounds):
                        raise ValueError('متراژ را به صورت ۷۰-۹۰ وارد کنید.')
                    lower, upper = map(int, bounds)
                    if not 20 <= lower <= upper <= 2000:
                        raise ValueError('بازه متراژ باید بین ۲۰ تا ۲۰۰۰ و مرتب باشد.')
                    data.update(min_area=lower, max_area=upper)
                    if len(parts) == 2:
                        data['min_rooms'] = int(parts[1].strip())
                        combined = 'district'
                elif field == 'min_rooms':
                    value = {'فرقی ندارد': '0', 'یک‌خواب': '1', 'دوخواب': '2', 'سه‌خواب و بیشتر': '3'}.get(text, text).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789'))
                    if value not in tuple(str(x) for x in range(11)):
                        raise ValueError('تعداد خواب را از صفر تا ۱۰ وارد کنید.')
                    data[field] = int(value)
                elif field == 'features':
                    selected = data.setdefault('preferred_features', [])
                    if text in FEATURES:
                        selected.remove(text) if text in selected else selected.append(text)
                        self.store.save(message.from_user.id, state)
                        return self.show(message, state)
                    if text == FEATURE_DONE:
                        data.setdefault('urgency', 'normal')
                        data.setdefault('urgency_label', 'زمان اقدام تعیین نشده')
                        combined = 'review' if data.get('phone') else 'contact'
                    timing = {'فوری': 'immediate', 'تا یک ماه': 'normal', 'فعلاً بررسی می‌کنم': 'looking'}
                    if text in timing:
                        data.update(urgency=timing[text], urgency_label=text)
                        combined = 'review' if data.get('phone') else 'contact'
                    elif text not in ('ادامه', FEATURE_DONE):
                        raise ValueError('امکانات را انتخاب کنید یا ادامه را بزنید.')
                elif field == 'urgency':
                    options = {'فوری': 'immediate', 'تا یک ماه': 'normal', 'فعلاً بررسی می‌کنم': 'looking'}
                    if text not in options:
                        raise ValueError('زمان اقدام را از گزینه‌ها انتخاب کنید.')
                    data.update(urgency=options[text], urgency_label=text)
                sequence = steps(data)
                state['step'] = sequence[sequence.index(field) + 1]
                if combined:
                    state['step'] = combined
                if state['step'] == 'max_rent' and data.get('full_mortgage'):
                    state['step'] = 'features'
                if state.get('edit_field'):
                    if field == 'deal_type':
                        state['edit_field'] = 'max_budget' if data['deal_type'] == 'sale' else 'max_deposit'
                        state['step'] = state['edit_field']
                    elif field == 'max_deposit' and not data.get('full_mortgage') and not combined:
                        state['step'] = 'max_rent'
                        state['edit_field'] = 'max_rent'
                    else:
                        state.pop('edit_field', None)
                        state['step'] = 'review'
            except ValueError as exc:
                return self.show(message, state, str(exc))
        self.store.save(message.from_user.id, state)
        self.show(message, state)


def register_customer_flow(bot, app_provider):
    flow = CustomerFlow(bot, app_provider)
    bot.saghf_customer_flow = flow
    from telegram_bot.district_picker import register
    register(flow)
    from telegram_bot.budget_picker import register as register_budget
    register_budget(flow)
    from telegram_bot.feature_picker import register as register_features
    register_features(flow)
    def safe_handle(message):
        started=time.monotonic()
        try:
            return flow.handle(message)
        except Exception:
            from database.db import db
            import logging
            with app_provider().app_context():
                db.session.rollback()
                from telegram_bot.telemetry import record_event
                record_event('customer_error')
            logging.getLogger(__name__).warning('Customer panel operation failed', exc_info=False)
            bot.send_message(message.chat.id, 'عملیات کامل نشد؛ پاسخ‌های قبلی محفوظ‌اند. دوباره تلاش کنید یا /start را بزنید.')
        finally:
            if time.monotonic()-started>3:
                with app_provider().app_context():
                    from telegram_bot.telemetry import record_event
                    record_event('slow_customer')
    bot.register_message_handler(safe_handle, func=flow.enabled, content_types=['text', 'contact'])
    return flow
