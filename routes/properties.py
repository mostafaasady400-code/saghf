from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database.db import db
from database.models import Property, Owner, Agent, Client, MatchRecord, Interaction
from services.matching_service import MatchingEngine
from services.scoring_service import PropertyScorer

properties_bp = Blueprint('properties', __name__, url_prefix='/properties')

@properties_bp.route('/')
def list_properties():
    now = datetime.utcnow()
    cutoff_7days = now - timedelta(days=7)

    # Basic query params
    deal_type = request.args.get('deal_type')
    district = request.args.get('district')
    status = request.args.get('status')
    source = request.args.get('source')
    search = request.args.get('q')
    lifecycle = request.args.get('lifecycle', 'active') # active (default < 7 days), all, expired (>= 7 days)
    client_id = request.args.get('client_id')

    # Financial & physical filters
    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    min_deposit = request.args.get('min_deposit', type=int)
    max_deposit = request.args.get('max_deposit', type=int)
    min_rent = request.args.get('min_rent', type=int)
    max_rent = request.args.get('max_rent', type=int)
    min_area = request.args.get('min_area', type=int)
    rooms = request.args.get('rooms', type=int)
    has_parking = request.args.get('has_parking')
    has_elevator = request.args.get('has_elevator')
    has_warehouse = request.args.get('has_warehouse')
    has_balcony = request.args.get('has_balcony')

    query = Property.query

    # 1. Lifecycle management: 7-Day filter rule
    if lifecycle == 'active':
        # آگهی‌های فعال فقط فایل‌های زیر ۷ روز و غیر بایگانی شده
        query = query.filter(
            Property.created_at >= cutoff_7days,
            Property.status.notin_(['archived', 'sold', 'needs_followup'])
        )
    elif lifecycle == 'expired':
        # فقط آگهی‌های نیازمند پیگیری و رد شده از مرز ۷ روز
        query = query.filter(
            (Property.created_at < cutoff_7days) | (Property.status == 'needs_followup'),
            Property.status.notin_(['archived', 'sold'])
        )
    elif lifecycle == 'all':
        # همه به جز بایگانی شده‌ها
        query = query.filter(Property.status != 'archived')

    # 0. فیلتر قطعی و بلادرنگ حذف هرگونه آگهی املاکی یا واسطه
    for forbidden in ['املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس']:
        query = query.filter(
            Property.title.notilike(f'%{forbidden}%'),
            Property.description.notilike(f'%{forbidden}%')
        )

    # 2. Filters
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

    # 3. Financial filters
    if min_price:
        query = query.filter(Property.total_price >= min_price)
    if max_price:
        query = query.filter(Property.total_price <= max_price)
    if min_deposit:
        query = query.filter(Property.deposit >= min_deposit)
    if max_deposit:
        query = query.filter(Property.deposit <= max_deposit)
    if min_rent:
        query = query.filter(Property.monthly_rent >= min_rent)
    if max_rent:
        query = query.filter(Property.monthly_rent <= max_rent)

    # 4. Physical & amenities filters
    if min_area:
        query = query.filter(Property.area >= min_area)
    if rooms:
        query = query.filter(Property.rooms >= rooms)
    if has_parking == '1':
        query = query.filter(Property.has_parking == True)
    if has_elevator == '1':
        query = query.filter(Property.has_elevator == True)
    if has_warehouse == '1':
        query = query.filter(Property.has_warehouse == True)
    if has_balcony == '1':
        query = query.filter(Property.has_balcony == True)

    properties = query.order_by(Property.created_at.desc()).all()

    # Active clients for automated client-matching assistant
    active_clients = Client.query.filter(Client.lead_status.notin_(['contract_won', 'lost'])).order_by(Client.created_at.desc()).all()
    selected_client = Client.query.get(client_id) if client_id else None

    # Calculate client match scores if a client is selected
    client_match_scores = {}
    if selected_client:
        for p in properties:
            score, reasons = MatchingEngine.calculate_match(p, selected_client)
            client_match_scores[p.id] = {'score': score, 'reasons': reasons}
        # Sort by match score descending
        properties.sort(key=lambda x: client_match_scores.get(x.id, {}).get('score', 0), reverse=True)

    districts = db.session.query(Property.district).distinct().all()
    districts = [d[0] for d in districts if d[0]]

    # Count expired for quick tab badge
    expired_count = Property.query.filter(
        (Property.created_at < cutoff_7days) | (Property.status == 'needs_followup'),
        Property.status.notin_(['archived', 'sold'])
    ).count()

    # Active sale and rent counts for distinct tabs
    base_active_query = Property.query.filter(
        Property.created_at >= cutoff_7days,
        Property.status.notin_(['archived', 'sold', 'needs_followup'])
    )
    sale_count = base_active_query.filter(Property.deal_type == 'sale').count()
    rent_count = base_active_query.filter(Property.deal_type == 'rent').count()

    return render_template(
        'properties/list.html',
        properties=properties,
        districts=districts,
        active_clients=active_clients,
        selected_client=selected_client,
        client_match_scores=client_match_scores,
        expired_count=expired_count,
        sale_count=sale_count,
        rent_count=rent_count,
        selected_deal_type=deal_type or 'all',
        selected_district=district or 'all',
        selected_status=status or 'all',
        selected_source=source or 'all',
        selected_lifecycle=lifecycle,
        search_query=search or '',
        min_price=min_price,
        max_price=max_price,
        min_deposit=min_deposit,
        max_deposit=max_deposit,
        min_rent=min_rent,
        max_rent=max_rent,
        min_area=min_area,
        rooms=rooms,
        has_parking=has_parking,
        has_elevator=has_elevator,
        has_warehouse=has_warehouse,
        has_balcony=has_balcony
    )

