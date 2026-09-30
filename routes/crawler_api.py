from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from crawler.crawler_manager import crawler_manager
from database.models import Property, SearchRun

crawler_bp = Blueprint('crawler', __name__, url_prefix='/crawler')

@crawler_bp.route('/')
def index():
    return redirect(url_for('crawler.live_monitor'))

@crawler_bp.route('/live')
def live_monitor():
    # نمایش همه آگهی‌های استخراج‌شده با اولویت «مالک هستم» و ترتیب جدیدترین
    sale_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'sale'
    ).order_by(
        Property.is_personal_owner.desc(),
        Property.score.desc(),
        Property.created_at.desc()
    ).all()

    rent_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'rent'
    ).order_by(
        Property.is_personal_owner.desc(),
        Property.score.desc(),
        Property.created_at.desc()
    ).all()

    crawled_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor'])
    ).order_by(Property.created_at.desc()).all()

    return render_template(
        'crawler/live.html',
        sale_properties=sale_properties,
        rent_properties=rent_properties,
        crawled_properties=crawled_properties
    )

@crawler_bp.route('/districts', methods=['GET'])
def get_districts():
    from data.tehran_districts import TEHRAN_REGIONS
    region = request.args.get('region')
    if region and str(region) in TEHRAN_REGIONS:
        return jsonify({
            'region': region,
            'data': TEHRAN_REGIONS[str(region)]
        })
    return jsonify({
        'regions': TEHRAN_REGIONS
    })


def _normalize_accessible_criteria(raw):
    """Map assistant/API values to strict nullable crawler criteria."""
    allowed = {
        'city', 'districts', 'deal_type', 'property_type', 'min_area', 'max_area',
        'rooms', 'min_price', 'max_price', 'min_deposit', 'max_deposit',
        'min_rent', 'max_rent', 'has_parking', 'has_elevator', 'has_warehouse',
        'has_balcony', 'window_hours',
    }
    result = {key: raw.get(key) for key in allowed if key in raw}
    districts = result.get('districts') or raw.get('district') or []
    if isinstance(districts, str):
        districts = [item.strip() for item in districts.split(',') if item.strip()]
    result['districts'] = districts
    result['city'] = result.get('city') or 'tehran'
    if result.get('city') == 'تهران':
        result['city'] = 'tehran'
    if result.get('property_type') in (None, 'residential'):
        result['property_type'] = 'apartment'
    for key in (
        'min_area', 'max_area', 'rooms', 'min_price', 'max_price',
        'min_deposit', 'max_deposit', 'min_rent', 'max_rent', 'window_hours',
    ):
        if result.get(key) in ('', 0, '0'):
            result[key] = None if key != 'window_hours' else 24
    result['window_hours'] = max(1, min(168, int(result.get('window_hours') or 24)))
    return result


@crawler_bp.route('/search-runs', methods=['POST'])
def create_search_run():
    """Start a finite, resumable and auditable accessible-source search."""
    from services.nlp_extractor import PropertyLeadNLPExtractor
    from services.search_run_service import SearchRunService

    data = request.get_json(silent=True) or request.form.to_dict(flat=True)
    query_text = str(data.get('query') or data.get('query_text') or '').strip()
    supplied = data.get('criteria') if isinstance(data.get('criteria'), dict) else {}
    extracted = PropertyLeadNLPExtractor.extract_criteria(query_text) if query_text else {}
    extracted.update(supplied)
    # Explicit top-level fields win over NLP output.
    extracted.update({key: value for key, value in data.items() if key not in {'query', 'query_text', 'criteria', 'start'}})
    criteria = _normalize_accessible_criteria(extracted)
    if criteria.get('deal_type') not in {'sale', 'rent'}:
        return jsonify({
            'success': False,
            'error': 'clarification_required',
            'question': 'قصد خرید دارید یا رهن و اجاره؟',
            'criteria': criteria,
        }), 400

    try:
        run = SearchRunService.create_run(criteria, query_text=query_text)
        should_start = str(data.get('start', 'true')).lower() not in {'false', '0', 'no'}
        if should_start:
            runtime = max(10, min(900, int(data.get('max_runtime_seconds') or 180)))
            SearchRunService.execute_async(current_app._get_current_object(), run.run_id, runtime)
        return jsonify({
            'success': True,
            'run': run.to_dict(),
            'status_url': url_for('crawler.search_run_status', run_id=run.run_id),
            'results_url': url_for('crawler.search_run_view', run_id=run.run_id),
        }), 202 if should_start else 201
    except (TypeError, ValueError) as exc:
        return jsonify({'success': False, 'error': 'invalid_criteria', 'message': str(exc)}), 400


