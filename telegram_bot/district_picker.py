"""Private, revision-bound district selection; one editable Telegram message."""

PREFIX = 'district:'
REGIONS = {'منطقه ۱': '1', 'منطقه ۲': '2', 'منطقه ۵': '5'}
DONE = 'تأیید مناطق'


def names(region):
    from data.tehran_districts import get_district_names, REGION_2_DISTRICT_NAMES, REGION_5_DISTRICT_NAMES
    extra = {
        '1': ['اقدسیه', 'امامزاده قاسم', 'اوین', 'باغ فردوس', 'اراج', 'حصار بوعلی',
              'دربند', 'درکه', 'دزاشیب', 'گلابدره', 'شهرک دانشگاه', 'شهرک نفت',
              'شهرک محلاتی', 'فرشته', 'بلوار ارتش', 'اندرزگو', 'جمشیدیه',
              'صاحبقرانیه', 'مینی‌سیتی', 'نوبنیاد', 'دیباجی شمالی', 'سعدآباد'],
        '2': [*REGION_2_DISTRICT_NAMES, 'برق آلستوم', 'تهران ویلا'],
        '5': [*REGION_5_DISTRICT_NAMES, 'اشرفی اصفهانی', 'شهرک اندیشه', 'شهرک والفجر'],
    }
    if region not in REGIONS.values():
        return []
    result, seen = [], set()
    for name in [*get_district_names(region), *extra[region]]:
        key = name.replace('\u200c', '').replace(' ', '').replace('ي', 'ی').replace('ك', 'ک')
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


PAGE_SIZE = 6
NEXT = 'محله‌های بعدی'
PREVIOUS = 'محله‌های قبلی'


