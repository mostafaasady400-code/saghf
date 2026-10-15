import json
import sqlite3
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch

import pytest
from database.db import db
from database.models import Interaction,Visit
from telegram_bot import customer_panel as panel
from telegram_bot.decision_support import DecisionStore,comparison_view,relaxation_options,show_relaxations,slot_options,handle_callback
from telegram_bot.workflow import lead_criteria
from telegram_bot.search_delivery import fingerprint
from telegram_bot.customer_flow import FormStore,CustomerFlow
from tests.test_telegram_customer_panel import crm_app,records,computed_matches,callback_bot,CUSTOMER,OTHER_CUSTOMER,item_for,dispatch,callback


@pytest.fixture
def store(crm_app,tmp_path):
    return DecisionStore(tmp_path/'decisions.sqlite3')


def test_comparison_is_scoped_and_capped_at_three(store):
    keys=['property:1','property:2','property:3','property:4']
    for value in keys[:3]:store.comparison(1,'criteria',value,keys)
    with pytest.raises(ValueError):store.comparison(1,'criteria',keys[3],keys)
    assert store.comparison(2,'criteria',allowed=keys)==[]
    assert store.comparison(1,'changed',allowed=keys)==[]


def test_comparison_revalidates_removed_item(store):
    store.comparison(1,'same','property:1',['property:1'])
    assert store.comparison(1,'same',allowed=[])==[]


def test_comparison_never_leaks_other_customer_files(records,computed_matches):
    for owner in (CUSTOMER,OTHER_CUSTOMER):
        db.session.add(panel.PanelSelection(telegram_id=str(owner),source_type='property',source_id=records[owner]['property'].id,saved=True))
    db.session.commit()
    text,buttons=comparison_view(CUSTOMER,records[CUSTOMER]['lead'])
    labels=[button.text for row in buttons.keyboard for button in row]
    assert records[CUSTOMER]['property'].title in labels
    assert records[OTHER_CUSTOMER]['property'].title not in labels


def test_comparison_escapes_title_and_keeps_source_link(records):
    item=item_for(records[CUSTOMER]['property']); item['title']='<script>bad</script>'
    with patch('telegram_bot.decision_support.saved_items',return_value=[item]):
        text,_=comparison_view(CUSTOMER,records[CUSTOMER]['lead'],'property:'+str(item['id']))
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert 'لینک آگهی' in text


def test_relaxation_counts_real_extra_items_and_changes_one_field(records):
    lead=records[CUSTOMER]['lead'];base=item_for(records[CUSTOMER]['property'])
    near=dict(base,id=88,total_price=5_200_000_000,source_url='https://divar.ir/v/near')
    far=dict(base,id=89,total_price=9_000_000_000,source_url='https://divar.ir/v/far')
    before=lead_criteria(lead)
    options=relaxation_options(lead,[base,near,far])
    assert options==[{'changes':{'max_budget':5_200_000_000},'extra_count':1}]
    assert lead_criteria(lead)==before


def test_no_unsupported_suggestion_when_no_extra_inventory(records):
    lead=records[CUSTOMER]['lead']
    assert relaxation_options(lead,[])==[]


def test_relaxation_never_drops_required_features(records):
    lead=records[CUSTOMER]['lead']; item=item_for(records[CUSTOMER]['property'])
    item.update(total_price=5_200_000_000,has_parking=False)
    assert relaxation_options(lead,[item])==[]

def test_irrelevant_cheaper_files_cannot_hide_valid_relaxation(records):
    lead=records[CUSTOMER]['lead'];base=item_for(records[CUSTOMER]['property'])
    distractions=[dict(base,id=100+i,district='محله دیگر',total_price=5_010_000_000+i*1_000_000) for i in range(8)]
    target=dict(base,id=200,total_price=5_200_000_000,source_url='https://divar.ir/v/valid')
    assert relaxation_options(lead,[*distractions,target])[0]['changes']=={'max_budget':5_200_000_000}

