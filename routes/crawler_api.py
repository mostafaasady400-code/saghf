from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from crawler.crawler_manager import crawler_manager
from database.models import Property

crawler_bp = Blueprint('crawler', __name__, url_prefix='/crawler')

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

@crawler_bp.route('/start', methods=['POST'])
def start_crawl():
    data = request.get_json(silent=True) or request.form
    sources = data.getlist('sources') if hasattr(data, 'getlist') else data.get('sources', ['divar', 'sheypoor'])
    categories = data.getlist('categories') if hasattr(data, 'getlist') else data.get('categories', ['buy-apartment', 'rent-apartment'])
    limit = int(data.get('limit', 8))
    city = data.get('city', 'tehran').strip() or 'tehran'
    district = data.get('district', '').strip() or None

    success, msg = crawler_manager.start_crawl_task(
        sources=sources if isinstance(sources, list) else [sources],
        categories=categories if isinstance(categories, list) else [categories],
        limit_per_cat=limit,
        city=city,
        district=district
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

        dedup_engine.seen_ids.clear()
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

