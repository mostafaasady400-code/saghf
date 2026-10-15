from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch

import pytest
from telebot.types import Message
from database.db import db
from telegram_bot.runtime import create_crm_context
from telegram_bot.customer_flow import CustomerFlow, FormStore, money, FIND, SKIP, CONFIRM, PROFILE, submit_request


@pytest.fixture
def app():
    class Test:
        SQLALCHEMY_DATABASE_URI = 'sqlite://'
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        TESTING = True
    instance = create_crm_context(Test)
    with instance.app_context():
        db.create_all()
        from tempfile import TemporaryDirectory
        from telegram_bot.extraction_jobs import ExtractionJobs
        with TemporaryDirectory() as directory:
            queue = ExtractionJobs(directory + '/jobs.sqlite3')
            with patch('telegram_bot.extraction_jobs.ExtractionJobs', return_value=queue):
                yield instance
        db.session.remove()
        db.drop_all()


def message(text=None, contact=None):
    data = {'message_id': 10, 'date': 1, 'chat': {'id': 777, 'type': 'private'},
            'from': {'id': 777, 'is_bot': False, 'first_name': 'مشتری'}}
    data['text' if contact is None else 'contact'] = text if contact is None else contact
    return Message.de_json(data)


@pytest.fixture
def flow(app, tmp_path):
    return CustomerFlow(MagicMock(), lambda: app, FormStore(tmp_path / 'forms.sqlite3'))


def test_restart_restores_draft_without_cross_customer_state(app, tmp_path):
    path = tmp_path / 'restart-forms.sqlite3'
    first = CustomerFlow(MagicMock(), lambda: app, FormStore(path))
    first.handle(message('/start'))
    first.handle(message(FIND))
    first.handle(message('خرید'))
    saved = first.store.get(777)
    restarted = CustomerFlow(MagicMock(), lambda: app, FormStore(path))
    assert restarted.store.get(777) == saved
    assert restarted.store.get(888) == {'step': 'menu', 'data': {}}
    restarted.handle(message('/start'))
    assert restarted.store.get(777)['step'] == 'menu'
    assert restarted.store.get(777)['data'] == saved['data']


@pytest.mark.parametrize('entry', ['/start', '/customer', 'پنل مشتری'])
def test_landing_deferred_official_contact_and_foreign_rejection(flow, entry):
    flow.handle(message(entry))
    assert flow.store.get(777)['step'] == 'menu'
    keyboard = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert not any(button.get('request_contact') for row in keyboard.keyboard for button in row)
    flow.handle(message(FIND))
    assert flow.store.get(777)['step'] == 'deal_type'
    for value in ['خرید', '70-90', '2', 'پونک', '5000', 'ادامه', 'فوری']:
        flow.handle(message(value))
    keyboard = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert any(button.get('request_contact') for row in keyboard.keyboard for button in row)
    flow.handle(message(contact={'user_id': 888, 'phone_number': '+989120000000', 'first_name': 'Other'}))
    assert 'phone' not in flow.store.get(777)['data']
    flow.handle(message(contact={'user_id': 777, 'phone_number': '+989120000000', 'first_name': 'Customer'}))
    assert flow.store.get(777)['data']['phone'] == '09120000000'
    assert '09120000000' not in flow.bot.send_message.call_args.args[1]
    assert FormStore(flow.store.path).get(777)['step'] == 'review'


def test_contact_without_fsm_is_retained(flow):
    flow.handle(message(contact={'user_id': 777, 'phone_number': '+989120000000', 'first_name': 'Customer'}))
    flow.handle(message(FIND))
    assert flow.store.get(777)['step'] == 'deal_type'


