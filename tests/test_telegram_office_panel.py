"""Office ACL and scoped CRM behavior, tested only against temporary SQLite."""
from datetime import datetime, timedelta
from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import inspect
from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from database.db import db
from database.models import Agent, Client, Interaction, MatchRecord, Property, User, Visit
from telegram_bot.office_access import OfficeAction, OfficeMembership, ensure_office_schema, principal_for
from telegram_bot.office_flow import CLIENTS, FOLLOWUPS, MATCHES, PROPERTIES, REPORTS, TODAY, OfficeFlow
from telegram_bot.runtime import create_crm_context


@pytest.fixture
def app(tmp_path):
    class TestConfig:
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + str(tmp_path / 'office.sqlite3').replace('\\', '/')
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        TESTING = True
    instance = create_crm_context(TestConfig)
    with instance.app_context():
        core_tables = [table for table in db.metadata.sorted_tables
                       if table.name not in {OfficeMembership.__tablename__, OfficeAction.__tablename__}]
        db.metadata.create_all(db.engine, tables=core_tables)
        ensure_office_schema()
        yield instance
        db.session.remove()
        db.engine.dispose()


def message(text='', who=101, chat_type='private', chat_id=None):
    return Message.de_json({'message_id': 10, 'date': 1,
        'chat': {'id': who if chat_id is None else chat_id, 'type': chat_type},
        'from': {'id': who, 'is_bot': False, 'first_name': 'مشاور'}, 'text': text})


def callback(data, who=101, callback_id='callback-10'):
    return CallbackQuery.de_json({'id': callback_id, 'chat_instance': 'office-tests',
        'from': {'id': who, 'is_bot': False, 'first_name': 'مشاور'},
        'message': message(who=who).json, 'data': data})


def member(who, office='alpha', role='agent', active=True, user_active=True, agent_active=True, user_role='agent'):
    user = User(username=f'office-{who}', password_hash='not-used', full_name=f'User {who}',
        telegram_id=str(who), role=user_role, is_active=user_active)
    agent = Agent(name=f'Agent {who}', is_active=agent_active)
    db.session.add_all([user, agent])
    db.session.flush()
    membership = OfficeMembership(telegram_id=str(who), user_id=user.id, agent_id=agent.id,
        office_key=office, office_role=role, active=active)
    db.session.add(membership)
    db.session.commit()
    return N(user=user, agent=agent, membership=membership)


def client(agent_id, name='Alpha Client'):
    row = Client(full_name=name, phone_number='09120000000', assigned_agent_id=agent_id,
        preferred_deal_type='sale', min_area=70, max_area=90, min_rooms=2,
        max_budget=10_000_000_000, preferred_districts_json='["پونک"]')
    db.session.add(row)
    db.session.flush()
    return row


def property_row(agent_id, title='Alpha Property'):
    row = Property(title=title, district='پونک', deal_type='sale', area=80, rooms=2,
        total_price=5_000_000_000, assigned_agent_id=agent_id, source='direct_owner',
        status='available', source_url='https://divar.ir/v/test-alpha')
    db.session.add(row)
    db.session.flush()
    return row


@pytest.fixture
def office(app):
    own, peer = member(101), member(102)
    manager, foreign = member(103, role='manager'), member(201, office='beta')
    own.client, own.property = client(own.agent.id), property_row(own.agent.id)
    peer.client, peer.property = client(peer.agent.id, 'Peer Client'), property_row(peer.agent.id, 'Peer Property')
    foreign.client = client(foreign.agent.id, 'FOREIGN_CLIENT_SECRET')
    foreign.property = property_row(foreign.agent.id, 'FOREIGN_PROPERTY_SECRET')
    own.interaction = Interaction(client_id=own.client.id, agent_id=own.agent.id, type='call',
        summary='Alpha followup', next_followup_date=datetime.utcnow() - timedelta(hours=1))
    foreign.interaction = Interaction(client_id=foreign.client.id, agent_id=foreign.agent.id, type='call',
        summary='FOREIGN_FOLLOWUP_SECRET', next_followup_date=datetime.utcnow())
    db.session.add_all([own.interaction, foreign.interaction])
    db.session.commit()
    return N(own=own, peer=peer, manager=manager, foreign=foreign)


