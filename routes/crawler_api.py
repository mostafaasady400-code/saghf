from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from crawler.crawler_manager import crawler_manager
from database.models import Property

crawler_bp = Blueprint('crawler', __name__, url_prefix='/crawler')

@crawler_bp.route('/live')
def live_monitor():
    crawled_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor'])
    ).order_by(Property.created_at.desc()).limit(20).all()

    return render_template(
        'crawler/live.html',
        crawled_properties=crawled_properties
    )

@crawler_bp.route('/start', methods=['POST'])
def start_crawl():
    data = request.get_json(silent=True) or request.form
    sources = data.getlist('sources') if hasattr(data, 'getlist') else data.get('sources', ['divar', 'sheypoor'])
    categories = data.getlist('categories') if hasattr(data, 'getlist') else data.get('categories', ['buy-apartment', 'rent-apartment'])
    limit = int(data.get('limit', 8))

    success, msg = crawler_manager.start_crawl_task(
        sources=sources if isinstance(sources, list) else [sources],
        categories=categories if isinstance(categories, list) else [categories],
        limit_per_cat=limit
    )
    return jsonify({'success': success, 'message': msg})

@crawler_bp.route('/status')
def get_status():
    status = crawler_manager.get_status()
    # Also fetch recent properties count
    total_crawled_in_db = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).count()
    status['stats']['total_in_db'] = total_crawled_in_db
    return jsonify(status)
