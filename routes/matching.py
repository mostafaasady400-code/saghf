from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database.db import db
from database.models import MatchRecord, Property, Client
from services.matching_service import MatchingEngine

matching_bp = Blueprint('matching', __name__, url_prefix='/matching')

@matching_bp.route('/')
@matching_bp.route('/console')
def console():
    min_score = int(request.args.get('min_score', 55))
    deal_type = request.args.get('deal_type', 'all')
    
    base_query = MatchRecord.query.join(Client).filter(MatchRecord.match_score >= min_score)
    
    total_count = base_query.count()
    sale_count = base_query.filter(Client.preferred_deal_type == 'sale').count()
    rent_count = base_query.filter(Client.preferred_deal_type == 'rent').count()
    
    if deal_type == 'sale':
        sale_records = base_query.filter(Client.preferred_deal_type == 'sale').order_by(MatchRecord.match_score.desc()).limit(50).all()
        rent_records = []
        records = sale_records
    elif deal_type == 'rent':
        rent_records = base_query.filter(Client.preferred_deal_type == 'rent').order_by(MatchRecord.match_score.desc()).limit(50).all()
        sale_records = []
        records = rent_records
    else:
        sale_records = base_query.filter(Client.preferred_deal_type == 'sale').order_by(MatchRecord.match_score.desc()).limit(30).all()
        rent_records = base_query.filter(Client.preferred_deal_type == 'rent').order_by(MatchRecord.match_score.desc()).limit(30).all()
        records = base_query.order_by(MatchRecord.match_score.desc()).limit(50).all()

    return render_template(
        'matching/console.html',
        records=records,
        sale_records=sale_records,
        rent_records=rent_records,
        total_count=total_count,
        sale_count=sale_count,
        rent_count=rent_count,
        min_score=min_score,
        deal_type=deal_type
    )

@matching_bp.route('/refresh', methods=['POST'])
def refresh_all():
    count = MatchingEngine.refresh_matches_for_all(threshold=60)
    flash(f'تطبیق سراسری با موفقیت بروزرسانی شد. {count} فرصت معامله شناسایی گردید.', 'success')
    return redirect(url_for('matching.console'))

@matching_bp.route('/<int:id>/suggest', methods=['POST'])
def mark_suggested(id):
    record = MatchRecord.query.get_or_404(id)
    record.is_suggested = True
    db.session.commit()
    return jsonify({'success': True, 'message': 'ملک با موفقیت در لیست پیشنهادات مشتری نشانه‌گذاری شد.'})