@pytest.fixture
def flow(app):
    return OfficeFlow(MagicMock(), lambda: app)


def sent_text(bot):
    rows = []
    for method in (bot.send_message, bot.edit_message_text, bot.answer_callback_query):
        for item in method.call_args_list:
            rows.extend(str(value) for value in item.args if isinstance(value, str))
            rows.extend(str(value) for key, value in item.kwargs.items() if key in {'text', 'caption'})
    return '\n'.join(rows)


def callbacks_sent(bot):
    result = []
    for method in (bot.send_message, bot.edit_message_text):
        for item in method.call_args_list:
            markup = item.kwargs.get('reply_markup')
            if markup is None:
                continue
            for row in markup.keyboard:
                for button in row:
                    value = button.get('callback_data') if isinstance(button, dict) else getattr(button, 'callback_data', None)
                    if value:
                        result.append(value)
    return result


def confirmation(flow):
    tokens = [item for item in callbacks_sent(flow.bot) if item.startswith('office:confirm:')]
    assert tokens, 'CRM writes must require explicit confirmation'
    return tokens[-1]


@pytest.mark.parametrize('entry', [TODAY,CLIENTS,PROPERTIES,MATCHES,FOLLOWUPS,REPORTS])
def test_all_office_primary_options_work_under_reply_only_transport(app, office, entry):
    from telebot import apihelper
    from telegram_bot.outbound_policy import ReplyOnlyTeleBot
    from telegram_bot.office_flow import register_office_flow
    bot=ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')
    register_office_flow(bot,lambda: app)
    member_row=db.session.get(OfficeMembership,office.own.membership.id)
    member_row.panel_mode='office'; db.session.commit()
    with patch.object(apihelper,'send_message', return_value={'message_id':1,'date':1,'chat':{'id':101,'type':'private'}}) as network:
        bot.process_new_messages([message(entry)])
    assert network.called
    payload=' '.join(str(call) for call in network.call_args_list)
    assert 'FOREIGN_' not in payload and 'عملیات انجام نشد' not in payload
    assert 'خواندن یا ثبت اطلاعات انجام نشد' not in payload


def test_overdue_view_excludes_resolved_and_foreign_items(flow, office):
    office.own.interaction.outcome='resolved'; db.session.commit()
    flow.followups(101,principal_for(101),overdue_only=True)
    assert 'Alpha followup' not in sent_text(flow.bot)
    assert 'FOREIGN_FOLLOWUP_SECRET' not in sent_text(flow.bot)
    assert 'office:today' in callbacks_sent(flow.bot)


def test_schema_is_additive_and_idempotent(app):
    entry = member(101)
    tables = set(inspect(db.engine).get_table_names())
    columns = {table: {row['name'] for row in inspect(db.engine).get_columns(table)} for table in tables}
    ensure_office_schema()
    ensure_office_schema()
    assert tables <= set(inspect(db.engine).get_table_names())
    assert db.session.get(User, entry.user.id).telegram_id == '101'
    for table, original in columns.items():
        assert original <= {row['name'] for row in inspect(db.engine).get_columns(table)}
    assert OfficeMembership.query.count() == 1


@pytest.mark.parametrize('user_role', ['user', 'admin', 'super_admin', 'agent'])
def test_user_role_alone_never_grants_office_access(app, user_role):
    db.session.add(User(username='unlinked', password_hash='not-used', full_name='Unlinked',
        telegram_id='101', role=user_role, is_active=True))
    db.session.commit()
    assert principal_for(101) is None


@pytest.mark.parametrize('changes', [{'active': False}, {'user_active': False}, {'agent_active': False}])
def test_every_link_must_be_active(app, changes):
    member(101, **changes)
    assert principal_for(101) is None


@pytest.mark.parametrize('identity', [True, False, None, '', '00101', '-1', '0', '۱۰۱', '101.0', '101 '])
def test_invalid_or_noncanonical_platform_identity_fails_closed(app, identity):
    member(101)
    assert principal_for(identity) is None


def test_customer_role_membership_is_not_an_agent(app):
    member(101, user_role='user')
    assert principal_for(101) is None


