from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from database.db import db
from database.models import Client, Property, Interaction, Visit, Agent

crm_bp = Blueprint('crm', __name__, url_prefix='/crm')

@crm_bp.route('/pipeline')
def pipeline():
    clients = Client.query.all()
    
    stages = {
        'new': [c for c in clients if c.lead_status == 'new'],
        'contacted': [c for c in clients if c.lead_status == 'contacted'],
        'visiting': [c for c in clients if c.lead_status == 'visiting'],
        'negotiating': [c for c in clients if c.lead_status == 'negotiating'],
        'contract_won': [c for c in clients if c.lead_status == 'contract_won'],
        'lost': [c for c in clients if c.lead_status == 'lost']
    }
    
    return render_template('crm/pipeline.html', stages=stages)

@crm_bp.route('/clients/<int:id>/move-stage', methods=['POST'])
def move_stage(id):
    client = Client.query.get_or_404(id)
    new_stage = request.form.get('stage') or request.json.get('stage')
    if new_stage in ['new', 'contacted', 'visiting', 'negotiating', 'contract_won', 'lost']:
        client.lead_status = new_stage
        db.session.commit()
        return jsonify({'success': True, 'new_stage': new_stage})
    return jsonify({'success': False, 'error': 'مرحله نامعتبر است'}), 400

@crm_bp.route('/calls')
def calls():
    interactions = Interaction.query.order_by(Interaction.created_at.desc()).all()
    clients = Client.query.all()
    properties = Property.query.all()
    agents = Agent.query.filter_by(is_active=True).all()
    
    return render_template(
        'crm/calls.html',
        interactions=interactions,
        clients=clients,
        properties=properties,
        agents=agents
    )

@crm_bp.route('/calls/new', methods=['POST'])
def create_call():
    target_type = request.form.get('target_type', 'client')
    target_id = int(request.form.get('target_id'))
    property_id = request.form.get('property_id')
    agent_id = request.form.get('agent_id')
    call_type = request.form.get('type', 'call')
    summary = request.form.get('summary')
    outcome = request.form.get('outcome', 'interested')
    
    next_followup_str = request.form.get('next_followup_date')
    next_followup = None
    if next_followup_str:
        try:
            next_followup = datetime.strptime(next_followup_str, '%Y-%m-%dT%H:%M')
        except Exception:
            pass

    client_id = target_id if target_type == 'client' else None
    owner_id = target_id if target_type == 'owner' else None

    interaction = Interaction(
        type=call_type,
        target_type=target_type,
        target_id=target_id,
        client_id=client_id,
        owner_id=owner_id,
        property_id=int(property_id) if property_id else None,
        agent_id=int(agent_id) if agent_id else None,
        summary=summary,
        outcome=outcome,
        next_followup_date=next_followup
    )
    db.session.add(interaction)
    
    # Auto update client lead status if needed
    if target_type == 'client' and outcome == 'requested_visit':
        client = Client.query.get(target_id)
        if client and client.lead_status in ['new', 'contacted']:
            client.lead_status = 'visiting'

    db.session.commit()
    flash('گزارش تماس و پیگیری با موفقیت ثبت شد.', 'success')
    
    referrer = request.referrer or url_for('crm.calls')
    return redirect(referrer)

@crm_bp.route('/visits')
def visits():
    visits_list = Visit.query.order_by(Visit.scheduled_time.desc()).all()
    clients = Client.query.all()
    properties = Property.query.filter(Property.status.notin_(['sold', 'archived'])).all()
    agents = Agent.query.filter_by(is_active=True).all()
    
    return render_template(
        'crm/visits.html',
        visits=visits_list,
        clients=clients,
        properties=properties,
        agents=agents
    )

@crm_bp.route('/visits/new', methods=['POST'])
def schedule_visit():
    property_id = int(request.form.get('property_id'))
    client_id = int(request.form.get('client_id'))
    agent_id = request.form.get('agent_id')
    time_str = request.form.get('scheduled_time')
    
    scheduled_time = datetime.now()
    if time_str:
        try:
            scheduled_time = datetime.strptime(time_str, '%Y-%m-%dT%H:%M')
        except Exception:
            pass

    visit = Visit(
        property_id=property_id,
        client_id=client_id,
        agent_id=int(agent_id) if agent_id else None,
        scheduled_time=scheduled_time,
        status='scheduled'
    )
    db.session.add(visit)
    
    # Update client status to visiting
    client = Client.query.get(client_id)
    if client:
        client.lead_status = 'visiting'
        
    db.session.commit()
    flash('هماهنگی بازدید ملک با موفقیت در تقویم کاری ثبت شد.', 'success')
    return redirect(request.referrer or url_for('crm.visits'))

@crm_bp.route('/visits/<int:id>/status', methods=['POST'])
def update_visit_status(id):
    visit = Visit.query.get_or_404(id)
    status = request.form.get('status')
    feedback = request.form.get('feedback')
    readiness = request.form.get('readiness_to_buy')
    
    if status:
        visit.status = status
    if feedback:
        visit.feedback = feedback
    if readiness:
        visit.readiness_to_buy = int(readiness)

    # If completed and readiness is high (4 or 5), advance client to negotiation
    if status == 'completed' and visit.readiness_to_buy >= 4:
        if visit.client:
            visit.client.lead_status = 'negotiating'

    db.session.commit()
    flash('بازخورد و نتیجه بازدید با موفقیت بروزرسانی شد.', 'success')
    return redirect(request.referrer or url_for('crm.visits'))


# =========================================================================
# اندپوینت‌های دستیار هوشمند فروش و CRM تلگرام (Sales Assistant APIs)
# =========================================================================

@crm_bp.route('/api/sales-assistant/onboard', methods=['POST'])
def api_sales_assistant_onboard():
    from services.crm_sales_assistant import CRMSalesAssistantEngine
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    phone = data.get('phone') or data.get('phone_number') or '09120000000'
    name = data.get('name') or data.get('client_name')
    res = CRMSalesAssistantEngine.start_onboarding(phone, name)
    return jsonify(res)

@crm_bp.route('/api/sales-assistant/turn', methods=['POST'])
def api_sales_assistant_turn():
    from services.crm_sales_assistant import CRMSalesAssistantEngine
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    phone = data.get('phone') or data.get('phone_number') or '09120000000'
    message = data.get('message') or data.get('text') or ''
    res = CRMSalesAssistantEngine.process_client_turn(phone, message)
    return jsonify(res)

@crm_bp.route('/api/sales-assistant/feedback', methods=['POST'])
def api_sales_assistant_feedback():
    from services.crm_sales_assistant import CRMSalesAssistantEngine
    data = request.get_json(silent=True) or request.form.to_dict() or {}
    phone = data.get('phone') or data.get('phone_number') or '09120000000'
    feedback = data.get('feedback') or data.get('text') or data.get('message') or ''
    res = CRMSalesAssistantEngine.handle_feedback_and_qualification(phone, feedback)
    return jsonify(res)