@crawler_bp.route('/search-runs/<run_id>', methods=['GET'])
def search_run_status(run_id):
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    return jsonify({'success': True, 'run': run.to_dict()})


@crawler_bp.route('/search-runs/<run_id>/results', methods=['GET'])
def search_run_results(run_id):
    from services.search_run_service import SearchRunService
    try:
        payload = SearchRunService.paginated_results(
            run_id,
            section=request.args.get('section', 'main'),
            page=request.args.get('page', 1, type=int),
            per_page=request.args.get('per_page', 20, type=int),
        )
        return jsonify({'success': True, **payload})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404


@crawler_bp.route('/search-runs/<run_id>/view', methods=['GET'])
def search_run_view(run_id):
    from services.search_run_service import SearchRunService
    section = request.args.get('section', 'main')
    try:
        payload = SearchRunService.paginated_results(
            run_id,
            section=section,
            page=request.args.get('page', 1, type=int),
            per_page=request.args.get('per_page', 20, type=int),
        )
    except ValueError:
        return ('اجرای جست‌وجو پیدا نشد.', 404)
    return render_template('crawler/search_results.html', **payload)


@crawler_bp.route('/search-runs/<run_id>/resume', methods=['POST'])
def resume_search_run(run_id):
    from services.search_run_service import SearchRunService
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    if run.status == 'running':
        return jsonify({'success': True, 'message': 'اجرا هم‌اکنون در حال پردازش است.', 'run': run.to_dict()})
    if not run.can_resume:
        return jsonify({'success': False, 'message': 'این اجرا به پایان واقعی منبع رسیده و قابل ادامه نیست.'}), 409
    runtime = max(10, min(900, int((request.get_json(silent=True) or {}).get('max_runtime_seconds') or 180)))
    SearchRunService.execute_async(current_app._get_current_object(), run_id, runtime)
    return jsonify({'success': True, 'message': 'ادامهٔ پیمایش از checkpoint آغاز شد.'}), 202


@crawler_bp.route('/listings/<int:listing_id>/publisher-correction', methods=['POST'])
def correct_listing_publisher(listing_id):
    from services.search_run_service import SearchRunService
    data = request.get_json(silent=True) or request.form
    try:
        listing = SearchRunService.apply_manual_correction(
            listing_id,
            str(data.get('category') or ''),
            str(data.get('reason') or ''),
            reviewer=str(data.get('reviewer') or '') or None,
        )
        return jsonify({'success': True, 'listing': listing.to_dict()})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

@crawler_bp.route('/search-runs/<run_id>/process-pending', methods=['POST'])
def process_pending_run_classifications(run_id):
    from services.search_run_service import SearchRunService
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    data = request.get_json(silent=True) or {}
    max_items = max(1, min(200, int(data.get('max_items', 50))))
    result = SearchRunService.process_pending_classifications(run_id=run.run_id, max_items=max_items)
    return jsonify({'success': True, 'result': result})