def test_ambiguous_active_telegram_user_fails_closed(app):
    member(101)
    db.session.add(User(username='duplicate', password_hash='unused', full_name='Duplicate',
                        telegram_id='101', role='agent', is_active=True))
    db.session.commit()
    assert principal_for(101) is None


def test_agent_id_cannot_bridge_two_offices(app):
    first, second = member(101), member(201, office='beta')
    second.membership.agent_id = first.agent.id
    db.session.commit()
    assert principal_for(101) is None
    assert principal_for(201) is None


def test_telegram_binding_is_exact(app):
    entry = member(101)
    entry.user.telegram_id = '999'
    db.session.commit()
    assert principal_for(101) is None
    assert principal_for(999) is None


def test_agent_and_manager_scopes_only_active_office_memberships(office):
    own, manager = principal_for(101), principal_for(103)
    assert own.agent_ids == (office.own.agent.id,)
    assert own.office_role == 'agent' and own.office_key == 'alpha'
    assert own.user_id == office.own.user.id and own.membership_id == office.own.membership.id
    assert own.agent_id == office.own.agent.id and str(own.telegram_id) == '101'
    assert set(manager.agent_ids) == {office.own.agent.id, office.peer.agent.id, office.manager.agent.id}
    office.peer.membership.active = False
    db.session.commit()
    assert office.peer.agent.id not in principal_for(103).agent_ids


def test_private_chat_only(flow, office):
    assert flow.enabled(message(TODAY))
    assert not flow.enabled(message(TODAY, chat_type='group', chat_id=-100))
    assert not flow.enabled(message(TODAY, chat_id=201))
    assert not flow.enabled(message('/start', who=999))


@pytest.mark.parametrize('command', [TODAY, CLIENTS, PROPERTIES, MATCHES, FOLLOWUPS, REPORTS])
def test_sections_are_real_and_scoped(flow, office, command):
    flow.handle(message(command))
    assert flow.bot.send_message.called or flow.bot.edit_message_text.called
    output = sent_text(flow.bot)
    assert not any(value in output for value in ['FOREIGN_CLIENT_SECRET', 'FOREIGN_PROPERTY_SECRET',
        'FOREIGN_FOLLOWUP_SECRET', 'Peer Client', 'Peer Property'])


def test_manager_sees_same_office_clients_not_other_offices(flow, office):
    flow.callback(callback('office:clients:0', who=103))
    output = sent_text(flow.bot)
    assert 'Alpha Client' in output and 'Peer Client' in output
    assert 'FOREIGN_CLIENT_SECRET' not in output


@pytest.mark.parametrize('kind', ['client', 'property', 'call', 'remind', 'resolve', 'status'])
def test_forged_foreign_callbacks_cannot_read_or_mutate(flow, office, kind):
    targets = {'client': office.foreign.client.id, 'call': office.foreign.client.id,
        'remind': office.foreign.client.id, 'property': office.foreign.property.id,
        'resolve': office.foreign.interaction.id, 'status': office.foreign.property.id}
    suffix = ':sold' if kind == 'status' else ''
    before = Interaction.query.count(), OfficeAction.query.count(), office.foreign.property.status
    flow.callback(callback(f'office:{kind}:{targets[kind]}{suffix}'))
    db.session.expire_all()
    assert (Interaction.query.count(), OfficeAction.query.count(), office.foreign.property.status) == before
    assert not any(value in sent_text(flow.bot) for value in ['FOREIGN_CLIENT_SECRET',
        'FOREIGN_PROPERTY_SECRET', 'FOREIGN_FOLLOWUP_SECRET'])
    assert not any(item.startswith('office:confirm:') for item in callbacks_sent(flow.bot))


@pytest.mark.parametrize('data', ['office:client:NaN', 'office:property:-1', 'office:clients:999999999',
    'office:status:1:drop', 'office:confirm:missing', 'office:resolve:'])
def test_malformed_callback_is_safe(flow, office, data):
    before = Interaction.query.count(), OfficeAction.query.count()
    flow.callback(callback(data))
    assert (Interaction.query.count(), OfficeAction.query.count()) == before