@properties_bp.route('/followup')
def followup():
    """
    بخش اختصاصی «یادآوری پیگیری مجدد»:
    نمایش فایل‌های رد شده از مرز ۷ روز جهت استعلام مجدد وضعیت از مالکین و تعیین تکلیف در دیتابیس
    """
    cutoff_7days = datetime.utcnow() - timedelta(days=7)
    
    # فایل‌های نیازمند پیگیری
    expired_properties = Property.query.filter(
        (Property.created_at < cutoff_7days) | (Property.status == 'needs_followup'),
        Property.status.notin_(['archived', 'sold'])
    ).order_by(Property.created_at.asc()).all()

    agents = Agent.query.filter_by(is_active=True).all()

    return render_template(
        'properties/followup.html',
        properties=expired_properties,
        agents=agents,
        total_count=len(expired_properties)
    )

@properties_bp.route('/<int:id>/reactivate', methods=['POST'])
def reactivate(id):
    """
    تایید موجودی توسط مالک یا کارشناس:
    صفر شدن تایمر ۷ روزه، ثبت در تاریخچه، و بازگشت ملک به لیست فایل‌های فعال
    """
    prop = Property.query.get_or_404(id)
    prop.reactivate()
    
    # ثبت در تعاملات
    interaction = Interaction(
        type='call',
        target_type='owner',
        owner_id=prop.owner_id,
        property_id=prop.id,
        summary="تایید موجودی فایل و تمدید دوره ۷ روزه در سیستم فایلینگ",
        outcome='interested'
    )
    db.session.add(interaction)
    db.session.commit()

    flash(f'فایل «{prop.title}» با موفقیت تایید موجودی شد و برای ۷ روز به لیست فایل‌های فعال اضافه گردید.', 'success')
    return redirect(request.referrer or url_for('properties.followup'))

