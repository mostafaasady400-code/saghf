from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database.db import db
from database.models import Client, Agent, Interaction, Visit
from services.matching_service import MatchingEngine

clients_bp = Blueprint('clients', __name__, url_prefix='/clients')

@clients_bp.route('/')
def list_clients():
    lead_status = request.args.get('status')
    deal_type = request.args.get('deal_type')
    search = request.args.get('q')

    query = Client.query
    if lead_status and lead_status != 'all':
        query = query.filter(Client.lead_status == lead_status)
    if deal_type and deal_type != 'all':
        query = query.filter(Client.preferred_deal_type == deal_type)
    if search:
        query = query.filter(Client.full_name.contains(search) | Client.phone_number.contains(search) | Client.notes.contains(search))

    clients = query.order_by(Client.created_at.desc()).all()
    agents = Agent.query.filter_by(is_active=True).all()

    return render_template(
        'clients/list.html',
        clients=clients,
        agents=agents,
        selected_status=lead_status or 'all',
        selected_deal_type=deal_type or 'all',
        search_query=search or ''
    )

@clients_bp.route('/<int:id>')
def detail(id):
    client = Client.query.get_or_404(id)
    agents = Agent.query.filter_by(is_active=True).all()
    
    # Calculate live matching properties for this client
    matching_props = MatchingEngine.match_client_with_properties(client.id, threshold=50, limit=12)
    
    # Interactions & Visits history
    interactions = Interaction.query.filter_by(target_type='client', target_id=client.id).order_by(Interaction.created_at.desc()).all()
    visits = Visit.query.filter_by(client_id=client.id).order_by(Visit.scheduled_time.desc()).all()

    return render_template(
        'clients/detail.html',
        client=client,
        agents=agents,
        matching_props=matching_props,
        interactions=interactions,
        visits=visits
    )

@clients_bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        deal_type = request.form.get('preferred_deal_type', 'sale')
        districts_raw = request.form.get('preferred_districts', '')
        districts = [d.strip() for d in districts_raw.split(',') if d.strip()]

        client = Client(
            full_name=request.form.get('full_name'),
            phone_number=request.form.get('phone_number'),
            preferred_deal_type=deal_type,
            min_budget=int(request.form.get('min_budget', 0) or 0),
            max_budget=int(request.form.get('max_budget', 0) or 0),
            max_deposit=int(request.form.get('max_deposit', 0) or 0),
            max_rent=int(request.form.get('max_rent', 0) or 0),
            min_area=int(request.form.get('min_area', 0) or 0),
            max_area=int(request.form.get('max_area', 0) or 0),
            min_rooms=int(request.form.get('min_rooms', 1) or 1),
            must_have_parking='must_have_parking' in request.form,
            must_have_elevator='must_have_elevator' in request.form,
            must_have_warehouse='must_have_warehouse' in request.form,
            urgency=request.form.get('urgency', 'normal'),
            lead_status=request.form.get('lead_status', 'new'),
            notes=request.form.get('notes'),
            assigned_agent_id=request.form.get('assigned_agent_id') or None
        )
        client.preferred_districts = districts

        db.session.add(client)
        db.session.commit()

        flash('متقاضی جدید با موفقیت ثبت شد و پیشنهادات ملکی آماده است.', 'success')
        return redirect(url_for('clients.detail', id=client.id))

    agents = Agent.query.filter_by(is_active=True).all()
    return render_template('clients/form.html', client=None, agents=agents)

@clients_bp.route('/<int:id>/status', methods=['POST'])
def update_status(id):
    client = Client.query.get_or_404(id)
    new_status = request.form.get('status')
    if new_status:
        client.lead_status = new_status
        db.session.commit()
        flash(f'وضعیت متقاضی به {new_status} تغییر یافت.', 'success')
    return redirect(url_for('clients.detail', id=client.id))

@clients_bp.route('/<int:id>/matches-json')
def get_matches_json(id):
    matches = MatchingEngine.match_client_with_properties(id, threshold=40, limit=12)
    return jsonify({'matches': matches})