@crawler_bp.route('/start', methods=['POST'])
def start_crawl():
    """Backward-compatible entry point backed by the uncapped resumable core."""
    from services.search_run_service import SearchRunService

    data = request.get_json(silent=True) or request.form
    categories = data.getlist('categories') if hasattr(data, 'getlist') else data.get('categories', ['buy-apartment', 'rent-apartment'])
    city = data.get('city', 'tehran').strip() or 'tehran'
    district = data.get('district', '').strip() or None
    
    # فیلترهای پیشرفته جغرافیایی و مالی
    districts = data.getlist('districts') if hasattr(data, 'getlist') else data.get('districts', [])
    if isinstance(districts, str):
        districts = [d.strip() for d in districts.split(',') if d.strip()]
    if district and district not in districts:
        districts.append(district)

    min_deposit = int(data.get('min_deposit', 0)) if data.get('min_deposit') else None
    max_deposit = int(data.get('max_deposit', 0)) if data.get('max_deposit') else None
    min_rent = int(data.get('min_rent', 0)) if data.get('min_rent') else None
    max_rent = int(data.get('max_rent', 0)) if data.get('max_rent') else None
    min_price = int(data.get('min_price', 0)) if data.get('min_price') else None
    max_price = int(data.get('max_price', 0)) if data.get('max_price') else None
    min_area = int(data.get('min_area', 0)) if data.get('min_area') else None
    max_area = int(data.get('max_area', 0)) if data.get('max_area') else None
    min_year = int(data.get('min_year', 0)) if data.get('min_year') else None

    category_list = categories if isinstance(categories, list) else [categories]
    run_payloads = []
    for category in category_list:
        deal_type = 'rent' if 'rent' in category else 'sale'
        if any(item in category for item in ('commercial', 'office')):
            property_type = 'commercial'
        elif 'villa' in category:
            property_type = 'villa'
        else:
            property_type = 'apartment'
        criteria = _normalize_accessible_criteria({
            'city': city,
            'districts': districts,
            'deal_type': deal_type,
            'property_type': property_type,
            'min_price': min_price,
            'max_price': max_price,
            'min_deposit': min_deposit,
            'max_deposit': max_deposit,
            'min_rent': min_rent,
            'max_rent': max_rent,
            'min_area': min_area,
            'max_area': max_area,
            'window_hours': 24,
        })
        run = SearchRunService.create_run(criteria, query_text='فرم مانیتورینگ کراولر')
        SearchRunService.execute_async(current_app._get_current_object(), run.run_id, 180)
        run_payloads.append({
            'run_id': run.run_id,
            'deal_type': deal_type,
            'results_url': url_for('crawler.search_run_view', run_id=run.run_id),
        })
    return jsonify({
        'success': True,
        'message': 'پیمایش بدون سقف تعداد آغاز شد؛ پیشرفت و پوشش برای ادامه ذخیره می‌شود.',
        'runs': run_payloads,
    }), 202

@crawler_bp.route('/status')
def get_status():
    status = crawler_manager.get_status()
    # Also fetch recent properties count
    total_crawled_in_db = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).count()
    status['stats']['total_in_db'] = total_crawled_in_db
    return jsonify(status)

@crawler_bp.route('/messenger-feed')
def messenger_feed():
    """
    خروجی تمیز و ساختاریافته ویژه پایپ‌لاین پیام‌رسان‌ها (تلگرام، بله، ایتا، واتساپ و پیامک)
    شامل صرفاً آگهی‌های تأییدشده شخصی (مالک مستقیم)
    """
    limit = int(request.args.get('limit', 20))
    deal_type = request.args.get('deal_type')

    query = Property.query.filter_by(is_personal_owner=True)
    if deal_type:
        query = query.filter_by(deal_type=deal_type)

    properties = query.order_by(Property.created_at.desc()).limit(limit).all()
    feed = [p.to_messenger_dict() for p in properties]

    return jsonify({
        'total': len(feed),
        'filter_applied': 'personal_owner_only',
        'items': feed
    })

@crawler_bp.route('/live-items')
def live_items():
    since_id = request.args.get('since_id', 0, type=int)
    new_props = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.id > since_id
    ).order_by(Property.id.asc()).limit(30).all()

    total_sale = Property.query.filter(Property.source.in_(['divar', 'sheypoor']), Property.deal_type == 'sale').count()
    total_rent = Property.query.filter(Property.source.in_(['divar', 'sheypoor']), Property.deal_type == 'rent').count()
    total_all = total_sale + total_rent

    return jsonify({
        'items': [p.to_dict() for p in new_props],
        'latest_id': new_props[-1].id if new_props else since_id,
        'total_sale': total_sale,
        'total_rent': total_rent,
        'total_all': total_all
    })

