"""Additive CRM workflow: search state, audit, feedback, visits and durable delivery."""
import hashlib
import json
from datetime import datetime, timedelta
from sqlalchemy import inspect
from database.db import db
from database.models import CustomerLead, Interaction, Property, Visit


class SearchCase(db.Model):
    __tablename__ = 'telegram_search_cases'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('customer_leads.id'), nullable=False, index=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    criteria = db.Column(db.Text, nullable=False)
    state = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class WorkflowAudit(db.Model):
    __tablename__ = 'telegram_workflow_audit'
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(50), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    details = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class RecommendationFeedback(db.Model):
    __tablename__ = 'telegram_recommendation_feedback'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), nullable=False)
    source_type = db.Column(db.String(20), nullable=False)
    source_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(20), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('telegram_id', 'source_type', 'source_id'),)


class MessageOutbox(db.Model):
    __tablename__ = 'telegram_message_outbox'
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(160), nullable=False, unique=True)
    recipient = db.Column(db.String(50), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    payload = db.Column(db.Text, nullable=False)
    state = db.Column(db.String(20), nullable=False, default='suppressed', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    message_id = db.Column(db.BigInteger)
    error_type = db.Column(db.String(60))


class VisitProposal(db.Model):
    __tablename__ = 'telegram_visit_proposals'
    id = db.Column(db.Integer, primary_key=True)
    interaction_id = db.Column(db.Integer, db.ForeignKey('interactions.id'), nullable=False, index=True)
    customer_id = db.Column(db.String(50), nullable=False)
    membership_id = db.Column(db.Integer, nullable=False)
    agent_id = db.Column(db.Integer, nullable=False)
    case_id = db.Column(db.Integer)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String(20), nullable=False, default='pending')
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), unique=True)


