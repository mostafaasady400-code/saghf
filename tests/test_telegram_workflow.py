"""Workflow contracts against real temporary SQLite; no external messages or crawl data."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch
import pytest
import telebot
from database.db import db
from database.models import Interaction, User, Visit, CustomerLead
from tests.test_telegram_customer_panel import (crm_app, records, computed_matches,
    callback_bot, dispatch, callback, CUSTOMER, OTHER_CUSTOMER, item_for)
from telegram_bot import workflow as w
from telegram_bot import operations as ops
from telegram_bot.customer_panel import request_followup
from telegram_bot.office_access import OfficeMembership, principal_for
from telegram_bot.office_flow import OfficeFlow


def office_principal(record):
    member = OfficeMembership.query.filter_by(agent_id=record['agent'].id).one()
    return principal_for(member.telegram_id)


def proposal_for(record):
    row, _ = request_followup(CUSTOMER, 'saghf_visit', item_for(record['property']))
    proposal = w.offer_visit(office_principal(record), row, datetime.utcnow()+timedelta(days=1))
    db.session.commit()
    return proposal


def reminder_for(record):
    item = Interaction(type='office_reminder', client_id=record['client'].id,
        target_type='client', target_id=record['client'].id, agent_id=record['agent'].id,
        summary='Private note must not enter notification', outcome='pending',
        next_followup_date=datetime.utcnow()-timedelta(seconds=1))
    db.session.add(item); db.session.commit()
    ops.enqueue_due_reminders()
    return item, w.MessageOutbox.query.filter_by(kind='reminder', target_id=item.id).one()


def test_cases_are_versioned_and_never_contain_customer_phone(records):
    lead = records[CUSTOMER]['lead']
    first = w.open_case(lead); db.session.commit()
    assert w.open_case(lead).id == first.id
    assert lead.phone_number not in first.criteria
    lead.max_budget += 1
    next_case = w.open_case(lead); db.session.commit()
    assert next_case.id != first.id and first.state == 'superseded'
    assert w.current_case(lead).id == next_case.id


def test_pause_and_resume_preserve_sales_lifecycle(records, tmp_path):
    from telegram_bot.extraction_jobs import ExtractionJobs
    lead, client = records[CUSTOMER]['lead'], records[CUSTOMER]['client']
    client.lead_status = 'negotiating'; db.session.commit()
    queue = ExtractionJobs(tmp_path/'queue.sqlite3')
    job_id = queue.enqueue(lead.id, CUSTOMER, w.lead_criteria(lead))
    queue.finish(job_id, 'cancelled')
    w.set_search_active(lead, False)
    assert client.lead_status == 'negotiating' and not w.search_enabled(lead)
    with patch('telegram_bot.extraction_jobs.ExtractionJobs', return_value=queue):
        w.set_search_active(lead, True)
    assert client.lead_status == 'negotiating' and w.search_enabled(lead)
    assert queue.status(job_id) == 'queued'


@pytest.mark.parametrize('state', ['lost', 'contract_won'])
def test_customer_cannot_reopen_closed_sales_case(records, state):
    record = records[CUSTOMER]
    record['client'].lead_status = state; db.session.commit()
    with pytest.raises(ValueError, match='بسته'):
        w.set_search_active(record['lead'], True)
    assert record['client'].lead_status == state


def test_rejection_reason_is_owned_and_does_not_rewrite_need(callback_bot, computed_matches):
    from telegram_bot.customer_panel import PanelSelection
    record = computed_matches[CUSTOMER]; prop = record['property']
    original = w.lead_criteria(record['lead'])
    dispatch(callback_bot, f'customer:reject:property:{prop.id}')
    dispatch(callback_bot, f'customer:reason:property:{prop.id}:price', user_id=OTHER_CUSTOMER)
    assert w.RecommendationFeedback.query.count() == 0
    dispatch(callback_bot, f'customer:reason:property:{prop.id}:price')
    assert w.RecommendationFeedback.query.one().reason == 'price'
    assert PanelSelection.query.one().rejected
    assert w.lead_criteria(record['lead']) == original


@pytest.mark.parametrize('reason', ['unknown', 'phone', 'price:extra'])
def test_invalid_reason_cannot_mutate(callback_bot, computed_matches, reason):
    dispatch(callback_bot, f'customer:reason:property:{computed_matches[CUSTOMER]["property"].id}:{reason}')
    assert w.RecommendationFeedback.query.count() == 0


def test_visit_requires_customer_acceptance_and_replay_is_idempotent(records):
    proposal = proposal_for(records[CUSTOMER])
    assert Visit.query.count() == 0
    visit_id = w.answer_proposal(CUSTOMER, proposal.id, True)
    assert Visit.query.count() == 1
    assert w.answer_proposal(CUSTOMER, proposal.id, True) == visit_id
    assert Visit.query.count() == 1
    assert db.session.get(Interaction, proposal.interaction_id).outcome == 'visit_scheduled'


def test_other_customer_cannot_accept_visit(records):
    proposal = proposal_for(records[CUSTOMER])
    with pytest.raises(PermissionError): w.answer_proposal(OTHER_CUSTOMER, proposal.id, True)
    assert Visit.query.count() == 0


def test_declined_time_keeps_request_pending(records):
    proposal = proposal_for(records[CUSTOMER])
    assert w.answer_proposal(CUSTOMER, proposal.id, False) is None
    assert Visit.query.count() == 0
    assert db.session.get(Interaction, proposal.interaction_id).outcome == 'pending'
    db.session.expire_all()
    assert proposal.state == 'declined'


@pytest.mark.parametrize('change', ['expired', 'paused', 'revoked', 'unavailable', 'new_need'])
def test_changed_visit_conditions_fail_closed(records, change):
    record = records[CUSTOMER]
    w.open_case(record['lead']); db.session.commit()
    proposal = proposal_for(record)
    if change == 'expired': proposal.expires_at = datetime.utcnow()-timedelta(seconds=1)
    elif change == 'paused': w.set_search_active(record['lead'], False)
    elif change == 'revoked':
        membership = OfficeMembership.query.filter_by(agent_id=record['agent'].id).one()
        db.session.get(User, membership.user_id).is_active = False
    elif change == 'unavailable': record['property'].status = 'sold'
    else:
        record['lead'].max_budget += 1; w.open_case(record['lead'])
    db.session.commit()
    with pytest.raises(ValueError): w.answer_proposal(CUSTOMER, proposal.id, True)
    assert Visit.query.count() == 0


def test_foreign_office_cannot_offer_visit(records):
    row, _ = request_followup(CUSTOMER, 'saghf_visit', item_for(records[CUSTOMER]['property']))
    with pytest.raises(ValueError):
        w.offer_visit(office_principal(records[OTHER_CUSTOMER]), row, datetime.utcnow()+timedelta(days=1))
    assert w.VisitProposal.query.count() == 0


def test_archived_source_request_cannot_make_internal_visit(records):
    row, _ = request_followup(CUSTOMER, 'saghf_visit', {'source_type': 'archive', 'id': 1})
    with pytest.raises(ValueError):
        w.offer_visit(office_principal(records[CUSTOMER]), row, datetime.utcnow()+timedelta(days=1))
    assert Visit.query.count() == 0


def test_reminder_planner_never_enqueues_automatic_messages(records):
    record = records[CUSTOMER]
    db.session.add(Interaction(type='office_reminder', client_id=record['client'].id,
        agent_id=record['agent'].id, outcome='pending', summary='test reminder',
        next_followup_date=datetime.utcnow()-timedelta(seconds=1)))
    db.session.commit()
    ops.enqueue_due_reminders(); ops.enqueue_due_reminders()
    assert w.MessageOutbox.query.count() == 0


@pytest.mark.parametrize('kind', ['reminder', 'visit_offer', 'visit_answer', 'visit_review', 'operations_probe'])
def test_all_new_outbox_messages_are_suppressed(records, kind):
    row = w.enqueue_message('quiet:'+kind, CUSTOMER, kind, 1, 'not sent')
    db.session.commit()
    bot = MagicMock()
    assert row.state == 'suppressed'
    assert not ops.dispatch_one(bot)
    bot.send_message.assert_not_called()
    assert row.attempts == 0 and row.message_id is None


@pytest.mark.parametrize('future', [False, True])
def test_legacy_pending_messages_are_suppressed_without_retry(records, future):
    row = w.MessageOutbox(event_key='legacy', recipient=str(CUSTOMER), kind='reminder',
        target_id=1, payload='{}', state='pending',
        available_at=datetime.utcnow()+timedelta(days=1 if future else -1))
    db.session.add(row); db.session.commit()
    bot = MagicMock()
    assert ops.dispatch_one(bot)
    assert row.state == 'suppressed' and row.attempts == 0
    assert not ops.dispatch_one(bot)
    bot.send_message.assert_not_called()


def test_crashed_send_is_marked_unknown_not_replayed(records):
    row = w.MessageOutbox(event_key='crashed', recipient=str(CUSTOMER), kind='reminder',
        target_id=1, payload='{}', state='sending', updated_at=datetime.utcnow()-timedelta(minutes=6))
    db.session.add(row); db.session.commit()
    bot = MagicMock(); ops.dispatch_one(bot)
    db.session.refresh(row)
    assert row.state == 'unknown'
    bot.send_message.assert_not_called()


def test_health_reports_missing_services_and_daily_backup_ttl(records):
    report = ops.health_report()
    assert not report['services']['telegram']['healthy']
    db.session.add(w.ServiceHeartbeat(service='backup', state='ready', seen_at=datetime.utcnow()-timedelta(hours=12)))
    db.session.commit()
    assert ops.health_report()['services']['backup']['healthy']


def test_backup_can_be_restored_and_does_not_mutate_crm(crm_app, records, tmp_path):
    count = CustomerLead.query.count()
    name = ops.verified_backup(crm_app, tmp_path/'backups')
    assert (tmp_path/'backups'/name).is_file()
    assert ops.verified_backup(crm_app, tmp_path/'backups') == name
    assert CustomerLead.query.count() == count


def test_commands_do_not_expose_office_to_public_or_revoked_member(records):
    member = OfficeMembership.query.filter_by(agent_id=records[OTHER_CUSTOMER]['agent'].id).one()
    member.active = False; db.session.commit()
    bot = MagicMock(); ops.configure_commands(bot)
    calls = bot.set_my_commands.call_args_list
    assert 'office' not in [command.command for command in calls[0].args[0]]
    per_chat = {call.kwargs['scope'].chat_id: [x.command for x in call.args[0]] for call in calls[1:]}
    assert 'office' not in per_chat[int(member.telegram_id)]
    assert 'office' in per_chat[int(office_principal(records[CUSTOMER]).telegram_id)]
    assert 'menu' in [command.command for command in calls[0].args[0]]
    menu_calls = bot.set_chat_menu_button.call_args_list
    assert menu_calls[0].kwargs['menu_button'].type == 'commands'
    assert {call.kwargs['chat_id'] for call in menu_calls[1:]} == set(per_chat)


def test_office_keyboard_is_dismissible_with_return_to_customer():
    from telegram_bot.office_flow import office_keyboard
    markup = office_keyboard()
    assert markup.is_persistent is False and markup.one_time_keyboard is False
    assert 'پنل مشتری' in [button['text'] for row in markup.keyboard for button in row]


def test_backup_failure_does_not_stop_notification_tick(crm_app, records):
    from contextlib import nullcontext
    with patch('sys.argv', ['operations', '--once']), \
         patch('telegram_bot.runtime.create_crm_context', return_value=crm_app), \
         patch('telegram_bot.runtime.check_database'), \
         patch('telegram_bot.runtime.polling_lock', return_value=nullcontext()), \
         patch('telegram_bot.bot.get_bot', return_value=MagicMock()), \
         patch.object(ops, 'verified_backup', side_effect=RuntimeError('private detail')), \
         patch.object(ops, 'enqueue_due_reminders') as due, \
         patch.object(ops, 'dispatch_one', return_value=False) as dispatch_one:
        ops.main()
    due.assert_called_once()
    dispatch_one.assert_called_once()
    assert db.session.get(w.ServiceHeartbeat, 'backup').state == 'degraded'
    assert db.session.get(w.ServiceHeartbeat, 'operations').state == 'ready'


def test_visit_review_is_owned_and_requires_completed_visit(crm_app, records):
    record = records[CUSTOMER]
    visit = Visit(client_id=record['client'].id, property_id=record['property'].id,
                  agent_id=record['agent'].id, scheduled_time=datetime.utcnow()-timedelta(hours=1), status='completed')
    db.session.add(visit); db.session.commit()
    bot = telebot.TeleBot('123:UNIT_TEST_ONLY', threaded=False)
    bot.send_message = MagicMock(); bot.answer_callback_query = MagicMock()
    w.register_callbacks(bot, lambda: crm_app)
    dispatch(bot, f'workflow:liked:{visit.id}', user_id=OTHER_CUSTOMER)
    assert w.VisitReview.query.count() == 0
    dispatch(bot, f'workflow:liked:{visit.id}')
    assert w.VisitReview.query.one().result == 'liked'


def test_office_visit_form_consumes_confirmation_without_creating_visit(crm_app, records):
    record = records[CUSTOMER]
    request, _ = request_followup(CUSTOMER, 'saghf_visit', item_for(record['property']))
    flow = OfficeFlow(MagicMock(), lambda: crm_app); principal = office_principal(record)
    flow.start_action(int(principal.telegram_id), principal, 'visit_offer', request.id)
    from telegram_bot.office_access import OfficeAction
    action = OfficeAction.query.filter_by(kind='visit_offer', consumed=False).one()
    due = (datetime.utcnow()+timedelta(days=1, hours=3, minutes=30)).strftime('%Y-%m-%d %H:%M')
    flow.input_action(int(principal.telegram_id), principal, action, due+' | هماهنگی بازدید')
    flow.confirm_action(int(principal.telegram_id), principal, action.token)
    flow.confirm_action(int(principal.telegram_id), principal, action.token)
    assert w.VisitProposal.query.count() == 1 and Visit.query.count() == 0


def test_future_visit_cannot_be_marked_completed(crm_app, records):
    record = records[CUSTOMER]
    visit = Visit(client_id=record['client'].id, property_id=record['property'].id,
                  agent_id=record['agent'].id, scheduled_time=datetime.utcnow()+timedelta(days=1), status='scheduled')
    db.session.add(visit); db.session.commit()
    with pytest.raises(ValueError):
        OfficeFlow(MagicMock(), lambda: crm_app).start_action(901, office_principal(record), 'visit_status', visit.id, 'completed')


def test_completed_visit_queues_feedback_without_replay(crm_app, records):
    record = records[CUSTOMER]
    visit = Visit(client_id=record['client'].id, property_id=record['property'].id,
                  agent_id=record['agent'].id, scheduled_time=datetime.utcnow()-timedelta(days=1), status='scheduled')
    db.session.add(visit); db.session.commit()
    flow = OfficeFlow(MagicMock(), lambda: crm_app); principal = office_principal(record)
    flow.start_action(901, principal, 'visit_status', visit.id, 'completed')
    from telegram_bot.office_access import OfficeAction
    action = OfficeAction.query.filter_by(kind='visit_status', consumed=False).one()
    flow.confirm_action(901, principal, action.token); flow.confirm_action(901, principal, action.token)
    db.session.refresh(visit)
    assert visit.status == 'completed'
    assert w.MessageOutbox.query.filter_by(kind='visit_review').count() == 1
