"""Budget and amenities callbacks: no live Telegram sends."""
from types import SimpleNamespace as N
from unittest.mock import MagicMock
import pytest
from tests.test_telegram_customer_flow import app
from telegram_bot.customer_flow import CustomerFlow, FormStore, FEATURES
from telegram_bot import budget_picker as budget, feature_picker as feature


@pytest.fixture
def flow(app,tmp_path):
    bot = MagicMock()
    bot.send_message.return_value = N(message_id=101)
    flow = CustomerFlow(bot,lambda:app,FormStore(tmp_path/'inline.sqlite3'))
    flow.store.save(777,{'step':'max_deposit','data':{'deal_type':'rent','district':'پونک'}})
    budget.render(flow,777,flow.store.get(777))
    return flow


def buttons(flow):
    method = flow.bot.edit_message_text if flow.bot.edit_message_text.called else flow.bot.send_message
    return [b for row in method.call_args.kwargs['reply_markup'].to_dict()['inline_keyboard'] for b in row]


def click(flow,picker,label,actor=777,payload=None):
    item = next((b for b in buttons(flow) if b['text'].removeprefix('✓ ')==label),None)
    data = payload or item['callback_data']
    picker.callback(flow,N(id='q',from_user=N(id=actor,is_bot=False,first_name='test'),
        message=N(message_id=101,chat=N(id=777,type='private')),data=data))
    return data


def test_budget_single_selection_green_and_no_extra_messages(flow):
    sends = flow.bot.send_message.call_count
    click(flow,budget,'سقف رهن')
    click(flow,budget,'۱ میلیارد تومان')
    assert next(b for b in buttons(flow) if b['text']=='✓ ۱ میلیارد تومان')['style']=='success'
    old = click(flow,budget,'۲ میلیارد تومان')
    assert not any(b['text']=='✓ ۱ میلیارد تومان' for b in buttons(flow))
    click(flow,budget,'۱ میلیارد تومان',payload=old)  # replay rejected
    assert flow.store.get(777)['data']['max_deposit']==2000000000
    click(flow,budget,'سقف اجاره')
    assert '۱۵۰ میلیون تومان' in [b['text'] for b in buttons(flow)]
    assert '۱۰ میلیون تومان' in [b['text'] for b in buttons(flow)]
    click(flow,budget,'۱۵۰ میلیون تومان')
    assert next(b for b in buttons(flow) if b['text']=='✓ ۱۵۰ میلیون تومان')['style']=='success'
    assert flow.bot.send_message.call_count==sends
    click(flow,budget,'تأیید بودجه')
    assert flow.store.get(777)['step']=='features'
    assert 'budget_message_id' not in flow.store.get(777)
    assert 'feature_message_id' in flow.store.get(777)


def test_budget_empty_foreign_network_and_back_are_safe(flow):
    before = flow.store.get(777)
    click(flow,budget,'تأیید بودجه')
    assert flow.store.get(777)==before
    click(flow,budget,'سقف رهن',actor=888)
    assert flow.store.get(777)==before
    click(flow,budget,'سقف رهن')
    before = flow.store.get(777)
    payload = next(b['callback_data'] for b in buttons(flow) if b['text']=='۱ میلیارد تومان')
    flow.bot.edit_message_text.side_effect = ConnectionError('offline')
    click(flow,budget,'۱ میلیارد تومان',payload=payload)
    assert flow.store.get(777)==before
    flow.bot.edit_message_text.side_effect = None
    click(flow,budget,'۱ میلیارد تومان',payload=payload)
    click(flow,budget,'برگشت')
    assert flow.store.get(777)['step']=='max_deposit'
    assert 'budget_field' not in flow.store.get(777)
    click(flow,budget,'برگشت')
    assert flow.store.get(777)['step']=='district'


def open_features(flow):
    flow.store.save(777,{'step':'features','data':{'deal_type':'rent','district':'پونک'}})
    flow.bot.edit_message_text.reset_mock()
    feature.render(flow,777,flow.store.get(777))


def test_features_only_amenities_toggle_counter_no_chat_spam(flow):
    open_features(flow)
    labels = [b['text'] for b in buttons(flow)]
    assert all(name in labels for name in FEATURES)
    assert all(name not in labels for name in ['فوری','تا یک ماه','فعلاً بررسی می‌کنم','ادامه','برگشت'])
    sends = flow.bot.send_message.call_count
    old = click(flow,feature,'بالکن')
    assert next(b for b in buttons(flow) if b['text']=='✓ بالکن')['style']=='success'
    click(flow,feature,'بالکن',payload=old)
    assert flow.store.get(777)['data']['preferred_features']==['بالکن']
    click(flow,feature,'پارکینگ')
    assert 'تأیید امکانات: ۲' in [b['text'] for b in buttons(flow)]
    click(flow,feature,'بالکن')
    assert next(b for b in buttons(flow) if b['text']=='× بالکن')['style']=='danger'
    assert flow.bot.send_message.call_count==sends
    click(flow,feature,'تأیید امکانات: ۱')
    assert flow.store.get(777)['step']=='contact'
    assert flow.store.get(777)['data']['urgency']=='normal'
    assert flow.bot.send_message.call_count==sends+1


def test_features_no_selection_allowed_and_failure_rolls_back(flow):
    open_features(flow)
    before = flow.store.get(777)
    click(flow,feature,'بالکن',actor=888)
    assert flow.store.get(777)==before
    flow.bot.edit_message_text.side_effect = ConnectionError('offline')
    click(flow,feature,'بالکن')
    assert flow.store.get(777)==before
    flow.bot.edit_message_text.side_effect = None
    click(flow,feature,'تأیید امکانات: ۰')
    assert flow.store.get(777)['step']=='contact'


@pytest.mark.parametrize('required,item,expected',[
    (['بالکن'],{'has_balcony':True},True),
    (['بالکن'],{'has_balcony':None},False),
    (['بالکن'],{'features':['تراس']},True),
    (['لابی‌من'],{'features':['لابی من']},True),
    (['استخر'],{'description':'بدون استخر'},False),
    (['استخر','سونا'],{'features':['استخر']},False),
    (['روف‌گاردن'],{'features':['روف گاردن']},True),
])
def test_extra_amenities_need_explicit_evidence(required,item,expected):
    from telegram_bot.amenities import extra_features_match
    assert extra_features_match(item,required) is expected

