from pathlib import Path
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from verification.team_review import TeamReviewStore, listing_fingerprint
from verification.workflow import token_from_url

team_review_bp = Blueprint('team_review', __name__, url_prefix='/ownership-review')
LABELS = {'pending_review': 'در انتظار بررسی انسانی', 'team_approved': 'تأیید مالکیت توسط تیم سقف',
          'rejected': 'ردشده توسط تیم', 'needs_review': 'نیازمند بررسی مجدد'}


@team_review_bp.before_request
def require_admin():
    from database.db import db
    from database.models import User
    uid = session.get('user_id')
    if type(uid) is not int:
        return redirect(url_for('auth.login'))
    user = db.session.get(User, uid)
    if user is None or not user.is_active or user.role not in {'admin', 'super_admin'}:
        abort(403)
    g.team_reviewer_id = user.id


@team_review_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@team_review_bp.get('/')
def index():
    from database.models import AccessibleListing
    listings = AccessibleListing.query.order_by(AccessibleListing.last_seen_at.desc()).limit(50).all()
    return render_template('verification/team_review.html', listings=listings, listing=None)


@team_review_bp.route('/<int:listing_id>', methods=['GET', 'POST'])
def review(listing_id):
    from database.db import db
    from database.models import AccessibleListing
    listing = db.session.get(AccessibleListing, listing_id)
    if listing is None:
        abort(404)
    try:
        token_from_url(listing.source_url)
        fingerprint = listing_fingerprint(listing)
    except ValueError:
        abort(400)
    path = current_app.config.get('TEAM_REVIEW_DB') or str(Path(current_app.instance_path) / 'team-ownership-review.sqlite3')
    error, code = None, 200
    try:
        store = TeamReviewStore(path)
    except Exception:
        abort(503)
    try:
        if request.method == 'POST':
            try:
                if request.form.get('fingerprint') != fingerprint:
                    raise ValueError('listing_changed')
                store.record(listing.id, fingerprint, g.team_reviewer_id,
                    decision=request.form.get('decision'), method=request.form.get('method'),
                    evidence=request.form.get('evidence'), previous_id=int(request.form.get('previous_id', '-1')),
                    acknowledged=request.form.get('acknowledged') == 'yes')
            except (ValueError, TypeError) as exc:
                messages = {'review_conflict': 'بازبین دیگری نتیجه را تغییر داده؛ صفحه را تازه کنید.',
                    'listing_changed': 'مشخصات آگهی تغییر کرده؛ دوباره بررسی کنید.',
                    'approval_needs_evidence': 'با شواهد ناکافی نمی‌توان مالکیت را تأیید کرد.'}
                error = messages.get(str(exc), 'نتیجه، روش، مرجع بررسی و تأیید انجام بررسی را کامل کنید.')
                code = 409 if str(exc) in {'review_conflict', 'listing_changed'} else 400
            else:
                return redirect(url_for('team_review.review', listing_id=listing.id, saved='1'), code=303)
        latest = store.latest(listing.id)
        return render_template('verification/team_review.html', listing=listing, listings=[],
            fingerprint=fingerprint, latest=latest, state_label=LABELS[store.status(listing.id, fingerprint)],
            error=error, saved=request.args.get('saved') == '1'), code
    finally:
        store.close()


def install_team_review(app):
    from verification.consent_routes import install_owner_consent
    install_owner_consent(app)
    if 'team_review' not in app.blueprints:
        app.register_blueprint(team_review_bp)
