from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database.db import db
from database.models import Property, Owner, Agent, Client, MatchRecord
from services.matching_service import MatchingEngine
from services.scoring_service import PropertyScorer

properties_bp = Blueprint('properties', __name__, url_prefix='/properties')

@properties_bp.route('/')
def list_properties():
    deal_type = request.args.get('deal_type')
    district = request.args.get('district')
    status = request.args.get('status')
    source = request.args.get('source')
    search = request.args.get('q')

    query = Property.query

    if deal_type and deal_type != 'all':
        query = query.filter(Property.deal_type == deal_type)
    if district and district != 'all':
        query = query.filter(Property.district.contains(district))
    if status and status != 'all':
        query = query.filter(Property.status == status)
    if source and source != 'all':
        query = query.filter(Property.source == source)
    if search:
        query = query.filter(Property.title.contains(search) | Property.district.contains(search) | Property.description.contains(search))

    properties = query.order_by(Property.created_at.desc()).all()
    districts = db.session.query(Property.district).distinct().all()
    districts = [d[0] for d in districts if d[0]]

    return render_template(
        'properties/list.html',
        properties=properties,
        districts=districts,
        selected_deal_type=deal_type or 'all',
        selected_district=district or 'all',
        selected_status=status or 'all',
        selected_source=source or 'all',
        search_query=search or ''
    )

@properties_bp.route('/<int:id>')
def detail(id):
    prop = Property.query.get_or_404(id)
    agents = Agent.query.filter_by(is_active=True).all()
    
    # Calculate live matches for this property
    matches = MatchingEngine.match_property_with_clients(prop.id, threshold=50, limit=10)
    
    return render_template(
        'properties/detail.html',
        prop=prop,
        agents=agents,
        matches=matches
    )

@properties_bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        # 1. Owner creation or selection
        owner_name = request.form.get('owner_name')
        owner_phone = request.form.get('owner_phone')
        owner_notes = request.form.get('owner_notes')
        
        owner = None
        if owner_phone:
            owner = Owner.query.filter_by(phone_number=owner_phone).first()
            if not owner:
                owner = Owner(
                    full_name=owner_name or 'مالک جدید',
                    phone_number=owner_phone,
                    urgency=request.form.get('owner_urgency', 'medium'),
                    flexibility=request.form.get('owner_flexibility', 'معمولی'),
                    notes=owner_notes
                )
                db.session.add(owner)
                db.session.flush()

        # 2. Property creation
        deal_type = request.form.get('deal_type', 'sale')
        total_price = int(request.form.get('total_price', 0) or 0)
        deposit = int(request.form.get('deposit', 0) or 0)
        monthly_rent = int(request.form.get('monthly_rent', 0) or 0)
        area = int(request.form.get('area', 80) or 80)
        meter_price = int(total_price / area) if area > 0 and total_price > 0 else 0

        prop = Property(
            source='direct_owner',
            title=request.form.get('title'),
            deal_type=deal_type,
            property_type=request.form.get('property_type', 'apartment'),
            city=request.form.get('city', 'تهران'),
            district=request.form.get('district', 'سعادت آباد'),
            address=request.form.get('address'),
            total_price=total_price,
            meter_price=meter_price,
            deposit=deposit,
            monthly_rent=monthly_rent,
            area=area,
            rooms=int(request.form.get('rooms', 2) or 2),
            floor=int(request.form.get('floor', 1) or 1),
            build_year=int(request.form.get('build_year', 1400) or 1400),
            has_elevator='has_elevator' in request.form,
            has_parking='has_parking' in request.form,
            has_warehouse='has_warehouse' in request.form,
            has_balcony='has_balcony' in request.form,
            description=request.form.get('description'),
            status='verified',
            owner_id=owner.id if owner else None,
            assigned_agent_id=request.form.get('assigned_agent_id') or None
        )
        
        # Calculate quality score
        prop.score = PropertyScorer.calculate_score(prop)
        
        db.session.add(prop)
        db.session.commit()
        
        flash('ملک جدید با موفقیت در پایگاه فایلینگ ثبت شد.', 'success')
        return redirect(url_for('properties.detail', id=prop.id))

    agents = Agent.query.filter_by(is_active=True).all()
    return render_template('properties/form.html', prop=None, agents=agents)

@properties_bp.route('/<int:id>/verify', methods=['POST'])
def verify(id):
    prop = Property.query.get_or_404(id)
    prop.status = 'verified'
    
    # Update owner info if submitted via quick modal
    owner_name = request.form.get('owner_name')
    owner_phone = request.form.get('owner_phone')
    if owner_phone:
        owner = Owner.query.filter_by(phone_number=owner_phone).first()
        if not owner:
            owner = Owner(full_name=owner_name or 'مالک تأیید شده', phone_number=owner_phone)
            db.session.add(owner)
            db.session.flush()
        prop.owner_id = owner.id

    db.session.commit()
    flash(f'فایل «{prop.title}» به لیست فایل‌های رسمی و کارشناسی‌شده سقف اضافه شد.', 'success')
    return redirect(url_for('properties.detail', id=prop.id))

@properties_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    prop = Property.query.get_or_404(id)
    db.session.delete(prop)
    db.session.commit()
    flash('ملک مورد نظر با موفقیت حذف شد.', 'info')
    return redirect(url_for('properties.list_properties'))

@properties_bp.route('/<int:id>/matches-json')
def get_matches_json(id):
    matches = MatchingEngine.match_property_with_clients(id, threshold=40, limit=12)
    return jsonify({'matches': matches})
