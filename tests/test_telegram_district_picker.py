"""Reply-keyboard interaction tests. No real Telegram traffic."""
from types import SimpleNamespace as N
from unittest.mock import MagicMock
import pytest
from tests.test_telegram_customer_flow import app, message
from telegram_bot.customer_flow import CustomerFlow, FormStore, FIND, BACK, CANCEL, DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE
from telegram_bot import district_picker as picker


@pytest.fixture
def flow(app, tmp_path):
    bot = MagicMock()
    bot.send_message.return_value = N(message_id=100)
    flow = CustomerFlow(bot, lambda: app, FormStore(tmp_path / 'picker.sqlite3'))
    for text in ['/start', FIND, 'رهن و اجاره', '۷۰ تا ۹۰ متر، دوخواب']:
        flow.handle(message(text))
    return flow


def buttons(flow):
    method = flow.bot.edit_message_text if flow.store.get(777)['step'] in ('district','max_deposit') and flow.bot.edit_message_text.called else flow.bot.send_message
    markup = method.call_args.kwargs['reply_markup']
    rows = markup.to_dict()['inline_keyboard'] if hasattr(markup,'to_dict') else markup.keyboard
    return [b for row in rows for b in row]


def test_area_replaces_bottom_menu_with_exact_region_choices(flow):
    assert flow.store.get(777)['step'] == 'district'
    assert [b['text'] for b in buttons(flow)] == ['منطقه ۱','منطقه ۲','منطقه ۵','تأیید مناطق: ۰',BACK,CANCEL]
    flow.handle(message('۷۰ تا ۹۰ متر، دوخواب'))  # delayed/repeated area input
    assert flow.store.get(777)['step'] == 'district'
    assert 'سقف رهن' not in [b['text'] for b in buttons(flow)]


def test_colors_pagination_multi_region_and_confirmation(flow):
    flow.handle(message('منطقه ۱'))
    assert all(label in [b['text'] for b in buttons(flow)] for label in picker.REGIONS)
    assert len([b for b in buttons(flow) if b['text'].lstrip('✓× ') in picker.names('1')]) <= picker.PAGE_SIZE
    name = next(b['text'] for b in buttons(flow) if b['text'] in picker.names('1'))
    flow.handle(message(name))
    assert next(b for b in buttons(flow) if b['text'] == '✓ '+name)['style'] == 'success'
    flow.handle(message('✓ '+name))
    assert next(b for b in buttons(flow) if b['text'] == '× '+name)['style'] == 'danger'
    flow.handle(message('× '+name))
    flow.handle(message(picker.NEXT))
    assert flow.store.get(777)['district_page'] == 1
    flow.handle(message('منطقه ۵'))
    flow.handle(message('پونک'))
    flow.handle(message(picker.DONE))
    assert flow.store.get(777)['data']['districts'] == [name,'پونک']
    assert flow.store.get(777)['step'] == 'max_deposit'
    assert flow.bot.edit_message_text.called


def test_budget_headers_remain_visible_ten_billion_and_back_chain(flow):
    for value in ['منطقه ۵','پونک',picker.DONE,DEPOSIT_TITLE]:
        flow.handle(message(value))
    assert [b['text'] for b in buttons(flow)][:2] == [DEPOSIT_TITLE,RENT_TITLE]
    assert '۱۰ میلیارد تومان' in [b['text'] for b in buttons(flow)]
    flow.handle(message('۱۰ میلیارد تومان'))
    flow.handle(message(RENT_TITLE))
    assert '۸۰ میلیون تومان' in [b['text'] for b in buttons(flow)]
    assert [b['text'] for b in buttons(flow)][:2] == [DEPOSIT_TITLE,RENT_TITLE]
    flow.handle(message('۸۰ میلیون تومان'))
    flow.handle(message(BUDGET_DONE))
    assert flow.store.get(777)['step'] == 'features'
    flow.handle(message(BACK))
    assert flow.store.get(777)['step'] == 'max_deposit'
    flow.handle(message(DEPOSIT_TITLE))
    flow.handle(message(BACK))  # subsection -> budget overview
    assert flow.store.get(777)['step'] == 'max_deposit'
    assert 'budget_field' not in flow.store.get(777)
    flow.handle(message(BACK))  # overview -> region choices
    assert flow.store.get(777)['step'] == 'district'
    assert 'district_region' not in flow.store.get(777)
    flow.handle(message('منطقه ۵'))
    flow.handle(message(BACK))
    assert 'district_region' not in flow.store.get(777)
    flow.handle(message(BACK))
    assert flow.store.get(777)['step'] == 'area'