@properties_bp.route('/<int:id>/archive', methods=['POST'])
def archive(id):
    """
    اعلام عدم موجودی یا واگذاری ملک: بایگانی قطعی از چرخه فایل‌های فعال
    """
    prop = Property.query.get_or_404(id)
    prop.archive(reason='sold')
    
    interaction = Interaction(
        type='call',
        target_type='owner',
        owner_id=prop.owner_id,
        property_id=prop.id,
        summary="اعلام واگذاری / عدم موجودی توسط مالک و بایگانی قطعی فایل",
        outcome='rejected'
    )
    db.session.add(interaction)
    db.session.commit()

    flash(f'فایل «{prop.title}» به عنوان واگذار شده در سیستم بایگانی گردید.', 'info')
    return redirect(request.referrer or url_for('properties.followup'))

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

@properties_bp.route('/<int:id>/data')
def property_data(id):
    """خروجی بلادرنگ جهت نمایش درون‌برنامه‌ای فایل در مودال لوکس سقف"""
    prop = Property.query.get_or_404(id)
    return jsonify({
        'success': True,
        'property': prop.to_dict()
    })

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

        # Forward new property to Telegram channel/group
        try:
            from telegram_bot.notifier import send_property_alert
            send_property_alert(prop)
        except Exception:
            pass
        
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
    title = prop.title
    db.session.delete(prop)
    db.session.commit()
    flash(f'ملک «{title}» با موفقیت از پایگاه داده حذف شد.', 'info')
    return redirect(request.referrer or url_for('properties.list_properties'))

@properties_bp.route('/<int:id>/matches-json')
def get_matches_json(id):
    matches = MatchingEngine.match_property_with_clients(id, threshold=40, limit=12)
    return jsonify({'matches': matches})

@properties_bp.route('/<int:id>/update-phone', methods=['POST'])
def update_phone(id):
    prop = Property.query.get_or_404(id)
    data = request.get_json(silent=True) or request.form
    phone = data.get('phone', '').strip()
    name = data.get('owner_name', '').strip()

    if not phone:
        return jsonify({'success': False, 'message': 'شماره تماس الزامی است.'}), 400

    from crawler.owner_filter import extract_phone_number
    clean_phone = extract_phone_number(phone) or phone

    if prop.owner:
        prop.owner.phone_number = clean_phone
        if name:
            prop.owner.full_name = name
    else:
        owner = Owner.query.filter_by(phone_number=clean_phone).first()
        if not owner:
            owner = Owner(full_name=name or 'مالک مستقیم', phone_number=clean_phone)
            db.session.add(owner)
            db.session.flush()
        prop.owner_id = owner.id

    db.session.commit()
    return jsonify({
        'success': True,
        'phone': clean_phone,
        'owner_name': prop.owner.full_name if prop.owner else name,
        'message': f'شماره تلفن واقعی مالک ({clean_phone}) با موفقیت در سیستم ثبت گردید.'
    })

@properties_bp.route('/<int:id>/fetch-divar-phone', methods=['POST'])
def fetch_divar_phone(id):
    prop = Property.query.get_or_404(id)
    from crawler.divar_session_manager import DivarSessionManager
    token = prop.source_id or ''
    if not token and prop.source_url:
        token = prop.source_url.rstrip('/').split('/')[-1]

    phone = DivarSessionManager.fetch_contact_phone(token)
    if phone:
        if prop.owner:
            prop.owner.phone_number = phone
        else:
            owner = Owner.query.filter_by(phone_number=phone).first()
            if not owner:
                owner = Owner(full_name='مالک استخراج‌شده از دیوار', phone_number=phone)
                db.session.add(owner)
                db.session.flush()
            prop.owner_id = owner.id
        db.session.commit()
        return jsonify({
            'success': True,
            'phone': phone,
            'message': f'شماره واقعی مالک ({phone}) با موفقیت از API دیوار استخراج شد.'
        })

    return jsonify({
        'success': False,
        'is_auth_needed': not DivarSessionManager.is_authenticated(),
        'message': 'جهت استخراج خودکار، لطفاً ابتدا نشست احراز هویت دیوار را با وارد کردن شماره همراه خود فعال نمایید یا از دکمه «دریافت شماره از دیوار» استفاده کنید.'
    })