def test_rental_budget_expands_each_field_and_confirms_together(flow):
    from telegram_bot.customer_flow import DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE
    for value in ['/start', FIND, 'رهن و اجاره', '۷۰ تا ۹۰ متر، دوخواب', 'پونک']:
        flow.handle(message(value))
    def labels():
        return [button['text'] for row in flow.bot.send_message.call_args.kwargs['reply_markup'].to_dict()['inline_keyboard'] for button in row]
    assert labels()[:3] == [DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE]
    assert not any('/' in label for label in labels())
    flow.handle(message(DEPOSIT_TITLE))
    assert labels()[:2] == [DEPOSIT_TITLE, RENT_TITLE]
    assert BUDGET_DONE in labels() and 'برگشت' in labels()
    assert '۵۰۰ میلیون تومان' in labels() and '۱۰ میلیارد تومان' in labels()
    flow.handle(message('۲ میلیارد تومان'))
    assert flow.store.get(777)['step'] == 'max_deposit'
    flow.handle(message(BUDGET_DONE))
    assert flow.store.get(777)['step'] == 'max_deposit'
    flow.handle(message(RENT_TITLE))
    assert '۴۵ میلیون تومان' in labels() and '۸۰ میلیون تومان' in labels()
    assert '۲ میلیارد تومان' not in labels()
    flow.handle(message('۴۵ میلیون تومان'))
    flow.handle(message(BUDGET_DONE))
    state = flow.store.get(777)
    assert state['step'] == 'features'
    assert state['data']['max_deposit'] == 2000000000
    assert state['data']['max_rent'] == 45000000
    flow.handle(message('برگشت'))
    assert flow.store.get(777)['step'] == 'max_deposit'
    assert '۲ میلیارد تومان' in flow.bot.send_message.call_args.args[1]
    assert '۴۵ میلیون تومان' in flow.bot.send_message.call_args.args[1]


def test_budget_invalid_input_is_preserved_and_full_mortgage_is_explicit(flow):
    from telegram_bot.customer_flow import DEPOSIT_TITLE, RENT_TITLE, BUDGET_DONE
    for value in ['/start', FIND, 'رهن و اجاره', '۷۰ تا ۹۰ متر، دوخواب', 'پونک', DEPOSIT_TITLE, '۵۰۰ میلیون تومان']:
        flow.handle(message(value))
    before = dict(flow.store.get(777)['data'])
    flow.handle(message('NaN'))
    assert flow.store.get(777)['data'] == before
    for value in [RENT_TITLE, 'بدون اجاره؛ رهن کامل', BUDGET_DONE]:
        flow.handle(message(value))
    state = flow.store.get(777)
    assert state['step'] == 'features'
    assert state['data']['max_rent'] == 0 and state['data']['full_mortgage'] is True


def test_region_lists_multi_select_and_switch_without_hidden_filters(flow):
    from telegram_bot.customer_flow import DISTRICT_DONE, validated_payload
    for value in ['/start', FIND, 'رهن و اجاره', '۷۰ تا ۹۰ متر، دوخواب', 'منطقه ۵']:
        flow.handle(message(value))
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    labels = [button['text'] for row in markup.to_dict()['inline_keyboard'] for button in row]
    assert 'جنت‌آباد شمالی' in labels and 'جنت‌آباد مرکزی' in labels and 'جنت‌آباد جنوبی' in labels
    assert 'مرزداران' not in labels
    assert 'منطقه ۲' in labels and 'منطقه ۵' in labels
    assert max(len(row) for row in markup.to_dict()['inline_keyboard']) <= 3
    for value in ['جنت‌آباد شمالی', 'پونک', 'باغ‌فیض', 'انتخاب‌شده: باغ‌فیض', 'منطقه ۲']:
        flow.handle(message(value))
    labels = [button['text'] for row in flow.bot.send_message.call_args.kwargs['reply_markup'].to_dict()['inline_keyboard'] for button in row]
    assert 'مرزداران' in labels and 'پونک' not in labels
    flow.handle(message('مرزداران'))
    assert flow.store.get(777)['step'] == 'district'
    flow.handle(message(DISTRICT_DONE))
    state = flow.store.get(777)
    assert state['step'] == 'max_deposit'
    assert state['data']['districts'] == ['جنت‌آباد شمالی', 'پونک', 'مرزداران']
    data = dict(state['data'], max_deposit=500000000, max_rent=15000000,
                phone='09120000000', contact_shared_at=1)
    assert validated_payload(data, 777, 'test')['preferred_districts'] == data['districts']


