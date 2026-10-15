"""Customer panel contracts against an isolated, real SQLite CRM (no network)."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import telebot
from telebot.types import CallbackQuery, Message

from database.db import db
from database.models import Agent, CustomerLead, Interaction, Property, User, Visit
from services.crm_dual_store import DualCRMStore
from telegram_bot import customer_panel as panel
from telegram_bot.customer_flow import (
    CANCEL, CONFIRM, EDIT, FIND, MAIN, PROFILE, SUGGESTIONS, SUPPORT, TRACKING, SAVED,
    CustomerFlow, FormStore,
)
from telegram_bot.extraction_jobs import ExtractionJobs, run_job
from telegram_bot.office_access import OfficeMembership
from telegram_bot.runtime import create_crm_context


CUSTOMER = 101
OTHER_CUSTOMER = 102


def message(text, user_id=CUSTOMER, chat_id=None, chat_type='private'):
    return Message.de_json({
        'message_id': 10, 'date': 1,
        'chat': {'id': user_id if chat_id is None else chat_id, 'type': chat_type},
        'from': {'id': user_id, 'is_bot': False, 'first_name': 'آزمون مشتری'},
        'text': text,
    })


def callback(data, user_id=CUSTOMER, chat_id=None, chat_type='private', is_bot=False):
    return CallbackQuery.de_json({
        'id': 'customer-panel-unit-callback', 'chat_instance': 'unit-test', 'data': data,
        'from': {'id': user_id, 'is_bot': is_bot, 'first_name': 'آزمون مشتری'},
        'message': {
            'message_id': 20, 'date': 1,
            'chat': {'id': user_id if chat_id is None else chat_id, 'type': chat_type},
            'text': 'کارت ملک آزمایشی',
        },
    })


@pytest.fixture
def crm_app(tmp_path, monkeypatch):
    class TestConfig:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + (tmp_path / 'panel-crm.sqlite3').as_posix()
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        TESTING = True

    monkeypatch.delenv('TELEGRAM_DEFAULT_AGENT_ID', raising=False)
    app = create_crm_context(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        # This schema belongs solely to tmp_path, never the configured live CRM.
        db.drop_all()


@pytest.fixture
def records(crm_app):
    result = {}
    for index, customer in enumerate((CUSTOMER, OTHER_CUSTOMER), 1):
        staff_id = 900 + index
        agent = Agent(name=f'آزمون مشاور {index}', is_active=True)
        user = User(username=f'panel-test-staff-{index}', password_hash='not-a-live-password',
                    full_name=f'آزمون مشاور {index}', telegram_id=str(staff_id),
                    role='agent', is_active=True)
        db.session.add_all([agent, user])
        db.session.flush()
        db.session.add(OfficeMembership(telegram_id=str(staff_id), user_id=user.id,
            agent_id=agent.id, office_key=f'unit-office-{index}', office_role='agent', active=True))
        db.session.commit()
        lead, client = DualCRMStore.store_customer_lead({
            'contact_key': f'telegram:{customer}', 'phone': f'0912{customer:07d}',
            'full_name': f'آزمون مشتری {index}', 'deal_type': 'sale',
            'preferred_districts': ['پونک'], 'min_area': 70, 'max_area': 90,
            'min_rooms': 2, 'max_budget': 5_000_000_000, 'max_deposit': 0, 'max_rent': 0,
            'preferred_features': ['پارکینگ'], 'urgency': 'immediate',
        }, channel='telegram')
        client.assigned_agent_id = agent.id
        prop = Property(title=f'آپارتمان آزمون دفتر {index}', deal_type='sale', city='تهران',
            district='پونک', property_type='apartment', area=80, rooms=2,
            total_price=4_000_000_000, has_parking=True, has_elevator=False,
            status='available', owner_type='personal', is_personal_owner=True,
            source='direct_owner', source_url=f'https://divar.ir/v/unit-test/property-{index}',
            assigned_agent_id=agent.id)
        db.session.add(prop)
        db.session.commit()
        result[customer] = {'lead': lead, 'client': client, 'property': prop, 'agent': agent}
    return result


def item_for(prop):
    item = prop.to_dict()
    item.update(source_type='property', id=prop.id)
    return item

def test_seen_files_are_excluded_from_new_tab_without_skipping_next_page(callback_bot,records):
    from telegram_bot.search_delivery import NotificationStore
    from telegram_bot.workflow import lead_criteria
    items=[dict(item_for(records[CUSTOMER]['property']),id=index,source_url=f'https://divar.ir/v/test/token{index}') for index in range(1,10)]
    store=NotificationStore()
    store.subscribe(CUSTOMER,records[CUSTOMER]['lead'].id,lead_criteria(records[CUSTOMER]['lead']),[])
    with patch.object(panel,'recommendations',return_value=items),patch.object(panel,'card') as render:
        panel.show_recommendations(callback_bot,CUSTOMER)
        render.reset_mock()
        panel.show_recommendations(callback_bot,CUSTOMER,new_only=True)
        assert [call.args[2]['id'] for call in render.call_args_list]==[5,6,7,8]
        render.reset_mock()
        panel.show_recommendations(callback_bot,CUSTOMER,page=1,new_only=True,refresh=False)
        assert [call.args[2]['id'] for call in render.call_args_list]==[9]

def test_card_amounts_are_readable_and_unknown_is_not_zero():
    assert panel.formatted_amount(1_500_000_000)=='۱.۵ میلیارد'
    assert panel.formatted_amount(15_000_000)=='۱۵ میلیون'
    assert panel.formatted_amount(0)=='۰'
    assert panel.formatted_amount(None)=='نامشخص'
    assert panel.formatted_amount(-1)=='نامشخص'


@pytest.fixture
def computed_matches(records):
    """Only mock candidate computation: ownership, fit and mutations remain real."""
    with patch('services.regional_matching.RegionalPropertyMatcher.match_lead',
               side_effect=lambda *args, **kwargs: [item_for(record['property']) for record in records.values()]), \
         patch('telegram_bot.extraction_jobs.archive_matches', return_value=[]):
        yield records


@pytest.fixture
def flow(crm_app, tmp_path):
    return CustomerFlow(MagicMock(), lambda: crm_app, FormStore(tmp_path / 'panel-forms.sqlite3'))


@pytest.fixture
def callback_bot(crm_app):
    bot = telebot.TeleBot('123:UNIT_TEST_ONLY', threaded=False)
    bot.send_message = MagicMock()
    bot.answer_callback_query = MagicMock()
    panel.register_customer_callbacks(bot, lambda: crm_app)
    return bot


def dispatch(bot, data, **kwargs):
    bot.process_new_callback_query([callback(data, **kwargs)])


def criteria_for(lead):
    client = lead.crm_client
    return dict(deal_type=lead.deal_type, preferred_districts=lead.preferred_districts,
        min_area=lead.min_area, max_area=client.max_area, min_rooms=client.min_rooms,
        max_budget=lead.max_budget, max_deposit=lead.max_deposit, max_rent=lead.max_rent,
        preferred_features=lead.preferred_features)


def test_customer_home_has_five_direct_action_buttons(flow):
    flow.handle(message(CANCEL))
    markup = flow.bot.send_message.call_args.kwargs['reply_markup']
    assert [button['text'] for row in markup.keyboard for button in row] == [
        FIND, SUGGESTIONS, TRACKING, SAVED, SUPPORT]
    assert MAIN == [FIND, SUGGESTIONS, TRACKING, SAVED, SUPPORT]
    assert [len(row) for row in markup.keyboard] == [1, 1, 1, 2]
    assert markup.is_persistent is False
    assert not any(button.get('request_contact') for row in markup.keyboard for button in row)


def test_recommendations_enforce_office_visibility_and_real_lifecycle(computed_matches):
    own = computed_matches[CUSTOMER]['property']
    other = computed_matches[OTHER_CUSTOMER]['property']
    assert [item['id'] for item in panel.recommendations(CUSTOMER)] == [own.id]
    assert [item['id'] for item in panel.recommendations(OTHER_CUSTOMER)] == [other.id]
    own.status = 'archived'
    db.session.commit()
    assert panel.recommendations(CUSTOMER) == []
    assert [item['id'] for item in panel.recommendations(OTHER_CUSTOMER)] == [other.id]


@pytest.mark.parametrize('context', [
    {'chat_id': OTHER_CUSTOMER},
    {'chat_id': -100, 'chat_type': 'group'},
    {'is_bot': True},
])
def test_customer_callback_requires_private_owner(callback_bot, computed_matches, context):
    prop = computed_matches[CUSTOMER]['property']
    dispatch(callback_bot, f'customer:save:property:{prop.id}', **context)
    assert panel.PanelSelection.query.count() == 0
    assert Interaction.query.count() == 2  # Initial CRM ingestion records remain unchanged.
    assert callback_bot.answer_callback_query.call_count == 1


def test_customer_callback_rejects_absent_message(callback_bot, computed_matches):
    call = callback(f"customer:save:property:{computed_matches[CUSTOMER]['property'].id}")
    call.message = None
    callback_bot.process_new_callback_query([call])
    assert panel.PanelSelection.query.count() == 0
    assert Interaction.query.count() == 2


def test_forged_other_office_callback_cannot_save_or_request_visit(callback_bot, computed_matches):
    foreign = computed_matches[OTHER_CUSTOMER]['property']
    for action in ('save', 'visit', 'reject'):
        dispatch(callback_bot, f'customer:{action}:property:{foreign.id}')
    assert panel.PanelSelection.query.count() == 0
    assert Interaction.query.count() == 2
    assert Visit.query.count() == 0
    assert 'قابل اقدام نیست' in callback_bot.answer_callback_query.call_args.args[1]


@pytest.mark.parametrize('data', [
    'customer:save:property:not-an-id', 'customer:delete:property:1',
    'customer:visit:owner:1', 'customer:save:property:1:extra',
])
def test_malformed_customer_callbacks_do_not_mutate(callback_bot, computed_matches, data):
    dispatch(callback_bot, data)
    assert panel.PanelSelection.query.count() == 0
    assert Interaction.query.count() == 2
    assert callback_bot.answer_callback_query.call_count == 1


def test_save_unsave_reject_are_owned_and_durable(callback_bot, computed_matches):
    prop = computed_matches[CUSTOMER]['property']
    data = f'customer:save:property:{prop.id}'
    dispatch(callback_bot, data)
    dispatch(callback_bot, data)
    row = panel.PanelSelection.query.one()
    assert row.telegram_id == str(CUSTOMER) and row.saved and not row.rejected
    assert panel.PanelSelection.query.filter_by(telegram_id=str(OTHER_CUSTOMER)).count() == 0
    dispatch(callback_bot, f'customer:unsave:property:{prop.id}')
    db.session.expire_all()
    assert not row.saved
    dispatch(callback_bot, data)
    dispatch(callback_bot, f'customer:reject:property:{prop.id}')
    db.session.expire_all()
    row = panel.PanelSelection.query.one()
    assert row.rejected and not row.saved
    assert panel.recommendations(CUSTOMER) == []
    assert len(panel.recommendations(OTHER_CUSTOMER)) == 1


def test_visit_callback_deduplicates_pending_request_not_scheduled_visit(callback_bot, computed_matches):
    record = computed_matches[CUSTOMER]
    data = f"customer:visit:property:{record['property'].id}"
    dispatch(callback_bot, data)
    dispatch(callback_bot, data)
    row = Interaction.query.filter_by(type='saghf_visit').one()
    assert Interaction.query.count() == 3
    assert row.client_id == record['client'].id and row.type == 'saghf_visit'
    assert row.property_id == record['property'].id and row.agent_id == record['agent'].id
    assert row.outcome == 'pending'
    assert Visit.query.count() == 0
    assert 'قبلاً ثبت شده' in callback_bot.answer_callback_query.call_args.args[1]
    assert 'بازدید هنوز قطعی نشده' in callback_bot.answer_callback_query.call_args.args[1]


def test_pending_support_request_idempotency_and_customer_isolation(records):
    row, created = panel.request_followup(CUSTOMER)
    replay, replay_created = panel.request_followup(CUSTOMER)
    other, other_created = panel.request_followup(OTHER_CUSTOMER)
    assert created and not replay_created and other_created
    assert row.id == replay.id and other.id != row.id
    assert row.client_id == records[CUSTOMER]['client'].id
    assert other.client_id == records[OTHER_CUSTOMER]['client'].id
    row.outcome = 'completed'
    db.session.commit()
    new, created = panel.request_followup(CUSTOMER)
    assert created and new.id != row.id
    assert Interaction.query.count() == 5


def test_tracking_lists_only_own_followups_and_visits(records):
    own, _ = panel.request_followup(CUSTOMER)
    other, _ = panel.request_followup(OTHER_CUSTOMER)
    visits = []
    for customer in (CUSTOMER, OTHER_CUSTOMER):
        record = records[customer]
        visit = Visit(client_id=record['client'].id, property_id=record['property'].id,
                      scheduled_time=datetime.utcnow() + timedelta(days=1), status='scheduled')
        db.session.add(visit)
        visits.append(visit)
    db.session.commit()
    text = panel.tracking_text(CUSTOMER)
    assert f'درخواست {own.id}:' in text and f'درخواست {other.id}:' not in text
    assert f'بازدید {visits[0].id}:' in text and f'بازدید {visits[1].id}:' not in text
    assert 'برنامه‌ریزی‌شده' in text and 'تهران' in text


def test_profile_reads_registered_crm_not_unconfirmed_draft(flow, records):
    flow.store.save(CUSTOMER, {'step': 'review', 'draft_dirty': True, 'data': {
        'deal_type': 'sale', 'district': 'محله پیش‌نویس تأییدنشده',
        'max_budget': 99_000_000_000, 'min_area': 150, 'max_area': 180,
    }})
    flow.handle(message(PROFILE))
    text = flow.bot.send_message.call_args.args[1]
    assert 'پونک' in text and '5,000,000,000' in text
    assert 'محله پیش‌نویس تأییدنشده' not in text and '99,000,000,000' not in text
    assert 'تغییرات فرم هنوز ثبت نشده' in text
    assert flow.store.get(CUSTOMER)['data']['district'] == 'محله پیش‌نویس تأییدنشده'


def test_registered_customer_start_recovers_dashboard_without_local_draft(flow, records):
    flow.handle(message('/start'))
    assert flow.store.get(CUSTOMER)['step'] == 'menu'
    assert 'جست‌وجوی شما' in flow.bot.send_message.call_args.args[1]


def test_default_routing_assigns_only_unassigned_customer(records):
    own, other = records[CUSTOMER], records[OTHER_CUSTOMER]
    own['client'].assigned_agent_id = None
    db.session.add(panel.PanelSetting(key='default_agent_id', value=str(own['agent'].id)))
    db.session.commit()
    panel.route_client(own['client'])
    panel.route_client(other['client'])
    assert own['client'].assigned_agent_id == own['agent'].id
    assert other['client'].assigned_agent_id == other['agent'].id


def test_default_routing_rejects_revoked_staff(records):
    own = records[CUSTOMER]
    own['client'].assigned_agent_id = None
    own['agent'].is_active = False
    db.session.add(panel.PanelSetting(key='default_agent_id', value=str(own['agent'].id)))
    db.session.commit()
    panel.route_client(own['client'])
    assert own['client'].assigned_agent_id is None


def test_back_from_single_field_edit_preserves_need_and_returns_edit_menu(flow, records):
    flow.handle(message(EDIT))
    before = flow.store.get(CUSTOMER)['data']
    flow.handle(message('بودجه'))
    flow.handle(message('برگشت'))
    state = flow.store.get(CUSTOMER)
    assert state['step'] == 'edit_menu' and 'edit_field' not in state
    assert state['data'] == before


def test_revoked_same_office_staff_cannot_supply_private_customer_files(computed_matches):
    own = computed_matches[CUSTOMER]
    other = computed_matches[OTHER_CUSTOMER]
    member = OfficeMembership.query.filter_by(agent_id=other['agent'].id).one()
    member.office_key = 'unit-office-1'
    user = db.session.get(User, member.user_id)
    user.is_active = False
    db.session.commit()
    assert [item['id'] for item in panel.recommendations(CUSTOMER)] == [own['property'].id]


def test_budget_only_edit_preserves_other_fields_and_commits_via_real_crm(flow, records, tmp_path):
    record = records[CUSTOMER]
    data = panel.registered_data(CUSTOMER)
    data.update(phone=record['lead'].phone_number, contact_shared_at=1)
    flow.store.save(CUSTOMER, {'step': 'menu', 'data': data})
    flow.handle(message(EDIT))
    flow.handle(message('بودجه'))
    flow.handle(message('7500'))
    state = flow.store.get(CUSTOMER)
    assert state['step'] == 'review' and state['data']['max_budget'] == 7_500_000_000
    assert {key: state['data'][key] for key in data if key != 'max_budget'} == {
        key: value for key, value in data.items() if key != 'max_budget'}
    assert record['lead'].max_budget == 5_000_000_000
    queue = ExtractionJobs(tmp_path / 'edit-extraction.sqlite3')
    with patch('services.omnichannel_engine.SemanticLLMRouter.classify_and_extract') as llm, \
         patch('services.omnichannel_engine.nurturing_engine.handle_lead_matching_and_dispatch', return_value=[]), \
         patch('services.omnichannel_engine.send_green_lead_alert', return_value=False), \
         patch('services.omnichannel_engine.send_bale_green_lead_alert', return_value=False), \
         patch('telegram_bot.extraction_jobs.ExtractionJobs', return_value=queue):
        flow.handle(message(CONFIRM))
    llm.assert_not_called()
    db.session.expire_all()
    assert CustomerLead.query.filter_by(contact_key=f'telegram:{CUSTOMER}').one().max_budget == 7_500_000_000
    assert record['client'].max_area == 90 and record['client'].min_rooms == 2
    assert record['client'].must_have_parking and record['client'].urgency == 'immediate'
    assert records[OTHER_CUSTOMER]['lead'].max_budget == 5_000_000_000
    assert flow.store.get(CUSTOMER)['step'] == 'menu'


@pytest.mark.parametrize('entry', ['/start', '/customer', 'پنل مشتری'])
def test_start_offers_resume_without_losing_partial_form(flow, entry):
    data = {'deal_type': 'sale', 'district': 'پونک', 'max_budget': 5_000_000_000}
    flow.store.save(CUSTOMER, {'step': 'area', 'data': data})
    flow.handle(message(entry))
    state = flow.store.get(CUSTOMER)
    assert state['step'] == 'menu' and state['resume_step'] == 'area'
    assert state['data'] == data
    flow.handle(message(FIND))
    assert flow.store.get(CUSTOMER)['step'] == 'deal_type'
    assert flow.store.get(CUSTOMER)['data'] == {}


def test_full_mortgage_skips_rent_question_and_retains_zero_rent(flow):
    for value in ('/start', FIND, 'رهن کامل', '70-90', 'دوخواب', 'پونک', '۵۰۰ میلیون تومان'):
        flow.handle(message(value))
    state = flow.store.get(CUSTOMER)
    assert state['step'] == 'features'
    assert state['data']['deal_type'] == 'rent' and state['data']['full_mortgage']
    assert state['data']['max_deposit'] == 500_000_000 and state['data']['max_rent'] == 0
    flow.handle(message('ادامه'))
    flow.handle(message('فوری'))
    assert flow.store.get(CUSTOMER)['step'] == 'contact'


def test_stop_search_preserves_record_and_cancels_worker_before_computation(flow, records, tmp_path):
    lead = records[CUSTOMER]['lead']
    queue = ExtractionJobs(tmp_path / 'stopped-extraction.sqlite3')
    job_id = queue.enqueue(lead.id, CUSTOMER, criteria_for(lead))
    flow.handle(message('توقف جست‌وجو'))
    assert records[CUSTOMER]['client'].lead_status == 'new'
    flow.handle(message('تأیید توقف'))
    db.session.expire_all()
    assert records[CUSTOMER]['client'].lead_status == 'new'
    from telegram_bot.workflow import current_case
    assert current_case(lead).state == 'paused'
    assert CustomerLead.query.count() == 2
    bot = MagicMock()
    with patch('telegram_bot.extraction_jobs.archive_matches') as archive, \
         patch('telegram_bot.inventory_bridge.refresh_inventory') as execute:
        run_job(queue, queue.claim(), bot)
    archive.assert_not_called()
    execute.assert_not_called()
    bot.send_message.assert_not_called()
    assert queue.status(job_id) == 'cancelled'
    assert panel.recommendations(CUSTOMER) == []
    with pytest.raises(ValueError, match='متوقف'):
        panel.request_followup(CUSTOMER)


def test_stop_during_worker_computation_prevents_dispatch(records, tmp_path):
    record = records[CUSTOMER]
    queue = ExtractionJobs(tmp_path / 'late-stop-extraction.sqlite3')
    job_id = queue.enqueue(record['lead'].id, CUSTOMER, criteria_for(record['lead']))

    def stop_during_computation(criteria):
        record['client'].lead_status = 'lost'
        db.session.commit()
        return [record['property']]

    bot = MagicMock()
    with patch('telegram_bot.extraction_jobs.archive_matches', side_effect=stop_during_computation):
        run_job(queue, queue.claim(), bot)
    assert queue.status(job_id) == 'cancelled'
    bot.send_message.assert_not_called()


@pytest.mark.parametrize('entry', MAIN)
def test_all_customer_primary_options_work_under_reply_only_transport(crm_app, records, tmp_path, entry):
    from telebot import apihelper
    from telegram_bot.outbound_policy import ReplyOnlyTeleBot
    from telegram_bot.customer_flow import register_customer_flow
    bot=ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')
    store=FormStore(tmp_path/'reply-only-forms.sqlite3')
    with patch('telegram_bot.customer_flow.FormStore', return_value=store):
        flow=register_customer_flow(bot,lambda: crm_app)
    flow.store.save(CUSTOMER, {'step':'menu','data':{}})
    with patch.object(apihelper,'send_message', return_value={'message_id':1,'date':1,'chat':{'id':CUSTOMER,'type':'private'}}) as network:
        bot.process_new_messages([message(entry)])
    assert network.called
    assert 'عملیات کامل نشد' not in ' '.join(str(call) for call in network.call_args_list)


def test_customer_matching_pages_are_disjoint_and_have_home(callback_bot, records):
    items=[dict(item_for(records[CUSTOMER]['property']), id=index) for index in range(1,10)]
    with patch.object(panel, 'recommendations', return_value=items), patch.object(panel, 'card') as render:
        panel.show_recommendations(callback_bot, CUSTOMER, page=0)
        assert [call.args[2]['id'] for call in render.call_args_list] == [1,2,3,4]
        render.reset_mock()
        dispatch(callback_bot, 'customer:page:0:1')
        assert [call.args[2]['id'] for call in render.call_args_list] == [5,6,7,8]
        markup=callback_bot.send_message.call_args.kwargs['reply_markup']
        assert 'customer:home' in [b.callback_data for row in markup.keyboard for b in row]


@pytest.mark.parametrize('data', ['customer:page:2:0','customer:page:0:-1','customer:page:0:9999999'])
def test_invalid_matching_page_never_displays_cards(callback_bot, records, data):
    with patch.object(panel,'card') as render:
        dispatch(callback_bot, data)
    render.assert_not_called()


def test_card_escapes_html_and_labels_archive_truthfully(callback_bot, records):
    item = item_for(records[CUSTOMER]['property'])
    item.update(title='آپارتمان <test> & نمونه', source_type='archive')
    panel.card(callback_bot, CUSTOMER, item)
    text = callback_bot.send_message.call_args.args[1]
    assert '<test>' not in text and '&lt;test&gt;' in text and '&amp;' in text
    assert 'آرشیو آگهی؛ نتیجه زنده نیست' in text
    assert '>لینک آگهی</a>' in text
    assert callback_bot.send_message.call_args.kwargs['parse_mode'] == 'HTML'


@pytest.mark.parametrize('action', [
    'adm_pub_', 'adm_sendmatch_', 'wiz_exec', 'btn_latest_sale', 'act_visit_',
])
def test_real_dispatcher_blocks_legacy_callbacks_for_unprivileged_customer(crm_app, records, flow, action):
    import telegram_bot.bot as module

    prop = records[CUSTOMER]['property']
    prop.status = 'raw_crawled'
    db.session.commit()
    data = action + str(prop.id) if action.endswith('_') else action
    bot = telebot.TeleBot('123:UNIT_TEST_ONLY', threaded=False)
    bot.send_message = MagicMock()
    bot.answer_callback_query = MagicMock()
    with patch.object(module, 'get_flask_app', return_value=crm_app), \
         patch.object(module, 'is_admin_telegram_user', return_value=False), \
         patch('telegram_bot.customer_flow.FormStore', return_value=flow.store):
        module._register_handlers(bot)
        dispatch(bot, data)
    db.session.expire_all()
    assert prop.status == 'raw_crawled'
    assert Interaction.query.count() == 2
    assert Visit.query.count() == 0
    assert bot.answer_callback_query.call_count == 1
    assert 'قدیمی' in bot.answer_callback_query.call_args.args[1]
    bot.send_message.assert_not_called()