def _property_to_json(prop):
    """
    سریالایز کردن مشخصات ملک به همراه عکس‌ها، شماره تلفن و فیلدهای لازم جهت رندر کارت در وب‌اپ.
    """
    owner_phone = prop.owner.phone_number if prop.owner else None
    return {
        'id': prop.id,
        'file_code': prop.file_code or f"{prop.id:05d}",
        'title': prop.title or 'ملک بدون عنوان',
        'deal_type': prop.deal_type,
        'district': prop.district or 'تهران',
        'city': prop.city or 'تهران',
        'address': prop.address or '',
        'source': prop.source or 'divar',
        'source_url': prop.source_url or f"/properties/{prop.id}",
        'images': prop.images or [],
        'area': prop.area or 0,
        'rooms': prop.rooms or 0,
        'floor': prop.floor,
        'build_year': prop.build_year or 1400,
        'total_price': prop.total_price,
        'meter_price': prop.meter_price,
        'deposit': prop.deposit,
        'monthly_rent': prop.monthly_rent,
        'has_parking': bool(prop.has_parking),
        'has_elevator': bool(prop.has_elevator),
        'has_warehouse': bool(prop.has_warehouse),
        'has_balcony': bool(prop.has_balcony),
        'created_at': prop.created_at.strftime('%Y-%m-%d %H:%M') if prop.created_at else '',
        'phone_number': owner_phone
    }