def test_empty_district_selection_cannot_advance_and_restart_preserves_choices(flow, app):
    from telegram_bot.customer_flow import DISTRICT_DONE
    for value in ['/start', FIND, 'خرید و فروش', '۷۰ تا ۹۰ متر، دوخواب', 'منطقه ۵', DISTRICT_DONE]:
        flow.handle(message(value))
    assert flow.store.get(777)['step'] == 'district'
    assert 'حداقل یک محله' in flow.bot.send_message.call_args.args[1]
    flow.handle(message('پونک'))
    restarted = CustomerFlow(MagicMock(), lambda: app, FormStore(flow.store.path))
    restarted.handle(message('/start'))
    assert restarted.store.get(777)['data']['districts'] == ['پونک']
    restarted.handle(message(FIND))
    state = restarted.store.get(777)
    assert state['step'] == 'deal_type' and state['data'] == {}
    assert 'district_region' not in state


def test_deal_menu_has_exactly_two_types_and_home(flow):
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert [button['text'] for row in markup.keyboard for button in row] == [
        'رهن و اجاره', 'خرید و فروش', 'منوی اصلی']
    flow.handle(message('خرید و فروش'))
    assert flow.store.get(777)['data']['deal_type'] == 'sale'
    assert flow.store.get(777)['step'] == 'area'


@pytest.mark.parametrize('label,lower,upper,rooms', [
    ('۵۰ تا ۷۰ متر، یک‌خواب',50,70,1),
    ('۷۰ تا ۹۰ متر، دوخواب',70,90,2),
    ('۹۰ تا ۱۲۰ متر، دوخواب',90,120,2),
    ('۱۲۰ تا ۱۶۰ متر، سه‌خواب',120,160,3),
])
def test_readable_area_buttons_store_both_filters(flow, label, lower, upper, rooms):
    for value in ['/start', FIND, 'خرید و فروش']:
        flow.handle(message(value))
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert label in [button['text'] for row in markup.keyboard for button in row]
    flow.handle(message(label))
    state = flow.store.get(777)
    assert state['step'] == 'district'
    assert (state['data']['min_area'],state['data']['max_area'],state['data']['min_rooms']) == (lower,upper,rooms)


@pytest.mark.parametrize('text', ['-1', 'NaN', 'Infinity', '999999999999', 'ده میلیون', '1e999999'])
def test_invalid_amount(text):
    with pytest.raises(ValueError):
        money(text)


def test_persian_amount():
    assert money('۱۵٫۵') == 15500000


def test_full_rent_form_to_real_crm(flow, app):
    from database.models import CustomerLead, Client
    with patch('services.omnichannel_engine.SemanticLLMRouter.classify_and_extract') as llm, patch('services.omnichannel_engine.nurturing_engine.handle_lead_matching_and_dispatch', return_value=[]), patch('services.omnichannel_engine.send_green_lead_alert', return_value=False), patch('services.omnichannel_engine.send_bale_green_lead_alert', return_value=False):
        for value in ['/start', FIND, 'رهن و اجاره', '70-90', '2', 'پونک', '500', '۱۵٫۵', 'پارکینگ', 'آسانسور', 'ادامه', 'فوری']:
            flow.handle(message(value))
        flow.handle(message(contact={'user_id': 777, 'phone_number': '+989120000000', 'first_name': 'Customer'}))
        assert flow.store.get(777)['step'] == 'review'
        assert CustomerLead.query.count() == 0
        flow.handle(message(CONFIRM))
        llm.assert_not_called()
        lead, client = CustomerLead.query.one(), Client.query.one()
        assert lead.contact_key == 'telegram:777'
        assert lead.max_deposit == 500000000
        assert lead.max_rent == 15500000
        assert client.max_area == 90 and client.min_rooms == 2
        assert client.urgency == 'immediate'
        assert client.must_have_parking and client.must_have_elevator
        # Contact upgrade updates the existing platform identity, not a second client.
        flow.handle(message(contact={'user_id': 777, 'phone_number': '+989120000000', 'first_name': 'Customer'}))
        data = flow.store.get(777)['data']
        submit_request(message(CONFIRM), data)
        assert CustomerLead.query.count() == Client.query.count() == 1
        assert lead.has_real_phone


