import re
from pathlib import Path

import pytest
from flask import Flask
from flask_wtf.csrf import CSRFProtect

from database.db import db
from database.models import User, AccessibleListing
from verification.team_review import TeamReviewStore, listing_fingerprint
from verification.team_review_routes import install_team_review


@pytest.fixture
def web(tmp_path):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
    app.config.update(TESTING=True, SECRET_KEY='isolated-test-key', SQLALCHEMY_DATABASE_URI='sqlite://',
                      TEAM_REVIEW_DB=str(tmp_path / 'reviews.db'), OWNER_CONSENT_DB=str(tmp_path / 'consent.db'))
    db.init_app(app)
    CSRFProtect(app)
    app.add_url_rule('/auth/login', endpoint='auth.login', view_func=lambda: 'login')
    install_team_review(app)
    with app.app_context():
        User.__table__.create(db.engine)
        AccessibleListing.__table__.create(db.engine)
        db.session.add_all([User(id=1, username='reviewer', full_name='Review', password_hash='test', role='admin'),
                            User(id=2, username='regular', full_name='User', password_hash='test', role='user'),
                            User(id=3, username='inactive', full_name='Inactive', password_hash='test', role='admin', is_active=False),
                            User(id=4, username='manager2', full_name='Manager', password_hash='test', role='admin'),
                            User(id=5, username='support', full_name='Support', password_hash='test', role='agent')])
        db.session.add(AccessibleListing(id=1, source_id='divar_gaHfchN7', source_url='https://divar.ir/v/gaHfchN7',
            title='Test listing', district='Test district', area=150, deal_type='rent'))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['is_admin'] = True  # Must NOT bypass DB role checks.


def form(client):
    response = client.get('/ownership-review/1')
    assert response.status_code == 200
    return {name: re.search(r'name="' + name + r'" value="([^"]*)"', response.text).group(1)
            for name in ('csrf_token', 'fingerprint', 'previous_id')}


def test_anonymous_redirect_and_role_enforced(web):
    client = web.test_client()
    assert client.get('/ownership-review/1').status_code == 302
    for uid in (2, 3, 999):
        login(client, uid)
        assert client.get('/ownership-review/1').status_code == 403


def test_csrf_required(web):
    client = web.test_client(); login(client, 1)
    assert client.post('/ownership-review/1', data={'decision': 'team_approved'}).status_code == 400


def test_review_does_not_grant_consent_or_phone_verification(web):
    client = web.test_client(); login(client, 1)
    values = form(client)
    values.update(decision='team_approved', method='document_review', evidence='OFFICE-123', acknowledged='yes', reviewer_id='999')
    result = client.post('/ownership-review/1', data=values)
    assert result.status_code == 303
    store = TeamReviewStore(web.config['TEAM_REVIEW_DB'])
    try:
        row = store.latest(1)
        assert row['reviewer_id'] == 1 and row['decision'] == 'team_approved'
        assert 'phone' not in row and 'consent_at' not in row
        assert 'OFFICE-123' not in str(row)
    finally: store.close()
    assert client.post('/ownership-review/1', data=values).status_code == 409
    page = client.get('/ownership-review/1')
    assert page.headers['Cache-Control'] == 'no-store, private'
    assert 'تأیید مالکیت توسط تیم سقف' in page.text


def test_evidence_and_actual_acknowledgment_required(web):
    client = web.test_client(); login(client, 1)
    values = form(client)
    values.update(decision='team_approved', method='insufficient_evidence', evidence='OFFICE-123', acknowledged='yes')
    assert client.post('/ownership-review/1', data=values).status_code == 400
    values.update(method='in_person'); values.pop('acknowledged')
    assert client.post('/ownership-review/1', data=values).status_code == 400


def test_changed_listing_rejects_stale_form(web):
    client = web.test_client(); login(client, 1)
    values = form(client)
    with web.app_context():
        db.session.get(AccessibleListing, 1).area = 160
        db.session.commit()
    values.update(decision='team_approved', method='in_person', evidence='OFFICE-123', acknowledged='yes')
    assert client.post('/ownership-review/1', data=values).status_code == 409


def test_expiry_and_append_only_history(tmp_path):
    now = [1000]
    store = TeamReviewStore(tmp_path / 'review.db', clock=lambda: now[0])
    try:
        args = dict(decision='team_approved', method='in_person', evidence='OFFICE-123', previous_id=0, acknowledged=True)
        store.record(1, 'fingerprint', 1, **args)
        assert store.status(1, 'fingerprint') == 'team_approved'
        assert store.status(1, 'changed') == 'needs_review'
        now[0] += 7 * 86400
        assert store.status(1, 'fingerprint') == 'needs_review'
        args.update(decision='rejected', previous_id=store.latest(1)['id'])
        store.record(1, 'fingerprint', 1, **args)
        assert store.status(1, 'fingerprint') == 'rejected'
        assert store.db.execute('SELECT COUNT(*) FROM team_ownership_reviews').fetchone()[0] == 2
    finally: store.close()