@crawler_bp.route('/reset-data', methods=['POST'])
def reset_data():
    from database.db import db
    from database.models import Property, Owner, MatchRecord
    from crawler.dedup import dedup_engine

    try:
        crawled_props = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).all()
        prop_ids = [p.id for p in crawled_props]
        if prop_ids:
            MatchRecord.query.filter(MatchRecord.property_id.in_(prop_ids)).delete(synchronize_session=False)
            Property.query.filter(Property.id.in_(prop_ids)).delete(synchronize_session=False)

        dedup_engine.clear()
        dedup_engine.initialize_from_db(Property)
        db.session.commit()

        crawler_manager.stats['total_crawled'] = 0
        crawler_manager.stats['new_saved'] = 0
        crawler_manager.stats['duplicates_skipped'] = 0
        crawler_manager.stats['status'] = 'idle'

        return jsonify({
            'success': True,
            'message': f'اطلاعات {len(prop_ids)} فایل کراول‌شده با موفقیت پاک‌سازی شد.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'خطا در پاک‌سازی داده‌ها: {str(e)}'
        }), 500

@crawler_bp.route('/divar-session/status')
def divar_session_status():
    from crawler.divar_session_manager import DivarSessionManager
    return jsonify({
        'authenticated': DivarSessionManager.is_authenticated(),
        'has_token': bool(DivarSessionManager.get_token())
    })

@crawler_bp.route('/divar-session/request-code', methods=['POST'])
def divar_session_request_code():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    phone = data.get('phone', '')
    result = DivarSessionManager.request_sms_code(phone)
    return jsonify(result)

@crawler_bp.route('/divar-session/confirm', methods=['POST'])
def divar_session_confirm():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    phone = data.get('phone', '')
    code = data.get('code', '')
    result = DivarSessionManager.confirm_sms_code(phone, code)
    return jsonify(result)

@crawler_bp.route('/divar-session/manual-token', methods=['POST'])
def divar_session_manual_token():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    token = data.get('token', '').strip()
    if not token:
        return jsonify({'success': False, 'message': 'توکن نامعتبر است.'}), 400
    success = DivarSessionManager.save_token(token)
    return jsonify({'success': success, 'message': 'توکن دیوار با موفقیت ذخیره شد.' if success else 'خطا در ذخیره توکن.'})

@crawler_bp.route('/divar-openapi/set-key', methods=['POST'])
def divar_openapi_set_key():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    api_key = data.get('api_key', '').strip()
    if not api_key:
        return jsonify({'success': False, 'message': 'کلید API پلتفرم باز نمی‌تواند خالی باشد.'}), 400
    success = DivarSessionManager.save_open_platform_key(api_key)
    return jsonify({'success': success, 'message': 'کلید OpenAPI دیوار با موفقیت ذخیره شد.' if success else 'خطا در ذخیره کلید.'})

# =====================================================================
# Targeted Filter Profiles Management
# =====================================================================

@crawler_bp.route('/profiles', methods=['GET'])
def list_profiles():
    from database.models import FilterProfile
    profiles = FilterProfile.query.order_by(FilterProfile.created_at.desc()).all()
    return jsonify({
        'total': len(profiles),
        'profiles': [p.to_dict() for p in profiles]
    })