def test_revocation_is_checked_again_on_callback(flow, office):
    flow.handle(message(CLIENTS))
    office.own.membership.active = False
    db.session.commit()
    flow.bot.reset_mock()
    assert not flow.enabled(message('/start'))
    flow.callback(callback(f'office:client:{office.own.client.id}'))
    assert 'Alpha Client' not in sent_text(flow.bot)


def test_client_pagination_has_disjoint_pages(flow, office):
    for index in range(25):
        client(office.own.agent.id, f'Page Client {index:02d}')
    db.session.commit()
    flow.callback(callback('office:clients:0'))
    first = {item for item in callbacks_sent(flow.bot) if item.startswith('office:client:')}
    next_pages = [item for item in callbacks_sent(flow.bot) if item.startswith('office:clients:') and item != 'office:clients:0']
    assert first and next_pages
    flow.bot.reset_mock()
    flow.callback(callback(next_pages[0], callback_id='page-2'))
    second = {item for item in callbacks_sent(flow.bot) if item.startswith('office:client:')}
    assert second and first.isdisjoint(second)
    assert f'office:client:{office.foreign.client.id}' not in first | second
    assert f'office:client:{office.peer.client.id}' not in first | second


def test_status_confirmation_is_idempotent_and_audited(flow, office):
    flow.callback(callback(f'office:status:{office.own.property.id}:reserved'))
    assert office.own.property.status == 'available'
    token = confirmation(flow)
    flow.callback(callback(token, callback_id='confirm-1'))
    db.session.expire_all()
    assert office.own.property.status == 'reserved'
    count = OfficeAction.query.count()
    assert count > 0
    flow.callback(callback(token, callback_id='confirm-replay'))
    assert OfficeAction.query.count() == count
    assert office.own.property.status == 'reserved'


def test_confirmation_cannot_be_replayed_by_another_member(flow, office):
    flow.callback(callback(f'office:status:{office.own.property.id}:reserved'))
    flow.callback(callback(confirmation(flow), who=102))
    assert office.own.property.status == 'available'


def test_revocation_before_confirm_fails_closed(flow, office):
    flow.callback(callback(f'office:status:{office.own.property.id}:reserved'))
    token = confirmation(flow)
    office.own.membership.active = False
    db.session.commit()
    flow.callback(callback(token))
    assert office.own.property.status == 'available'


def test_real_dispatcher_registers_office_handlers(app, office):
    from telegram_bot.office_flow import register_office_flow
    bot = TeleBot('123456:TEST', threaded=False)
    flow = register_office_flow(bot, lambda: app)
    with patch.object(bot, 'send_message') as send, patch.object(bot, 'answer_callback_query'), patch.object(bot, 'edit_message_text') as edit:
        bot.process_new_messages([message(CLIENTS)])
        assert send.called or edit.called
        send.reset_mock()
        edit.reset_mock()
        bot.process_new_callback_query([callback(f'office:client:{office.own.client.id}')])
        assert 'Alpha Client' in sent_text(bot)
    assert isinstance(flow, OfficeFlow)


def test_customer_mode_is_durable_and_does_not_consume_numeric_form_input(app, flow, office):
    assert not flow.enabled(message('/start'))
    assert not flow.enabled(message('/customer'))
    db.session.expire_all()
    assert office.own.membership.panel_mode == 'customer'
    restarted = OfficeFlow(MagicMock(), lambda: app)
    assert not restarted.enabled(message('70-90'))
    assert not restarted.enabled(message('2'))
    assert not restarted.enabled(message('پونک'))
    assert not restarted.enabled(message('خرید'))
    assert restarted.enabled(message('/office'))
    restarted.handle(message('/office'))
    db.session.expire_all()
    assert office.own.membership.panel_mode == 'office'
    assert restarted.enabled(message('2'))
    assert not restarted.enabled(message('/start'))
    db.session.expire_all()
    assert office.own.membership.panel_mode == 'customer'
    assert not restarted.enabled(message('70-90'))