class VisitReview(db.Model):
    __tablename__ = 'telegram_visit_reviews'
    visit_id = db.Column(db.Integer, db.ForeignKey('visits.id'), primary_key=True)
    customer_id = db.Column(db.String(50), nullable=False)
    result = db.Column(db.String(20), nullable=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ServiceHeartbeat(db.Model):
    __tablename__ = 'telegram_service_heartbeats'
    service = db.Column(db.String(30), primary_key=True)
    seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    state = db.Column(db.String(20), nullable=False, default='ready')


MODELS = (SearchCase, WorkflowAudit, RecommendationFeedback, MessageOutbox,
          VisitProposal, VisitReview, ServiceHeartbeat)
REASONS = {'price': 'قیمت', 'district': 'محله', 'area': 'متراژ',
           'features': 'امکانات', 'layout': 'نقشه ملک', 'other': 'دلیل دیگر'}


def ensure_schema():
    for model in MODELS:
        model.__table__.create(db.engine, checkfirst=True)


def audit(actor, kind, target_id, **details):
    # Only structural metadata; never free text, phone numbers, tokens or cookies.
    safe = {k: v for k, v in details.items() if k in ('state', 'previous', 'reason', 'case_id', 'visit_id', 'agent_id')}
    db.session.add(WorkflowAudit(actor=str(actor), kind=kind, target_id=target_id,
                                details=json.dumps(safe, ensure_ascii=False)))


def current_case(lead):
    if not inspect(db.engine).has_table(SearchCase.__tablename__):
        return None
    return SearchCase.query.filter_by(lead_id=lead.id).order_by(SearchCase.id.desc()).populate_existing().first()


def search_enabled(lead):
    if not lead or not lead.crm_client or lead.crm_client.lead_status in ('lost', 'contract_won'):
        return False
    case = current_case(lead)
    return case is None or case.state == 'active'


def lead_criteria(lead):
    client = lead.crm_client
    return dict(deal_type=lead.deal_type, preferred_districts=lead.preferred_districts,
        min_area=client.min_area, max_area=client.max_area, min_rooms=client.min_rooms,
        max_budget=lead.max_budget, max_deposit=lead.max_deposit, max_rent=lead.max_rent,
        preferred_features=lead.preferred_features)


def open_case(lead):
    value = json.dumps(lead_criteria(lead), sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    case = current_case(lead)
    if case and case.fingerprint == fingerprint:
        if case.state != 'active':
            audit(lead.contact_key, 'search_resumed', case.id, previous=case.state, state='active')
        case.state, case.updated_at = 'active', datetime.utcnow()
    else:
        if case:
            case.state, case.updated_at = 'superseded', datetime.utcnow()
        case = SearchCase(lead_id=lead.id, fingerprint=fingerprint, criteria=value, state='active')
        db.session.add(case)
        db.session.flush()
        audit(lead.contact_key, 'search_registered', case.id, state='active')
    return case


def set_search_active(lead, active):
    if active and lead.crm_client.lead_status in ('lost', 'contract_won'):
        raise ValueError('پرونده CRM بسته است؛ تغییر وضعیت باید توسط مشاور انجام شود.')
    case = open_case(lead) if active else (current_case(lead) or open_case(lead))
    previous = case.state
    case.state, case.updated_at = ('active' if active else 'paused'), datetime.utcnow()
    if previous != case.state:
        audit(lead.contact_key, 'search_state', case.id, previous=previous, state=case.state)
    db.session.commit()
    if active:
        from telegram_bot.extraction_jobs import ExtractionJobs
        ExtractionJobs().enqueue(lead.id, lead.contact_key.split(':')[1], lead_criteria(lead))
    return case


def enqueue_message(event_key, recipient, kind, target_id, text, rows=None):
    recipient = str(recipient)
    if not recipient.isascii() or not recipient.isdigit() or not 0 < int(recipient) < 2**63:
        raise ValueError('invalid_message_recipient')
    existing = MessageOutbox.query.filter_by(event_key=event_key).first()
    if existing:
        return existing
    message = MessageOutbox(event_key=event_key, recipient=recipient, kind=kind,
        target_id=target_id, state='suppressed', error_type='PullOnlyPolicy',
        payload=json.dumps({'text': text, 'rows': rows or []}, ensure_ascii=False))
    db.session.add(message)
    return message


def customer_for_client(client_id):
    rows = CustomerLead.query.filter_by(client_id=client_id).filter(
        CustomerLead.contact_key.like('telegram:%')).limit(2).all()
    if len(rows) != 1:
        raise ValueError('هویت تلگرام مشتری روشن نیست.')
    return rows[0]


def offer_visit(principal, interaction, due):
    from telegram_bot.office_access import OfficeMembership, principal_for
    lead = customer_for_client(interaction.client_id)
    prop = db.session.get(Property, interaction.property_id) if interaction.property_id else None
    from telegram_bot.customer_panel import _fits
    rescheduling=interaction.target_type=='visit'
    if rescheduling:
        original=db.session.get(Visit,interaction.target_id)
        if not lead or not original or original.client_id!=interaction.client_id or original.property_id!=interaction.property_id or original.agent_id!=lead.crm_client.assigned_agent_id or original.status!='scheduled' or original.scheduled_time<=datetime.utcnow():
            raise ValueError('بازدید قبلی برای تغییر زمان معتبر نیست.')
    if (interaction.type != 'saghf_visit' or interaction.outcome != 'pending' or (not rescheduling and not search_enabled(lead))
            or lead.crm_client.assigned_agent_id not in principal.agent_ids or not prop
            or prop.assigned_agent_id not in principal.agent_ids or prop.status not in ('available', 'verified')
            or prop.is_personal_owner is not True or prop.owner_type != 'personal'
            or (not rescheduling and not _fits(prop.to_dict(), lead))
            or not datetime.utcnow() < due <= datetime.utcnow()+timedelta(days=60)):
        raise ValueError('درخواست یا فایل برای تعیین بازدید معتبر نیست.')
    agent_id = lead.crm_client.assigned_agent_id
    member = OfficeMembership.query.filter_by(agent_id=agent_id, active=True).first()
    if not member or not principal_for(member.telegram_id):
        raise ValueError('مشاور فعال برای بازدید مشخص نیست.')
    previous = VisitProposal.query.filter_by(interaction_id=interaction.id, state='pending').first()
    if previous:
        if previous.scheduled_at == due and previous.expires_at > datetime.utcnow():
            return previous
        previous.state = 'superseded'
    case = current_case(lead)
    proposal = VisitProposal(interaction_id=interaction.id, customer_id=lead.contact_key.split(':')[1],
        membership_id=principal.membership_id, agent_id=agent_id, case_id=case.id if case else None,
        scheduled_at=due, expires_at=min(due, datetime.utcnow()+timedelta(hours=48)))
    db.session.add(proposal); db.session.flush()
    from telegram_bot.office_flow import _when
    enqueue_message(f'visit_offer:{proposal.id}', proposal.customer_id, 'visit_offer', proposal.id,
        f'زمان پیشنهادی بازدید برای درخواست #{interaction.id}: {_when(due)} به وقت تهران.\nتا تأیید شما بازدید قطعی نیست.',
        [[('تأیید زمان', f'workflow:accept:{proposal.id}'), ('زمان دیگری می‌خواهم', f'workflow:decline:{proposal.id}')]])
    audit(principal.telegram_id, 'visit_offered', interaction.id, agent_id=agent_id)
    return proposal


def valid_proposal(proposal):
    from telegram_bot.office_access import OfficeMembership, principal_for
    item = db.session.get(Interaction, proposal.interaction_id)
    if not item:
        return False
    if item.target_type=='visit':
        original=db.session.get(Visit,item.target_id)
        if not original or original.client_id!=item.client_id or original.property_id!=item.property_id or original.agent_id!=proposal.agent_id or original.status!='scheduled' or original.scheduled_time<=datetime.utcnow():
            return False
    lead = customer_for_client(item.client_id)
    prop = db.session.get(Property, item.property_id) if item.property_id else None
    case = current_case(lead)
    actor = db.session.get(OfficeMembership, proposal.membership_id)
    principal = principal_for(actor.telegram_id) if actor else None
    member = OfficeMembership.query.filter_by(agent_id=proposal.agent_id, active=True).first()
    return bool(proposal.state == 'pending' and proposal.expires_at > datetime.utcnow()
        and proposal.scheduled_at > datetime.utcnow() and item.outcome == 'pending' and (search_enabled(lead) or item.target_type=='visit')
        and lead.contact_key == f'telegram:{proposal.customer_id}'
        and (case.id if case else None) == proposal.case_id
        and principal and member and principal_for(member.telegram_id)
        and lead.crm_client.assigned_agent_id == proposal.agent_id
        and proposal.agent_id in principal.agent_ids and prop
        and prop.assigned_agent_id in principal.agent_ids and prop.status in ('available', 'verified')
        and prop.is_personal_owner is True and prop.owner_type == 'personal')


def answer_proposal(customer_id, proposal_id, accept):
    proposal = VisitProposal.query.filter_by(id=proposal_id, customer_id=str(customer_id)).first()
    if not proposal:
        raise PermissionError('foreign_visit_proposal')
    if proposal.state == 'accepted':
        return proposal.visit_id
    if not valid_proposal(proposal):
        raise ValueError('پیشنهاد منقضی یا شرایط پرونده تغییر کرده است.')
    item = db.session.get(Interaction, proposal.interaction_id)
    if accept and Visit.query.filter_by(agent_id=proposal.agent_id, scheduled_time=proposal.scheduled_at, status='scheduled').count():
        raise ValueError('این زمان برای مشاور پر شده است؛ زمان دیگری بخواهید.')
    claimed = VisitProposal.query.filter_by(id=proposal.id, state='pending').update(
        {'state': 'accepted' if accept else 'declined'}, synchronize_session=False)
    if claimed != 1:
        raise ValueError('این پیشنهاد قبلاً پاسخ داده شده است.')
    visit = None
    if accept:
        if item.target_type=='visit':
            changed=Visit.query.filter_by(id=item.target_id,client_id=item.client_id,property_id=item.property_id,agent_id=proposal.agent_id,status='scheduled').filter(Visit.scheduled_time>datetime.utcnow()).update({'status':'cancelled'},synchronize_session='fetch')
            if changed!=1: raise ValueError('وقت قبلی تغییر کرده است؛ دوباره هماهنگ کنید.')
        visit = Visit(client_id=item.client_id, property_id=item.property_id, agent_id=proposal.agent_id,
                      scheduled_time=proposal.scheduled_at, status='scheduled')
        db.session.add(visit); db.session.flush()
        proposal.visit_id = visit.id
        item.outcome, item.next_followup_date = 'visit_scheduled', None
    from telegram_bot.office_access import OfficeMembership
    member = OfficeMembership.query.filter_by(agent_id=proposal.agent_id, active=True).first()
    enqueue_message(f'visit_answer:{proposal.id}', member.telegram_id, 'visit_answer', proposal.id,
        f'مشتری زمان پیشنهادی درخواست #{item.id} را '+('تأیید کرد؛ بازدید در CRM ثبت شد.' if accept else 'نپذیرفت؛ زمان دیگری هماهنگ کنید.'),
        [[('پیگیری‌ها', 'office:followups:0')]])
    audit(f'telegram:{customer_id}', 'visit_answer', proposal.id, state='accepted' if accept else 'declined', visit_id=visit.id if visit else None)
    db.session.commit()
    return visit.id if visit else None


def register_callbacks(bot, app_provider):
    def callback(call):
        user, message = call.from_user, call.message
        if not user or user.is_bot or not message or message.chat.type != 'private' or message.chat.id != user.id:
            return bot.answer_callback_query(call.id, 'دسترسی مجاز نیست.')
        try:
            _, action, raw_id = call.data.split(':')
            if action not in ('accept', 'decline', 'liked', 'not_suitable') or not raw_id.isascii() or not raw_id.isdigit():
                raise ValueError('گزینه معتبر نیست.')
            with app_provider().app_context():
                if action in ('accept', 'decline'):
                    visit_id = answer_proposal(user.id, int(raw_id), action == 'accept')
                    text = f'بازدید #{visit_id} ثبت شده است.' if visit_id else 'درخواست زمان دیگر ثبت شد.'
                else:
                    visit = db.session.get(Visit, int(raw_id))
                    lead = customer_for_client(visit.client_id) if visit else None
                    if not lead or lead.contact_key != f'telegram:{user.id}' or visit.status != 'completed':
                        raise PermissionError('foreign_visit_feedback')
                    review = db.session.get(VisitReview, visit.id)
                    if not review:
                        review = VisitReview(visit_id=visit.id, customer_id=str(user.id))
                        db.session.add(review)
                    review.result, review.updated_at = action, datetime.utcnow()
                    audit(lead.contact_key, 'visit_feedback', visit.id, reason=action)
                    db.session.commit(); text = 'بازخورد بازدید ثبت شد؛ نیاز شما خودکار تغییر نکرد.'
            bot.answer_callback_query(call.id, text)
        except (ValueError, PermissionError) as exc:
            with app_provider().app_context(): db.session.rollback()
            bot.answer_callback_query(call.id, str(exc) if isinstance(exc, ValueError) else 'دسترسی مجاز نیست.')
        except Exception:
            with app_provider().app_context(): db.session.rollback()
            bot.answer_callback_query(call.id, 'ثبت انجام نشد؛ دوباره بررسی کنید.')
    bot.register_callback_query_handler(callback, func=lambda call: bool(call.data and call.data.startswith('workflow:')))