def test_back_edit_and_invalid_area(flow):
    for value in [FIND, 'خرید', '90-70']:
        flow.handle(message(value))
    assert flow.store.get(777)['step'] == 'area'
    flow.handle(message('برگشت'))
    assert flow.store.get(777)['step'] == 'deal_type'
    assert flow.store.get(777)['data']['deal_type'] == 'sale'


def test_matching_uses_room_and_area_constraints(app):
    from services.regional_matching import RegionalPropertyMatcher
    client = N(min_rooms=2, max_area=90)
    lead = N(client_id=1, crm_client=client, preferred_features=[])
    candidates = [N(to_dict=lambda: {'rooms': 1, 'area': 80}), N(to_dict=lambda: {'rooms': 2, 'area': 100}), N(to_dict=lambda: {'rooms': 2, 'area': 85})]
    with patch('services.regional_matching.UnifiedMatcher.match', return_value=candidates) as match:
        assert RegionalPropertyMatcher.match_lead(lead) == [{'rooms': 2, 'area': 85}]
        assert match.call_args.args[0] is client


def test_real_dispatcher_selects_customer_flow(flow, app):
    import telegram_bot.bot as module
    with patch.object(module, '_bot_instance', None), patch.object(module, '_flask_app_instance', app), patch.object(module.Config, 'TELEGRAM_BOT_TOKEN', '123456:TEST'), patch('telegram_bot.customer_flow.FormStore', return_value=flow.store):
        bot = module.get_bot()
        with patch.object(bot, 'send_message') as send:
            bot.process_new_messages([message('/start')])
            assert send.call_count == 1
            assert any(button['text'] == FIND for row in send.call_args.kwargs['reply_markup'].keyboard for button in row)
            assert flow.store.get(777)['step'] == 'menu'


def test_failed_submit_keeps_review(flow):
    data = {'deal_type': 'sale', 'district': 'پونک', 'max_budget': 5000000000, 'min_area': 70, 'max_area': 90, 'min_rooms': 2, 'phone': '09120000000', 'contact_shared_at': 1}
    flow.store.save(777, {'step': 'review', 'data': data})
    with patch('telegram_bot.customer_flow.submit_request', side_effect=RuntimeError('network')):
        flow.handle(message(CONFIRM))
    assert flow.store.get(777)['step'] == 'review'


def test_matcher_uses_actual_linked_client_and_strict_budget(app):
    from services.crm_dual_store import DualCRMStore
    from services.regional_matching import RegionalPropertyMatcher
    lead, client = DualCRMStore.store_customer_lead({'contact_key': 'telegram:777', 'deal_type': 'rent',
        'min_area': 70, 'max_area': 90, 'min_rooms': 2, 'max_deposit': 500000000, 'max_rent': 15000000,
        'preferred_features': ['پارکینگ']}, channel='telegram')
    good = {'rooms': 2, 'area': 85, 'deposit': 500000000, 'monthly_rent': 15000000, 'has_parking': True}
    expensive = dict(good, deposit=510000000)
    missing = dict(good, has_parking=False)
    candidates = [N(to_dict=lambda: expensive), N(to_dict=lambda: missing), N(to_dict=lambda: good)]
    with patch('services.regional_matching.UnifiedMatcher.match', return_value=candidates):
        assert RegionalPropertyMatcher.match_lead(lead) == [good]


