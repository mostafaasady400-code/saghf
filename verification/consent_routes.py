from pathlib import Path
from datetime import datetime, timezone
import sqlite3
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from verification.owner_consent import OwnerConsentStore
from verification.team_review import TeamReviewStore, listing_fingerprint
from verification.workflow import token_from_url

consent_bp = Blueprint('owner_consent', __name__, url_prefix='/owner-consent')
LABELS = {'awaiting_owner_consent': 'در انتظار رضایت واقعی مالک', 'support_recorded': 'ثبت پشتیبانی؛ در انتظار مدیریت',
          'management_approved': 'رضایت مستند تأییدشده توسط مدیریت', 'rejected': 'ردشده',
          'withdrawn': 'رضایت لغو شده', 'needs_renewal': 'نیازمند دریافت و بررسی مجدد رضایت'}


@consent_bp.before_request
def authorized_staff():
    from database.db import db
    from database.models import User
    uid = session.get('user_id')
    if type(uid) is not int:
        return redirect(url_for('auth.login'))
    user = db.session.get(User, uid)
    if not user or not user.is_active or user.role not in {'agent', 'admin', 'super_admin'}:
        abort(403)
    g.consent_actor = user.id
    g.consent_manager = user.role in {'admin', 'super_admin'}


@consent_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@consent_bp.get('/')
def index():
    from database.models import AccessibleListing
    page = request.args.get('page', 1, type=int)
    if page < 1:
        abort(400)
    pagination = AccessibleListing.query.order_by(AccessibleListing.last_seen_at.desc(), AccessibleListing.id.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template('verification/consent.html', listing=None, pagination=pagination)


@consent_bp.route('/<int:listing_id>', methods=['GET', 'POST'])
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
    root = Path(current_app.instance_path)
    consent_path = current_app.config.get('OWNER_CONSENT_DB') or str(root / 'owner-consent.sqlite3')
    ownership_path = current_app.config.get('TEAM_REVIEW_DB') or str(root / 'team-ownership-review.sqlite3')
    store, ownership = None, None
    error, code = None, 200
    values = {k: request.form.get(k, '') for k in ('action', 'method')}
    try:
        store = OwnerConsentStore(consent_path)
        ownership = TeamReviewStore(ownership_path)
        ownership_valid = ownership.status(listing_id, fingerprint) == 'team_approved'
        if request.method == 'POST':
            action = request.form.get('action')
            if action in {'management_approved', 'rejected'} and not g.consent_manager:
                abort(403)
            try:
                if request.form.get('fingerprint') != fingerprint:
                    raise ValueError('listing_changed')
                if action == 'management_approved' and not ownership_valid:
                    raise ValueError('ownership_required')
                store.record(listing_id, fingerprint, g.consent_actor, action=action,
                             method=request.form.get('method'), evidence=request.form.get('evidence'),
                             previous_id=int(request.form.get('previous_id', '-1')),
                             acknowledged=request.form.get('acknowledged') == 'yes')
            except (ValueError, TypeError) as exc:
                messages = {'consent_conflict': 'پرونده تغییر کرده است؛ صفحه را تازه کنید.',
                    'listing_changed': 'مشخصات آگهی تغییر کرده است؛ دوباره بررسی کنید.',
                    'separate_manager_required': 'مدیر تأییدکننده باید با ثبت‌کنندهٔ رضایت متفاوت باشد.',
                    'ownership_required': 'ابتدا بررسی معتبر مالکیت توسط تیم لازم است.',
                    'actual_consent_required': 'رضایت معتبرِ ثبت‌شده توسط پشتیبانی وجود ندارد.',
                    'consent_missing': 'پروندهٔ رضایت برای این اقدام وجود ندارد.'}
                error = messages.get(str(exc), 'اقدام، روش، مرجع رضایت و تأیید انجام بررسی را کامل کنید.')
                code = 409 if str(exc) in {'consent_conflict', 'listing_changed'} else 400
            else:
                return redirect(url_for('owner_consent.review', listing_id=listing_id, saved='1'), code=303)
        latest = store.latest(listing_id)
        history = store.history(listing_id)
        for event in history:
            event['label'] = LABELS[event['action']]
            event['time'] = datetime.fromtimestamp(event['observed_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        state = store.status(listing_id, fingerprint)
        effective = state == 'management_approved' and ownership_valid
        return render_template('verification/consent.html', listing=listing, fingerprint=fingerprint,
            latest=latest, state_label=LABELS[state], ownership_valid=ownership_valid,
            effective=effective, manager=g.consent_manager, actor=g.consent_actor,
            error=error, values=values, history=history, saved=request.args.get('saved') == '1'), code
    except sqlite3.Error:
        abort(503, description='ذخیره‌سازی بررسی موقتاً در دسترس نیست؛ چیزی تأیید نشد.')
    finally:
        if store: store.close()
        if ownership: ownership.close()


def install_owner_consent(app):
    if 'owner_consent' not in app.blueprints:
        app.register_blueprint(consent_bp)