@pytest.mark.parametrize('entry', ['/start', '/customer'])
@pytest.mark.parametrize('who', [101, 103, 999])
def test_real_dispatcher_customer_entry_does_not_grant_or_force_office(app, office, tmp_path, entry, who):
    import telegram_bot.bot as module
    from telegram_bot.customer_flow import FormStore
    store = FormStore(tmp_path / 'entry-forms.sqlite3')
    bot = TeleBot('123456:TEST', threaded=False)
    before = OfficeMembership.query.count()
    with patch.object(module, 'get_flask_app', return_value=app), \
         patch('telegram_bot.customer_flow.FormStore', return_value=store), \
         patch.object(bot, 'send_message') as send:
        module._register_handlers(bot)
        bot.process_new_messages([message(entry, who=who)])
    assert store.get(who)['step'] == 'menu'
    markup = send.call_args.kwargs['reply_markup']
    assert 'جست‌وجوی ملک' in [button['text'] for row in markup.keyboard for button in row]
    assert 'میزکار املاک' not in [button['text'] for row in markup.keyboard for button in row]
    assert OfficeMembership.query.count() == before
    db.session.expire_all()
    member = OfficeMembership.query.filter_by(telegram_id=str(who)).one_or_none()
    if member:
        assert member.panel_mode == 'customer'
        assert member.office_role == ('manager' if who == 103 else 'agent')


def test_call_record_is_created_once_after_text_and_confirmation(flow, office):
    before = Interaction.query.count()
    flow.callback(callback(f'office:call:{office.own.client.id}'))
    assert Interaction.query.count() == before
    flow.handle(message('تماس انجام شد؛ مشتری برای بازدید آماده است.'))
    assert Interaction.query.count() == before
    token = confirmation(flow)
    flow.callback(callback(token, callback_id='call-confirm'))
    assert Interaction.query.count() == before + 1
    created = Interaction.query.order_by(Interaction.id.desc()).first()
    assert created.client_id == office.own.client.id and created.agent_id == office.own.agent.id
    assert 'مشتری برای بازدید آماده' in created.summary
    flow.callback(callback(token, callback_id='call-replay'))
    assert Interaction.query.count() == before + 1


def test_pending_support_and_visit_requests_are_visible_only_in_scoped_crm(flow, office):
    own_request = Interaction(type='support_request', client_id=office.own.client.id,
        summary='SUPPORT_ALPHA_PENDING', outcome='pending', agent_id=None)
    own_visit = Interaction(type='visit_request', client_id=office.own.client.id,
        property_id=office.own.property.id, summary='VISIT_ALPHA_PENDING', outcome='pending', agent_id=None)
    foreign_request = Interaction(type='support_request', client_id=office.foreign.client.id,
        summary='FOREIGN_SUPPORT_PENDING', outcome='pending', agent_id=None)
    db.session.add_all([own_request, own_visit, foreign_request])
    db.session.commit()
    flow.handle(message(FOLLOWUPS))
    output = sent_text(flow.bot)
    assert 'SUPPORT_ALPHA_PENDING' in output and 'VISIT_ALPHA_PENDING' in output
    assert 'FOREIGN_SUPPORT_PENDING' not in output
    assert f'office:resolve:{own_request.id}' in callbacks_sent(flow.bot)
    assert f'office:resolve:{own_visit.id}' in callbacks_sent(flow.bot)


def test_match_and_visit_records_cannot_bridge_tenants(flow, office):
    db.session.add_all([
        MatchRecord(client_id=office.own.client.id, property_id=office.foreign.property.id, match_score=99),
        Visit(client_id=office.own.client.id, property_id=office.foreign.property.id,
            agent_id=office.own.agent.id, scheduled_time=datetime.utcnow()),
    ])
    db.session.commit()
    principal = principal_for(101)
    assert flow.matches(principal).count() == 0
    assert flow.visits(principal).count() == 0
    flow.handle(message(MATCHES))
    flow.handle(message(FOLLOWUPS))
    assert 'FOREIGN_PROPERTY_SECRET' not in sent_text(flow.bot)


def test_property_detail_escapes_content_and_has_direct_ad_link(flow, office):
    office.own.property.title = '<b>unsafe title</b>'
    db.session.commit()
    flow.callback(callback(f'office:property:{office.own.property.id}'))
    output = sent_text(flow.bot)
    assert '&lt;b&gt;unsafe title&lt;/b&gt;' in output
    assert '<a href="https://divar.ir/v/test-alpha">لینک آگهی</a>' in output