def test_contact_identity_conflict_does_not_merge(app):
    from services.crm_dual_store import DualCRMStore
    from database.models import CustomerLead
    DualCRMStore.store_customer_lead({'contact_key': 'telegram:888', 'phone': '09120000000'}, channel='telegram')
    data = {'deal_type': 'sale', 'district': 'پونک', 'max_budget': 5000000000, 'min_area': 70, 'max_area': 90, 'phone': '09120000000', 'contact_shared_at': 1}
    with pytest.raises(ValueError, match='contact_identity_conflict'):
        submit_request(message(CONFIRM), data)
    assert CustomerLead.query.one().contact_key == 'telegram:888'


def test_form_edits_clear_old_budget_and_full_mortgage_is_strict(app):
    from services.crm_dual_store import DualCRMStore
    from services.regional_matching import RegionalPropertyMatcher
    from telegram_bot.customer_flow import validated_payload
    lead, client = DualCRMStore.store_customer_lead({'contact_key': 'telegram:777', 'max_budget': 5000000000, 'max_rent': 15000000}, channel='telegram')
    data = {'deal_type': 'rent', 'district': 'پونک', 'max_deposit': 500000000, 'max_rent': 0, 'min_area': 70, 'max_area': 90, 'min_rooms': 2, 'phone': '09120000000', 'contact_shared_at': 1}
    lead, client = DualCRMStore.store_customer_lead(validated_payload(data, 777, 'Customer'), channel='telegram')
    assert client.max_budget == client.max_rent == lead.max_budget == lead.max_rent == 0
    good = {'rooms': 2, 'area': 85, 'deposit': 500000000, 'monthly_rent': 0}
    bad = dict(good, monthly_rent=10000000)
    with patch('services.regional_matching.UnifiedMatcher.match', return_value=[N(to_dict=lambda: bad), N(to_dict=lambda: good)]):
        assert RegionalPropertyMatcher.match_lead(lead) == [good]


def test_contact_is_required_last_step_and_keyboard_dismissible(flow):
    for value in ['/start', FIND, 'خرید', '70-90', '2', 'پونک', '5000', 'ادامه', 'فوری']:
        flow.handle(message(value))
    assert flow.store.get(777)['step'] == 'contact'
    assert flow.bot.send_message.call_args.kwargs['reply_markup'].is_persistent is False
    flow.handle(message('برگشت'))
    assert flow.store.get(777)['step'] == 'urgency'
    flow.handle(message('تا یک ماه'))
    flow.handle(message(SKIP))
    assert flow.store.get(777)['step'] == 'contact'
    flow.handle(message(contact={'user_id': 777, 'phone_number': '+989120000000', 'first_name': 'Customer'}))
    assert flow.store.get(777)['step'] == 'review'


def test_menu_recovery_preserves_draft_even_when_telegram_menu_api_fails(flow):
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    flow.handle(message('خرید'))
    before = dict(flow.store.get(777)['data'])
    previous_step = flow.store.get(777)['step']
    flow.bot.set_chat_menu_button.side_effect = RuntimeError('network failure')
    assert flow.enabled(message('/menu'))
    flow.handle(message('/menu'))
    state = flow.store.get(777)
    assert state['step'] == 'menu' and state['data'] == before
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert markup.is_persistent is False and markup.one_time_keyboard is False
    flow.handle(message('/start'))
    assert flow.store.get(777)['step'] == 'menu'
    flow.handle(message(FIND))
    assert flow.store.get(777)['step'] == 'deal_type'
    assert flow.store.get(777)['data'] == {}


def test_new_request_requires_confirmation_and_back_preserves_draft(flow):
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    flow.handle(message('خرید'))
    before = dict(flow.store.get(777)['data'])
    assert flow.store.get(777)['step'] == 'area'
    flow.handle(message('شروع درخواست جدید'))
    assert flow.store.get(777)['step'] == 'new_request_confirm'
    assert flow.store.get(777)['data'] == before
    flow.handle(message('برگشت'))
    flow.handle(message('ادامه فرم'))
    assert flow.store.get(777)['step'] == 'area'
    assert flow.store.get(777)['data'] == before
    flow.handle(message('شروع درخواست جدید'))
    flow.handle(message('تأیید درخواست جدید'))
    assert flow.store.get(777)['data'] == {}
    assert flow.store.get(777)['step'] == 'deal_type'


