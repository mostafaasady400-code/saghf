from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from crawler.crawler_manager import crawler_manager
from database.models import Property

crawler_bp = Blueprint('crawler', __name__, url_prefix='/crawler')

@crawler_bp.route('/')
def index():
    return redirect(url_for('crawler.live_monitor'))

@crawler_bp.route('/live')
def live_monitor():
    sale_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'sale'
    ).order_by(Property.created_at.desc()).limit(30).all()

    rent_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'rent'
    ).order_by(Property.created_at.desc()).limit(30).all()

    crawled_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor'])
    ).order_by(Property.created_at.desc()).limit(20).all()

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

@crawler_bp.route('/start', methods=['POST'])
def start_crawl():
    data = request.get_json(silent=True) or request.form
    sources = data.getlist('sources') if hasattr(data, 'getlist') else data.get('sources', ['divar', 'sheypoor'])
    categories = data.getlist('categories') if hasattr(data, 'getlist') else data.get('categories', ['buy-apartment', 'rent-apartment'])
    limit = int(data.get('limit', 8))
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

    success, msg = crawler_manager.start_crawl_task(
        sources=sources if isinstance(sources, list) else [sources],
        categories=categories if isinstance(categories, list) else [categories],
        limit_per_cat=limit,
        city=city,
        district=district,
        districts=districts,
        min_price=min_price,
        max_price=max_price,
        min_deposit=min_deposit,
        max_deposit=max_deposit,
        min_rent=min_rent,
        max_rent=max_rent,
        min_area=min_area,
        max_area=max_area,
        min_year=min_year
    )
    return jsonify({'success': success, 'message': msg})

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
    data = request.get_json(silent=True) or {}
    target_district = data.get('district', 'منطقه ۵')
    interval = int(data.get('interval', 75))
    success = divar_monitor.start(
        app=current_app._get_current_object(),
        target_district=target_district,
        interval_seconds=interval
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