@crawler_bp.route('/profiles', methods=['POST'])
def save_profile():
    from database.models import FilterProfile
    from database.db import db
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'نام پروفایل الزامی است.'}), 400

    profile = FilterProfile.query.filter_by(name=name).first()
    if not profile:
        profile = FilterProfile(name=name)
        db.session.add(profile)

    profile.city = data.get('city', 'تهران')
    profile.region = data.get('region', '5')
    districts = data.get('active_districts', ['پونک', 'جنت‌آباد'])
    profile.active_districts = districts if isinstance(districts, list) else [districts]
    profile.deal_type = data.get('deal_type', 'rent')
    profile.min_deposit = int(data.get('min_deposit', 0))
    profile.max_deposit = int(data.get('max_deposit', 0))
    profile.min_rent = int(data.get('min_rent', 0))
    profile.max_rent = int(data.get('max_rent', 0))
    profile.min_price = int(data.get('min_price', 0))
    profile.max_price = int(data.get('max_price', 0))
    profile.min_area = int(data.get('min_area', 0))
    profile.max_area = int(data.get('max_area', 0))
    profile.is_auto_crawl_active = bool(data.get('is_auto_crawl_active', True))

    db.session.commit()
    return jsonify({'success': True, 'profile': profile.to_dict()})

@crawler_bp.route('/profiles/<int:profile_id>/toggle-auto', methods=['POST'])
def toggle_profile_auto(profile_id):
    from database.models import FilterProfile
    from database.db import db
    profile = FilterProfile.query.get_or_404(profile_id)
    profile.is_auto_crawl_active = not profile.is_auto_crawl_active
    db.session.commit()
    return jsonify({
        'success': True,
        'is_auto_crawl_active': profile.is_auto_crawl_active,
        'message': f'وضعیت کراول خودکار برای {profile.name} تغییر یافت.'
    })

@crawler_bp.route('/profiles/<int:profile_id>/run', methods=['POST'])
def run_profile_crawl(profile_id):
    from database.models import FilterProfile
    profile = FilterProfile.query.get_or_404(profile_id)
    cats = ['rent-apartment'] if profile.deal_type == 'rent' else ['buy-apartment']
    districts = profile.active_districts
    district_str = districts[0] if districts else None

    success, msg = crawler_manager.start_crawl_task(
        sources=['divar', 'sheypoor'],
        categories=cats,
        limit_per_cat=10,
        city='tehran',
        district=district_str
    )
    return jsonify({'success': success, 'message': msg, 'profile': profile.name})


# =========================================================================
# پایش زنده و خودکار دیوار (Real-Time Continuous Divar Monitor)
# =========================================================================

@crawler_bp.route('/realtime-monitor/status', methods=['GET'])
def get_realtime_monitor_status():
    from crawler.continuous_monitor import divar_monitor
    status = divar_monitor.get_status()
    return jsonify(status)

@crawler_bp.route('/realtime-monitor/start', methods=['POST'])
def start_realtime_monitor():
    from crawler.continuous_monitor import divar_monitor
    from flask import current_app
    data = request.get_json(silent=True) or request.form or {}
    target_district = data.get('district', 'منطقه ۲ و ۵ تهران')
    
    # استخراج محله‌ها
    districts = data.getlist('districts') if hasattr(data, 'getlist') else data.get('districts', [])
    if isinstance(districts, str):
        districts = [d.strip() for d in districts.split(',') if d.strip()]

    # پارامترهای هدفمند (متراژ، خواب و بازه زمانی ۱۲۰ تا ۱۸۰ ثانیه)
    min_area = int(data.get('min_area')) if data.get('min_area') else None
    max_area = int(data.get('max_area')) if data.get('max_area') else None
    rooms = int(data.get('rooms')) if data.get('rooms') else None
    interval = int(data.get('interval', 150))
    interval = max(60, min(300, interval))

    success = divar_monitor.start(
        app=current_app._get_current_object(),
        target_district=target_district,
        interval_seconds=interval,
        districts=districts if districts else None,
        min_area=min_area,
        max_area=max_area,
        rooms=rooms
    )
    return jsonify({
        'success': success,
        'message': f"پایش زنده دیوار برای {target_district} با موفقیت فعال شد." if success else "خطا در فعال‌سازی پایش زنده.",
        'status': divar_monitor.get_status()
    })

@crawler_bp.route('/realtime-monitor/stop', methods=['POST'])
def stop_realtime_monitor():
    from crawler.continuous_monitor import divar_monitor
    success = divar_monitor.stop()
    return jsonify({
        'success': success,
        'message': "پایش زنده دیوار متوقف شد.",
        'status': divar_monitor.get_status()
    })