def test_comparison_page_keeps_button_positions_and_selection(records):
    lead=records[CUSTOMER]['lead'];base=item_for(records[CUSTOMER]['property'])
    items=[dict(base,id=i,title=f'ملک {i}') for i in range(1,9)]
    with patch('telegram_bot.decision_support.saved_items',return_value=items):
        _,buttons=comparison_view(CUSTOMER,lead,page=1)
        before=[row[0].text for row in buttons.keyboard[:3]]
        text,buttons=comparison_view(CUSTOMER,lead,'property:7',page=1)
        after=[row[0].text.removeprefix('✓ ') for row in buttons.keyboard[:3]]
    assert before==after and 'انتخاب 1 از ۳' in text
    assert all(len(button.callback_data.encode())<=64 for row in buttons.keyboard for button in row)

def test_slot_options_reject_ambiguous_naive_time():
    with pytest.raises(ValueError):slot_options(datetime(2026,10,15))


def test_actions_are_bound_to_recipient_criteria_expiry_and_kind(store):
    token=store.issue_action(1,'same','relax',{'changes':{'max_budget':10}})
    for user,signature,kind in [(2,'same','relax'),(1,'changed','relax'),(1,'same','slots')]:
        with pytest.raises(ValueError):store.action(token,user,signature,kind)
    with patch('telegram_bot.decision_support.time.time',return_value=10**12):
        with pytest.raises(ValueError):store.action(token,1,'same','relax')
    store.consume(token)
    with pytest.raises(ValueError):store.action(token,1,'same','relax')


def test_apply_only_updates_draft_not_crm(records,crm_app,tmp_path):
    lead=records[CUSTOMER]['lead'];before=lead_criteria(lead)
    option={'changes':{'max_budget':5_200_000_000},'extra_count':1}
    store=DecisionStore();token=store.issue_action(CUSTOMER,fingerprint(before),'relax',option)
    bot=MagicMock();flow=CustomerFlow(bot,lambda:crm_app,FormStore(tmp_path/'forms.sqlite3'));bot.saghf_customer_flow=flow
    flow.store.save(CUSTOMER,{'step':'menu','data':{'phone':'09120000101','contact_shared_at':1}})
    with patch('telegram_bot.decision_support.relaxation_pool',return_value=[]),patch('telegram_bot.decision_support.relaxation_options',return_value=[option]),patch.object(flow,'show'):
        handle_callback(bot,callback('decision:apply:'+token))
    assert lead_criteria(lead)==before
    draft=flow.store.get(CUSTOMER)
    assert draft['step']=='review' and draft['data']['max_budget']==5_200_000_000


def test_stale_inventory_rejects_draft_change(records):
    lead=records[CUSTOMER]['lead'];option={'changes':{'max_budget':5_200_000_000},'extra_count':1}
    token=DecisionStore().issue_action(CUSTOMER,fingerprint(lead_criteria(lead)),'relax',option)
    with patch('telegram_bot.decision_support.relaxation_pool',return_value=[]):
        with pytest.raises(ValueError):handle_callback(MagicMock(),callback('decision:apply:'+token))


def test_slots_use_tehran_and_remain_preferences(store):
    slots=slot_options(datetime(2026,10,15,22,tzinfo=timezone.utc))
    assert len(slots)==6
    assert datetime.fromisoformat(slots[0]['starts']).hour==6
    token=store.issue_action(1,'same','slots',{'interaction_id':12,'slots':slots})
    value=store.set_preference(token,1,'same',0)
    assert value==slots[0]
    with pytest.raises(ValueError):store.set_preference(token,1,'same',1)


def test_selecting_visit_window_creates_no_confirmed_visit(records,computed_matches):
    lead=records[CUSTOMER]['lead']; item=item_for(records[CUSTOMER]['property'])
    interaction,_=panel.request_followup(CUSTOMER,'saghf_visit',item)
    before=Visit.query.count();slots=slot_options()
    token=DecisionStore().issue_action(CUSTOMER,fingerprint(lead_criteria(lead)),'slots',{'interaction_id':interaction.id,'slots':slots,'item':['property',item['id']]})
    handle_callback(MagicMock(),callback('decision:slot:'+token+':0'))
    assert Visit.query.count()==before and DecisionStore().preference(interaction.id)


