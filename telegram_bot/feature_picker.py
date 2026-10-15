"""Multi-select building amenities, one revision-bound editable Telegram message."""
import copy
import secrets
from types import SimpleNamespace
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove

PREFIX = 'feature:'


def render(flow, chat_id, state, error=None):
    from telegram_bot.customer_flow import FEATURES, FEATURE_DONE, CANCEL
    token = state.setdefault('feature_token',secrets.token_hex(5))
    revision = state.setdefault('feature_revision',0)
    selected = state['data'].get('preferred_features') or []
    removed = state.get('feature_removed') or []
    def button(label, action, style=None):
        return InlineKeyboardButton(label,callback_data=f'{PREFIX}{token}:{revision}:{action}',style=style)
    markup = InlineKeyboardMarkup(row_width=2)
    for index in range(0,len(FEATURES),2):
        markup.row(*(button(('✓ ' if name in selected else '× ' if name in removed else '')+name,
            'pick:'+str(i),'success' if name in selected else 'danger' if name in removed else None)
            for i,name in enumerate(FEATURES[index:index+2],index)))
    count = str(len(selected)).translate(str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹'))
    markup.row(button(FEATURE_DONE+': '+count,'done','primary'))
    markup.row(button(CANCEL,'home'))
    prompt = 'امکانات الزامی ملک\nموارد موردنیاز را انتخاب کنید؛ لمس دوباره یعنی حذف.\nسبز ✓ انتخاب؛ قرمز × حذف انتخاب.\nاگر امکانات خاصی لازم ندارید، بدون انتخاب تأیید کنید.'
    if error:
        prompt = error+'\n\n'+prompt
    message_id = state.get('feature_message_id')
    if isinstance(message_id,int):
        flow.bot.edit_message_text(prompt,chat_id=chat_id,message_id=message_id,reply_markup=markup)
    else:
        flow.bot.send_message(chat_id,'امکانات موردنیاز را در پیام زیر انتخاب کنید.',reply_markup=ReplyKeyboardRemove())
        sent = flow.bot.send_message(chat_id,prompt,reply_markup=markup)
        if isinstance(getattr(sent,'message_id',None),int):
            state['feature_message_id'] = sent.message_id
    flow.store.save(chat_id,state)


def callback(flow, call):
    from telegram_bot.customer_flow import FEATURES, FEATURE_DONE, CANCEL
    actor,message = getattr(call,'from_user',None),getattr(call,'message',None)
    if not actor or actor.is_bot or not message or message.chat.type!='private' or message.chat.id!=actor.id:
        return flow.bot.answer_callback_query(call.id,'دسترسی مجاز نیست.')
    state = flow.store.get(actor.id)
    parts = (getattr(call,'data','') or '').split(':')
    if (len(parts)<4 or state['step']!='features' or parts[1]!=state.get('feature_token')
        or parts[2]!=str(state.get('feature_revision')) or message.message_id!=state.get('feature_message_id')):
        return flow.bot.answer_callback_query(call.id,'این دکمه قدیمی است؛ از فهرست جاری استفاده کنید.')
    before = copy.deepcopy(state)
    action,text = parts[3],None
    if action=='pick' and len(parts)==5 and parts[4].isdigit() and int(parts[4])<len(FEATURES):
        text = FEATURES[int(parts[4])]
    elif action in ('done','home') and len(parts)==4:
        text = FEATURE_DONE if action=='done' else CANCEL
    if text is None:
        return flow.bot.answer_callback_query(call.id,'گزینه معتبر نیست.')
    flow.bot.answer_callback_query(call.id)
    state['feature_revision'] += 1
    try:
        if action=='pick':
            selected = state['data'].get('preferred_features') or []
            removed = list(state.get('feature_removed') or [])
            if text in selected and text not in removed:
                removed.append(text)
            elif text in removed:
                removed.remove(text)
            state['feature_removed'] = removed
        else:
            selected = state['data'].get('preferred_features') or []
            body = 'امکانات انتخاب‌شده: '+('، '.join(selected) or 'بدون الزام امکانات') if action=='done' else 'انتخاب امکانات بسته شد.'
            flow.bot.edit_message_text(body,chat_id=actor.id,message_id=message.message_id,reply_markup=None)
            for key in ('feature_message_id','feature_token','feature_revision'):
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

