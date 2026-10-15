"""Private single-choice rent/deposit selection in one editable message."""
import copy
import secrets
from types import SimpleNamespace
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

PREFIX = 'budget:'


def amount_label(amounts, value):
    return next((label for label, amount in amounts.items() if amount == value),
        f'{value:,} تومان' if value is not None else 'انتخاب نشده')


def summary(data):
    from telegram_bot.customer_flow import DEPOSIT_AMOUNTS, RENT_AMOUNTS
    return ('سقف رهن: '+amount_label(DEPOSIT_AMOUNTS,data.get('max_deposit'))+
        '\nسقف اجاره ماهانه: '+amount_label(RENT_AMOUNTS,data.get('max_rent')))


def render(flow, chat_id, state, error=None):
    from telegram_bot.customer_flow import DEPOSIT_TITLE, RENT_TITLE, DEPOSIT_AMOUNTS, RENT_AMOUNTS, BUDGET_DONE, BACK, CANCEL
    token = state.setdefault('budget_token',secrets.token_hex(5))
    revision = state.setdefault('budget_revision',0)
    data, active = state['data'],state.get('budget_field')
    def button(label, action, style=None):
        return InlineKeyboardButton(label,callback_data=f'{PREFIX}{token}:{revision}:{action}',style=style)
    markup = InlineKeyboardMarkup(row_width=2)
    markup.row(button(DEPOSIT_TITLE,'field:deposit','primary' if active=='max_deposit' else None),
        button(RENT_TITLE,'field:rent','primary' if active=='max_rent' else None))
    if active:
        amounts = DEPOSIT_AMOUNTS if active=='max_deposit' else RENT_AMOUNTS
        items = list(amounts.items())
        for index in range(0,len(items),2):
            markup.row(*(button(('✓ ' if data.get(active)==value else '')+label,'amount:'+str(i),
                'success' if data.get(active)==value else None)
                for i,(label,value) in enumerate(items[index:index+2],index)))
    completed = sum(key in data for key in ('max_deposit','max_rent'))
    markup.row(button(BUDGET_DONE,'done','success' if completed==2 else None))
    markup.row(button(BACK,'back'),button(CANCEL,'home'))
    prompt = 'انتخاب سقف بودجه\n'+summary(data)+'\n\nابتدا رهن یا اجاره را انتخاب کنید. هر بخش یک مبلغ دارد؛ مبلغ سبز ✓ انتخاب فعلی است.\nعدد دلخواه را به میلیون تومان هم می‌توانید بنویسید.'
    if error:
        prompt = error+'\n\n'+prompt
    message_id = state.get('budget_message_id')
    if isinstance(message_id,int):
        flow.bot.edit_message_text(prompt,chat_id=chat_id,message_id=message_id,reply_markup=markup)
    else:
        flow.bot.send_message(chat_id,'سقف رهن و اجاره را در پیام زیر انتخاب و سپس تأیید کنید.',reply_markup=ReplyKeyboardRemove())
        sent = flow.bot.send_message(chat_id,prompt,reply_markup=markup)
        if isinstance(getattr(sent,'message_id',None),int):
            state['budget_message_id'] = sent.message_id
    flow.store.save(chat_id,state)


def callback(flow, call):
    from telegram_bot.customer_flow import DEPOSIT_TITLE, RENT_TITLE, DEPOSIT_AMOUNTS, RENT_AMOUNTS, BUDGET_DONE, BACK, CANCEL
    actor,message = getattr(call,'from_user',None),getattr(call,'message',None)
    if not actor or actor.is_bot or not message or message.chat.type!='private' or message.chat.id!=actor.id:
        return flow.bot.answer_callback_query(call.id,'دسترسی مجاز نیست.')
    state = flow.store.get(actor.id)
    parts = (getattr(call,'data','') or '').split(':')
    if (len(parts)<4 or state['step']!='max_deposit' or parts[1]!=state.get('budget_token')
        or parts[2]!=str(state.get('budget_revision')) or message.message_id!=state.get('budget_message_id')):
        return flow.bot.answer_callback_query(call.id,'این دکمه قدیمی است؛ از فهرست جاری استفاده کنید.')
    before = copy.deepcopy(state)
    action,text = parts[3],None
    if action=='field' and len(parts)==5:
        text = {'deposit':DEPOSIT_TITLE,'rent':RENT_TITLE}.get(parts[4])
    elif action=='amount' and len(parts)==5 and parts[4].isdigit() and state.get('budget_field'):
        amounts = DEPOSIT_AMOUNTS if state['budget_field']=='max_deposit' else RENT_AMOUNTS
        index = int(parts[4])
        if index<len(amounts):
            text = list(amounts)[index]
    elif action in ('done','back','home') and len(parts)==4:
        text = {'done':BUDGET_DONE,'back':BACK,'home':CANCEL}[action]
    if text is None:
        return flow.bot.answer_callback_query(call.id,'گزینه معتبر نیست.')
    data = state['data']
    if action=='done' and ('max_deposit' not in data or 'max_rent' not in data):
        return flow.bot.answer_callback_query(call.id,'هر دو سقف رهن و اجاره را انتخاب کنید.')
    if action=='done' and not (data['max_deposit'] or data['max_rent']):
        return flow.bot.answer_callback_query(call.id,'حداقل یکی از مبالغ باید مثبت باشد.')
    flow.bot.answer_callback_query(call.id)
    state['budget_revision'] += 1
    closes = action in ('done','home') or (action=='back' and (not state.get('budget_field') or state.get('edit_field')))
    try:
        if closes:
            body = 'بودجه انتخاب‌شده\n'+summary(data) if action=='done' else 'انتخاب بودجه بسته شد.'
            flow.bot.edit_message_text(body,chat_id=actor.id,message_id=message.message_id,reply_markup=None)
            for key in ('budget_message_id','budget_token','budget_revision'):
                state.pop(key,None)
        flow.store.save(actor.id,state)
        flow.handle(SimpleNamespace(chat=message.chat,from_user=actor,text=text,content_type='text'))
    except Exception:
        flow.store.save(actor.id,before)
        try:
            render(flow,actor.id,before,'به‌روزرسانی کامل نشد؛ پاسخ‌های قبلی محفوظ‌اند. دوباره تلاش کنید.')
        except Exception:
            pass


def register(flow):
    flow.bot.register_callback_query_handler(lambda call: callback(flow,call),
        func=lambda call: bool(call.data and call.data.startswith(PREFIX)))