def test_group_or_other_user_cannot_operate_customer_callback(callback_bot,records):
    dispatch(callback_bot,'decision:compare',chat_id=-100,chat_type='group')
    assert callback_bot.answer_callback_query.call_args.args[1]=='دسترسی مجاز نیست.'


def test_metrics_never_store_message_or_phone(crm_app):
    from telegram_bot.telemetry import record_event,metric_counts
    assert record_event('callback_error')
    assert metric_counts()['callback_error']==1
    with pytest.raises(ValueError):record_event('phone=private')
    store=DecisionStore()
    with sqlite3.connect(store.path) as conn:
        columns=[row[1] for row in conn.execute('PRAGMA table_info(bot_metrics)')]
    assert columns==['day','kind','count']


def booked_visit(records):
    from tests.test_telegram_workflow import proposal_for
    from telegram_bot.workflow import answer_proposal
    proposal=proposal_for(records[CUSTOMER])
    return db.session.get(Visit,answer_proposal(CUSTOMER,proposal.id,True))


def test_reschedule_request_is_idempotent_and_preserves_original(records):
    from telegram_bot.decision_support import request_reschedule
    visit=booked_visit(records)
    row,created=request_reschedule(CUSTOMER,visit.id)
    again,repeated=request_reschedule(CUSTOMER,visit.id)
    assert row.id==again.id and created and not repeated
    assert visit.status=='scheduled' and Visit.query.count()==1
    with pytest.raises(ValueError):request_reschedule(OTHER_CUSTOMER,visit.id)


def test_reschedule_replaces_time_only_after_customer_acceptance(records):
    from telegram_bot.decision_support import request_reschedule
    from tests.test_telegram_workflow import office_principal
    from telegram_bot.workflow import offer_visit,answer_proposal
    original=booked_visit(records)
    row,_=request_reschedule(CUSTOMER,original.id)
    proposal=offer_visit(office_principal(records[CUSTOMER]),row,datetime.utcnow()+timedelta(days=2));db.session.commit()
    assert original.status=='scheduled'
    new_id=answer_proposal(CUSTOMER,proposal.id,True)
    db.session.refresh(original)
    assert original.status=='cancelled' and db.session.get(Visit,new_id).status=='scheduled'
    assert answer_proposal(CUSTOMER,proposal.id,True)==new_id
    assert Visit.query.count()==2


def test_declining_new_time_preserves_original_booking(records):
    from telegram_bot.decision_support import request_reschedule
    from tests.test_telegram_workflow import office_principal
    from telegram_bot.workflow import offer_visit,answer_proposal
    original=booked_visit(records);row,_=request_reschedule(CUSTOMER,original.id)
    proposal=offer_visit(office_principal(records[CUSTOMER]),row,datetime.utcnow()+timedelta(days=2));db.session.commit()
    answer_proposal(CUSTOMER,proposal.id,False)
    assert original.status=='scheduled' and Visit.query.count()==1


def test_pausing_search_does_not_block_rescheduling_existing_booking(records):
    from telegram_bot.decision_support import request_reschedule
    from tests.test_telegram_workflow import office_principal
    from telegram_bot.workflow import set_search_active,offer_visit,answer_proposal,search_enabled
    original=booked_visit(records);lead=records[CUSTOMER]['lead']
    set_search_active(lead,False)
    interaction,_=request_reschedule(CUSTOMER,original.id)
    proposal=offer_visit(office_principal(records[CUSTOMER]),interaction,datetime.utcnow()+timedelta(days=2));db.session.commit()
    new_id=answer_proposal(CUSTOMER,proposal.id,True)
    assert new_id and not search_enabled(lead)