def _apply_property_filters(query, params):
    """
    اعمال یکنواخت فیلترهای ملکی روی کوئری SQLAlchemy
    """
    now = datetime.utcnow()
    cutoff_7days = now - timedelta(days=7)

    deal_type = params.get('deal_type')
    district = params.get('district')
    status = params.get('status')
    source = params.get('source')
    search = params.get('q')
    lifecycle = params.get('lifecycle', 'active')

    def _parse_int(val):
        try:
            return int(val) if val not in [None, '', 'null', 'None'] else None
        except (ValueError, TypeError):
            return None

    min_price = _parse_int(params.get('min_price'))
    max_price = _parse_int(params.get('max_price'))
    min_deposit = _parse_int(params.get('min_deposit'))
    max_deposit = _parse_int(params.get('max_deposit'))
    min_rent = _parse_int(params.get('min_rent'))
    max_rent = _parse_int(params.get('max_rent'))
    min_area = _parse_int(params.get('min_area'))
    rooms = _parse_int(params.get('rooms'))
    has_parking = params.get('has_parking')
    has_elevator = params.get('has_elevator')
    has_warehouse = params.get('has_warehouse')
    has_balcony = params.get('has_balcony')

    # Lifecycle filter
    if lifecycle == 'active':
        query = query.filter(
            Property.created_at >= cutoff_7days,
            Property.status.notin_(['archived', 'sold', 'needs_followup'])
        )
    elif lifecycle == 'expired':
        query = query.filter(
            (Property.created_at < cutoff_7days) | (Property.status == 'needs_followup'),
            Property.status.notin_(['archived', 'sold'])
        )
    elif lifecycle == 'all':
        query = query.filter(Property.status != 'archived')

    # فیلتر قطعی حذف آگهی‌های املاک/مشاور
    for forbidden in ['املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوره', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس']:
        query = query.filter(
            Property.title.notilike(f'%{forbidden}%'),
            Property.description.notilike(f'%{forbidden}%')
        )

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

    if min_price:
        query = query.filter(Property.total_price >= min_price)
    if max_price:
        query = query.filter(Property.total_price <= max_price)
    if min_deposit:
        query = query.filter(Property.deposit >= min_deposit)
    if max_deposit:
        query = query.filter(Property.deposit <= max_deposit)
    if min_rent:
        query = query.filter(Property.monthly_rent >= min_rent)
    if max_rent:
        query = query.filter(Property.monthly_rent <= max_rent)
    if min_area:
        query = query.filter(Property.area >= min_area)
    if rooms:
        query = query.filter(Property.rooms >= rooms)
    if str(has_parking) == '1':
        query = query.filter(Property.has_parking == True)
    if str(has_elevator) == '1':
        query = query.filter(Property.has_elevator == True)
    if str(has_warehouse) == '1':
        query = query.filter(Property.has_warehouse == True)
    if str(has_balcony) == '1':
        query = query.filter(Property.has_balcony == True)

    return query

@properties_bp.route('/api/on-demand-search', methods=['GET', 'POST'])
def api_on_demand_search():
    """
    استخراج درجا (On-Demand Scrape):
    ابتدا در دیتابیس لوکال سرچ می‌کند؛ اگر موردی نبود (یا force_crawl باشد)، بلافاصله
    کراولر هدفمند را با پارامترهای همان فیلتر فعال می‌کند.
    """
    from crawler.crawler_manager import crawler_manager

    data = request.get_json(silent=True) if request.is_json else request.args.to_dict()
    if not data:
        data = request.form.to_dict()

    query = Property.query
    query = _apply_property_filters(query, data)
    properties = query.order_by(Property.created_at.desc()).limit(30).all()

    force_crawl = str(data.get('force_crawl', '0')).lower() in ['1', 'true', 'yes']
    deal_type = data.get('deal_type', 'all')
    district = data.get('district')
    district_clean = district if (district and district != 'all') else None

    crawler_status = crawler_manager.get_status()
    crawler_running = crawler_status.get('is_running', False)

    # اگر فایلی مطابق فیلتر یافت نشد (یا کاربر درخواست استخراج زنده داده باشد)، فوراً کراولر را استارت بزن
    if (len(properties) == 0 or force_crawl) and not crawler_running:
        categories = []
        if deal_type == 'sale':
            categories = ['buy-apartment']
        elif deal_type == 'rent':
            categories = ['rent-apartment']
        else:
            categories = ['buy-apartment', 'rent-apartment']

        def _p_int(k):
            try:
                return int(data.get(k)) if data.get(k) not in [None, '', 'null'] else None
            except Exception:
                return None

        crawler_manager.start_crawl_task(
            sources=['divar', 'sheypoor'],
            categories=categories,
            limit_per_cat=6,
            city='tehran',
            district=district_clean,
            districts=[district_clean] if district_clean else None,
            min_price=_p_int('min_price'),
            max_price=_p_int('max_price'),
            min_deposit=_p_int('min_deposit'),
            max_deposit=_p_int('max_deposit'),
            min_rent=_p_int('min_rent'),
            max_rent=_p_int('max_rent'),
            min_area=_p_int('min_area')
        )
        crawler_running = True

    return jsonify({
        'status': 'crawling' if (len(properties) == 0 or crawler_running) else 'found',
        'crawler_running': crawler_running,
        'count': len(properties),
        'items': [_property_to_json(p) for p in properties],
        'message': 'در حال استخراج جدیدترین آگهی‌ها از دیوار و شیپور با فیلترهای انتخابی...' if (len(properties) == 0 or crawler_running) else 'فایل‌های منطبق یافت شد.'
    })

@properties_bp.route('/api/poll-live', methods=['GET'])
def api_poll_live():
    """
    پولینگ بلادرنگ جهت دریافت مرحله‌به‌مرحله آگهی‌های جدید ثبت‌شده مطابق فیلتر
    """
    from crawler.crawler_manager import crawler_manager

    data = request.args.to_dict()
    query = Property.query
    query = _apply_property_filters(query, data)
    properties = query.order_by(Property.created_at.desc()).limit(30).all()

    crawler_status = crawler_manager.get_status()
    crawler_running = crawler_status.get('is_running', False)

    return jsonify({
        'status': 'ok',
        'crawler_running': crawler_running,
        'count': len(properties),
        'items': [_property_to_json(p) for p in properties]
    })