def test_retired_callbacks_never_change_form(flow):
    before = flow.store.get(777)
    picker.callback(flow,N(id='old'))
    assert flow.store.get(777) == before
    flow.bot.edit_message_text.assert_not_called()


def click(flow, label, actor=777, payload=None):
    item = next((b for b in buttons(flow) if b['text'].lstrip('✓× ') == label), None)
    data = payload or item['callback_data']
    picker.callback(flow,N(id='test',from_user=N(id=actor,is_bot=False,first_name='test'),
        message=N(message_id=100,chat=N(id=777,type='private')),data=data))
    return data


def test_callbacks_only_edit_until_confirm_and_reject_replay(flow):
    sends = flow.bot.send_message.call_count
    click(flow,'منطقه ۵')
    old = click(flow,'پونک')
    assert next(b for b in buttons(flow) if b['text']=='✓ پونک')['style']=='success'
    assert 'تأیید مناطق: ۱' in [b['text'] for b in buttons(flow)]
    click(flow,'پونک',payload=old)
    assert flow.store.get(777)['data']['districts']==['پونک']
    click(flow,'منطقه ۲')
    click(flow,'مرزداران',actor=888)
    assert flow.store.get(777)['data']['districts']==['پونک']
    click(flow,'مرزداران')
    assert 'تأیید مناطق: ۲' in [b['text'] for b in buttons(flow)]
    assert flow.bot.send_message.call_count == sends
    click(flow,'تأیید مناطق: ۲')
    assert flow.store.get(777)['step']=='max_deposit'
    assert flow.bot.send_message.call_count == sends+2
    assert 'پونک، مرزداران' in flow.bot.edit_message_text.call_args.args[0]
    assert 'district_message_id' not in flow.store.get(777)


def test_callback_network_failure_keeps_previous_choices(flow):
    click(flow,'منطقه ۵')
    before = flow.store.get(777)
    flow.bot.edit_message_text.side_effect = ConnectionError('offline')
    click(flow,'پونک')
    assert flow.store.get(777)==before
    flow.bot.edit_message_text.side_effect = None
    click(flow,'پونک')
    assert flow.store.get(777)['data']['districts']==['پونک']


def test_real_dispatcher_replaces_keyboard_through_budget_and_back(app, tmp_path):
    from unittest.mock import patch
    from telebot import apihelper
    from telebot.types import Message
    from telegram_bot.outbound_policy import ReplyOnlyTeleBot
    bot = ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')
    flow = CustomerFlow(bot, lambda: app, FormStore(tmp_path / 'dispatcher.sqlite3'))
    bot.register_message_handler(flow.handle, func=flow.enabled, content_types=['text'])
    response = {'message_id':100,'date':1,'chat':{'id':777,'type':'private'}}
    with patch.object(apihelper, '_make_request', return_value=response) as network:
        for index, text in enumerate([FIND,'رهن و اجاره','۷۰ تا ۹۰ متر، دوخواب','منطقه ۵',
                'پونک',picker.DONE,DEPOSIT_TITLE,'۱۰ میلیارد تومان',RENT_TITLE,
                '۳۰ میلیون تومان',BUDGET_DONE,BACK,BACK]):
            update = Message.de_json({'message_id':index+1,'date':1,
                'from':{'id':777,'is_bot':False,'first_name':'test'},
                'chat':{'id':777,'type':'private'},'text':text})
            bot.process_new_messages([update])
        assert flow.store.get(777)['step'] == 'district'
        assert flow.store.get(777)['data']['max_deposit'] == 10000000000
        assert network.call_count >= 13
        assert all(call.args[1] in ('sendMessage','editMessageText') for call in network.call_args_list)


@pytest.mark.parametrize('step', ['area','district','max_deposit','review','menu'])
def test_find_always_resets_filters_but_not_own_contact(flow, step):
    flow.store.save(777, {'step':step,'data':{'phone':'09120000000','contact_shared_at':1,
        'districts':['پونک'],'district':'پونک','max_rent':30000000,'deal_type':'rent'},
        'resume_step':'district','district_region':'5','budget_field':'max_rent','edit_field':'district'})
    flow.handle(message(FIND))
    assert flow.store.get(777) == {'step':'deal_type','data':{'phone':'09120000000','contact_shared_at':1},'draft_dirty':True}