def consent_form(client):
    response = client.get('/owner-consent/1')
    assert response.status_code == 200
    return {name: re.search(r'name="' + name + r'" value="([^"]*)"', response.text).group(1)
            for name in ('csrf_token', 'fingerprint', 'previous_id')}


def consent_values(client, action='support_recorded'):
    values = consent_form(client)
    values.update(action=action, method='written', evidence='CONSENT-REF-123', acknowledged='yes')
    return values


def approve_ownership(client):
    values = form(client)
    values.update(decision='team_approved', method='in_person', evidence='OWNER-REF-123', acknowledged='yes')
    assert client.post('/ownership-review/1', data=values).status_code == 303


def test_consent_roles_csrf_and_hidden_identity(web):
    client = web.test_client()
    assert client.get('/owner-consent/').status_code == 302
    for uid in (2, 3, 999):
        login(client, uid)
        assert client.get('/owner-consent/1').status_code == 403
    login(client, 5)
    assert client.post('/owner-consent/1', data={'action': 'support_recorded'}).status_code == 400
    values = consent_values(client, 'management_approved')
    assert client.post('/owner-consent/1', data=values).status_code == 403
    values.update(action='support_recorded', actor_id='4')
    assert client.post('/owner-consent/1', data=values).status_code == 303
    from verification.owner_consent import OwnerConsentStore
    store = OwnerConsentStore(web.config['OWNER_CONSENT_DB'])
    try:
        assert store.latest(1)['support_id'] == 5
        assert 'CONSENT-REF-123' not in str(store.latest(1))
    finally: store.close()


def test_full_consent_flow_requires_ownership_and_different_manager(web):
    client = web.test_client(); login(client, 1)
    assert client.post('/owner-consent/1', data=consent_values(client)).status_code == 303
    assert client.post('/owner-consent/1', data=consent_values(client, 'management_approved')).status_code == 400
    approve_ownership(client)
    assert client.post('/owner-consent/1', data=consent_values(client, 'management_approved')).status_code == 400
    login(client, 4)
    values = consent_values(client, 'management_approved')
    assert client.post('/owner-consent/1', data=values).status_code == 303
    assert client.post('/owner-consent/1', data=values).status_code == 409
    page = client.get('/owner-consent/1')
    assert 'تأیید انسانی معتبر' in page.text
    assert page.headers['Cache-Control'] == 'no-store, private'
    with web.app_context():
        db.session.get(AccessibleListing, 1).description = 'changed text'
        db.session.commit()
    assert 'تأیید نهایی معتبر نیست' in client.get('/owner-consent/1').text


def test_consent_withdrawal_and_ownership_revocation(web):
    client = web.test_client(); login(client, 1); approve_ownership(client)
    assert client.post('/owner-consent/1', data=consent_values(client)).status_code == 303
    login(client, 4)
    assert client.post('/owner-consent/1', data=consent_values(client, 'management_approved')).status_code == 303
    values = form(client)
    values.update(decision='rejected', method='in_person', evidence='REJECTION-123', acknowledged='yes')
    assert client.post('/ownership-review/1', data=values).status_code == 303
    assert 'تأیید نهایی معتبر نیست' in client.get('/owner-consent/1').text
    login(client, 5)
    assert client.post('/owner-consent/1', data=consent_values(client, 'withdrawn')).status_code == 303
    assert 'رضایت لغو شده' in client.get('/owner-consent/1').text


def test_consent_invalid_input_and_storage_fail_closed(web):
    client = web.test_client(); login(client, 5)
    values = consent_values(client); values['acknowledged'] = 'no'
    assert client.post('/owner-consent/1', data=values).status_code == 400
    values.update(acknowledged='yes', previous_id='invalid')
    assert client.post('/owner-consent/1', data=values).status_code == 400
    values.update(previous_id='0', fingerprint='stale')
    assert client.post('/owner-consent/1', data=values).status_code == 409
    assert client.get('/owner-consent/999').status_code == 404
    web.config['OWNER_CONSENT_DB'] = str(Path(web.config['OWNER_CONSENT_DB']).parent / 'missing' / 'x.db')
    assert client.get('/owner-consent/1').status_code == 503


def test_consent_queue_pagination(web):
    client = web.test_client(); login(client, 5)
    with web.app_context():
        for i in range(2, 29):
            db.session.add(AccessibleListing(id=i, source_id=f'test_{i}', source_url='https://divar.ir/v/gaHfchN7', title=f'Listing {i}', district='Test', area=80, deal_type='rent'))
        db.session.commit()
    first = client.get('/owner-consent/')
    second = client.get('/owner-consent/?page=2')
    ids1 = set(re.findall(r'href="/owner-consent/(\d+)"', first.text))
    ids2 = set(re.findall(r'href="/owner-consent/(\d+)"', second.text))
    assert len(ids1) == 25 and len(ids2) == 3 and not ids1.intersection(ids2)
    assert client.get('/owner-consent/?page=0').status_code == 400