@pytest.mark.parametrize('saved', [False, True])
def test_recommendations_open_directly_and_preserve_form(flow, saved):
    from telegram_bot.customer_flow import SAVED, SUGGESTIONS, MAIN
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    flow.handle(message('خرید'))
    before = dict(flow.store.get(777)['data'])
    with patch('telegram_bot.customer_panel.show_recommendations') as display:
        flow.handle(message(SAVED if saved else SUGGESTIONS))
    display.assert_called_once_with(flow.bot, 777, saved)
    state = flow.store.get(777)
    assert state['step'] == 'menu' and state['data'] == before
    assert state['resume_step'] == 'area'
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert [button['text'] for row in markup.keyboard for button in row] == MAIN
    assert [len(row) for row in markup.keyboard] == [1, 1, 1, 2]


def test_grouped_rental_filters_finish_in_six_choices(flow):
    for value in ['/start', FIND, 'رهن و اجاره', '70-90 / 2', 'پونک', '500 / 15', 'پارکینگ', 'فوری']:
        flow.handle(message(value))
    state = flow.store.get(777)
    assert state['step'] == 'contact'
    assert state['data']['min_rooms'] == 2
    assert state['data']['min_area'] == 70
    assert state['data']['max_deposit'] == 500000000
    assert state['data']['max_rent'] == 15000000
    assert state['data']['preferred_features'] == ['پارکینگ']
    assert state['data']['urgency'] == 'immediate'


@pytest.mark.parametrize('value', ['70-90 / 11', '90-70 / 2', '70-90 / 2 / 3'])
def test_invalid_grouped_area_does_not_partially_save(flow, value):
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    flow.handle(message('خرید'))
    before = dict(flow.store.get(777)['data'])
    flow.handle(message(value))
    assert flow.store.get(777)['step'] == 'area'
    assert flow.store.get(777)['data'] == before


def test_invalid_grouped_budget_preserves_previous_values(flow):
    for value in ['/start', FIND, 'رهن و اجاره', '70-90 / 2', 'پونک']:
        flow.handle(message(value))
    before = dict(flow.store.get(777)['data'])
    flow.handle(message('500 / NaN'))
    assert flow.store.get(777)['step'] == 'max_deposit'
    assert flow.store.get(777)['data'] == before


@pytest.mark.parametrize('question', ['راهنمای بازدید', 'چرا پیشنهادی ندارم؟'])
def test_support_guidance_keeps_navigation_and_data(flow, question):
    from telegram_bot.customer_flow import SUPPORT
    flow.handle(message('/start'))
    flow.handle(message(FIND))
    flow.handle(message('خرید'))
    before = dict(flow.store.get(777)['data'])
    flow.handle(message(SUPPORT))
    flow.handle(message(question))
    assert flow.store.get(777)['step'] == 'support'
    assert flow.store.get(777)['data'] == before
    assert 'درخواست تماس' in [b['text'] for row in flow.bot.send_message.call_args.kwargs['reply_markup'].keyboard for b in row]


def test_phone_cannot_be_bypassed_via_old_review(flow, app):
    from database.models import CustomerLead
    flow.store.save(777, {'step': 'review', 'data': {'deal_type': 'sale'}})
    flow.handle(message(CONFIRM))
    assert flow.store.get(777)['step'] == 'contact'
    assert CustomerLead.query.count() == 0


def test_telegram_delivery_prefers_user_id_over_shared_phone():
    from services.omnichannel.dispatcher import omnichannel_dispatcher
    lead = N(has_real_phone=True, phone_number='09120000000', contact_key='telegram:777')
    assert omnichannel_dispatcher._resolve_lead_recipient(lead, 'telegram') == '777'