def render(flow, chat_id, state, error=None):
    import secrets
    from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup, ReplyKeyboardRemove
    token = state.setdefault('district_token', secrets.token_hex(5))
    revision = state.setdefault('district_revision', 0)
    def button(label, action, style=None):
        return B(label, callback_data=f'{PREFIX}{token}:{revision}:{action}', style=style)
    markup = InlineKeyboardMarkup(row_width=2)
    region = state.get('district_region')
    selected, removed = state['data'].get('districts') or [], state.get('district_removed') or []
    markup.row(*(button(label, 'region:'+key, 'primary' if key == region else None) for label,key in REGIONS.items()))
    prompt = 'انتخاب محدوده ملک\nمنطقه را انتخاب کنید؛ انتخاب‌های مناطق دیگر محفوظ می‌مانند.'
    if region:
        choices = names(region)
        last = max(0, (len(choices)-1)//PAGE_SIZE)
        page = min(last,max(0,state.get('district_page',0)))
        state['district_page'] = page
        for index in range(page*PAGE_SIZE, min(len(choices),(page+1)*PAGE_SIZE),2):
            markup.row(*(button(('✓ ' if name in selected else '× ' if name in removed else '')+name,
                'pick:'+str(i), 'success' if name in selected else 'danger' if name in removed else None)
                for i,name in enumerate(choices[index:index+2],index)))
        nav = ([button(PREVIOUS,'prev')] if page else []) + ([button(NEXT,'next')] if page<last else [])
        if nav:
            markup.row(*nav)
        title = next(label for label,key in REGIONS.items() if key==region)
        prompt = f'{title} | صفحه {page+1} از {last+1}\nمحله‌ها را انتخاب کنید؛ لمس دوباره یعنی حذف.\nسبز ✓ انتخاب؛ قرمز × حذف انتخاب.'
    count = str(len(selected)).translate(str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹'))
    markup.row(button(f'{DONE}: {count}','done','success'))
    markup.row(button('برگشت','back'),button('منوی اصلی','home'))
    if error:
        prompt = error+'\n\n'+prompt
    message_id = state.get('district_message_id')
    if isinstance(message_id,int):
        flow.bot.edit_message_text(prompt,chat_id=chat_id,message_id=message_id,reply_markup=markup)
    else:
        flow.bot.send_message(chat_id,'انتخاب منطقه و محله در پیام زیر؛ پس از پایان «تأیید مناطق» را بزنید.',reply_markup=ReplyKeyboardRemove())
        sent = flow.bot.send_message(chat_id,prompt,reply_markup=markup)
        if isinstance(getattr(sent,'message_id',None),int):
            state['district_message_id'] = sent.message_id
    flow.store.save(chat_id,state)

def handle_text(flow, message, state, text):
    from telegram_bot.customer_flow import CHANGE_REGION, DISTRICT_DONE
    data, region = state['data'], state.get('district_region')
    name = text.removeprefix('✓ ').removeprefix('× ').removeprefix('انتخاب‌شده: ')
    if text in REGIONS:
        state['district_region'], state['district_page'] = REGIONS[text], 0
    elif text in (CHANGE_REGION, 'بازگشت به مناطق'):
        state.pop('district_region', None)
        state['district_page'] = 0
    elif text in (NEXT, PREVIOUS) and region:
        last = max(0, (len(names(region))-1)//PAGE_SIZE)
        state['district_page'] = min(last, max(0, state.get('district_page',0)+(1 if text == NEXT else -1)))
    elif text in (DONE, DISTRICT_DONE):
        if not data.get('districts'):
            render(flow, message.chat.id, state, 'حداقل یک محله انتخاب کنید.')
            return True
        state['step'] = 'review' if state.pop('edit_field',None) else ('max_budget' if data['deal_type']=='sale' else 'max_deposit')
        state.pop('budget_field',None)
        flow.store.save(message.from_user.id,state)
        flow.show(message,state)
        return True
    elif region and name in names(region):
        selected, removed = list(data.get('districts') or []), list(state.get('district_removed') or [])
        if name in selected:
            selected.remove(name)
            if name not in removed:
                removed.append(name)
        else:
            selected.append(name)
            if name in removed:
                removed.remove(name)
        data['districts'], data['district'] = selected, '، '.join(selected)
        state['district_removed'] = removed
    else:
        return False
    render(flow,message.chat.id,state)
    return True


def callback(flow, call):
    import copy
    from types import SimpleNamespace
    actor, message = getattr(call,'from_user',None),getattr(call,'message',None)
    if not actor or actor.is_bot or not message or message.chat.type!='private' or message.chat.id!=actor.id:
        return flow.bot.answer_callback_query(call.id,'دسترسی مجاز نیست.')
    state = flow.store.get(actor.id)
    parts = (getattr(call,'data','') or '').split(':')
    if (len(parts)<4 or state['step']!='district' or parts[1]!=state.get('district_token')
        or parts[2]!=str(state.get('district_revision')) or message.message_id!=state.get('district_message_id')):
        return flow.bot.answer_callback_query(call.id,'این دکمه قدیمی است؛ از فهرست جاری استفاده کنید.')
    before = copy.deepcopy(state)
    action = parts[3]
    text = None
    if action=='region' and len(parts)==5:
        text = next((label for label,key in REGIONS.items() if key==parts[4]),None)
    elif action=='pick' and len(parts)==5 and parts[4].isdigit() and state.get('district_region'):
        choices = names(state['district_region'])
        index = int(parts[4])
        page = state.get('district_page',0)
        if page*PAGE_SIZE<=index<min(len(choices),(page+1)*PAGE_SIZE):
            text = choices[index]
    elif action in ('next','prev') and len(parts)==4:
        text = NEXT if action=='next' else PREVIOUS
    elif action in ('done','back','home') and len(parts)==4:
        text = {'done':DONE,'back':'برگشت','home':'منوی اصلی'}[action]
    if text is None:
        return flow.bot.answer_callback_query(call.id,'گزینه معتبر نیست.')
    if action=='done' and not state['data'].get('districts'):
        return flow.bot.answer_callback_query(call.id,'حداقل یک محله انتخاب کنید.')
    # Acknowledge before network edits so the client spinner stops promptly.
    flow.bot.answer_callback_query(call.id)
    request = SimpleNamespace(chat=message.chat,from_user=actor,text=text,content_type='text')
    state['district_revision'] += 1
    try:
        if action in ('done','home') or (action=='back' and not state.get('district_region')):
            summary = ('محله‌های انتخاب‌شده: '+ '، '.join(state['data']['districts'])) if action=='done' else 'انتخاب محدوده بسته شد.'
            flow.bot.edit_message_text(summary,chat_id=actor.id,message_id=message.message_id,reply_markup=None)
            for key in ('district_message_id','district_token','district_revision'):
                state.pop(key,None)
        flow.store.save(actor.id,state)
        flow.handle(request)
    except Exception:
        flow.store.save(actor.id,before)
        try:
            render(flow,actor.id,before,'به‌روزرسانی کامل نشد؛ انتخاب‌های قبلی محفوظ‌اند. دوباره تلاش کنید.')
        except Exception:
            pass


def register(flow):
    flow.bot.register_callback_query_handler(lambda call: callback(flow,call),
        func=lambda call: bool(call.data and call.data.startswith(PREFIX)))
