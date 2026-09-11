from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from database.db import db
from database.models import MatchRecord, Property, Client
from services.matching_service import MatchingEngine

matching_bp = Blueprint('matching', __name__, url_prefix='/matching')

@matching_bp.route('/')
def console():
    min_score = int(request.args.get('min_score', 65))
    deal_type = request.args.get('deal_type', 'all')
    
    query = MatchRecord.query.filter(MatchRecord.match_score >= min_score)
    
    if deal_type != 'all':
        query = query.join(Property).filter(Property.deal_type == deal_type)
        
    records = query.order_by(MatchRecord.match_score.desc()).limit(30).all()

    return render_template(
        'matching/console.html',
        records=records,
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
