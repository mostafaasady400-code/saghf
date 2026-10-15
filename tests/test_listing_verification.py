import hashlib

import pytest

from verification.workflow import VerificationError, VerificationStore, token_from_url


@pytest.fixture
def fixture_case(tmp_path):
    now = [1000.0]
    deliveries = []
    store = VerificationStore(tmp_path / 'cases.db', key=b'x'*32, sender=lambda phone, code: deliveries.append((phone, code)) or True, clock=lambda: now[0])
    snapshot = dict(token='gaCP64cf', title='واحد', district='پونک', area=80, deal_type='rent')
    case_id = store.create('https://divar.ir/v/gaCP64cf', snapshot)
    yield store, case_id, snapshot, now, deliveries
    store.close()


def review(store, case_id):
    store.record_human_review(case_id, reviewer='isolated-test-reviewer', evidence_hash=hashlib.sha256(b'test-evidence').hexdigest(), consent_version='owner-contact-v1')


def test_no_review_cannot_probe_or_issue_otp(fixture_case):
    store, cid, snapshot, _, deliveries = fixture_case
    from verification.playwright_probe import recheck_reviewed_listing
    with pytest.raises(VerificationError, match='human_review'):
        recheck_reviewed_listing(store, cid, cdp_url='http://127.0.0.1:1')
    with pytest.raises(VerificationError):store.issue_otp(cid, '09120000000')
    assert not deliveries


def test_review_needs_evidence_and_consent(fixture_case):
    store, cid, *_ = fixture_case
    with pytest.raises(VerificationError):
        store.record_human_review(cid, reviewer='admin', evidence_hash='missing', consent_version='none')
    assert store.public_status(cid)['state']=='pending_review'


def test_changed_listing_invalidates_gate(fixture_case):
    store,cid,snapshot,_,deliveries=fixture_case
    review(store,cid)
    assert not store.record_listing_check(cid,{**snapshot,'area':90},active=True)
    with pytest.raises(VerificationError):store.issue_otp(cid,'09120000000')
    assert not deliveries


def test_opt_in_otp_controls_number_not_ownership(fixture_case):
    store,cid,snapshot,_,deliveries=fixture_case
    review(store,cid);assert store.record_listing_check(cid,snapshot,active=True)
    store.issue_otp(cid,'09120000000')
    assert store.verify_otp(cid,deliveries[-1][1])
    status=store.public_status(cid)
    assert status['phone_control_verified'] and not status['ownership_guaranteed']
    assert status['phone_matches_divar'] is None
    assert not store.verify_otp(cid,deliveries[-1][1])
    row=store._case(cid)
    assert row['otp_digest'] is None
    assert '09120000000' not in str(dict(row))


def test_otp_attempt_limit_and_expiry(fixture_case):
    store,cid,snapshot,now,deliveries=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.issue_otp(cid,'09120000000')
    correct=deliveries[-1][1];wrong='000000' if correct!='000000' else '111111'
    for _ in range(5):assert not store.verify_otp(cid,wrong)
    assert not store.verify_otp(cid,correct)
    now[0]+=61;store.issue_otp(cid,'09120000000');now[0]+=301
    assert not store.verify_otp(cid,deliveries[-1][1])


def test_cooldown_and_no_provider_fail_closed(fixture_case):
    store,cid,snapshot,_,_=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.issue_otp(cid,'09120000000')
    with pytest.raises(VerificationError,match='cooldown'):store.issue_otp(cid,'09120000000')
    store.sender=None
    with pytest.raises(VerificationError,match='not_configured'):store.issue_otp(cid,'09120000000')


def test_send_failure_does_not_leak_provider_exception(fixture_case):
    store,cid,snapshot,_,_=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True)
    def fail(*args):raise RuntimeError('private provider credentials')
    store.sender=fail
    with pytest.raises(VerificationError,match='sms_delivery_unconfirmed') as exc:store.issue_otp(cid,'09120000000')
    assert 'private' not in str(exc.value)
    assert store._case(cid)['otp_digest'] is None


def test_success_does_not_survive_stale_listing_check(fixture_case):
    store,cid,snapshot,now,deliveries=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.issue_otp(cid,'09120000000')
    assert store.verify_otp(cid,deliveries[-1][1])
    now[0]+=901
    assert not store.public_status(cid)['phone_control_verified']


def test_otp_total_send_limit(fixture_case):
    store,cid,snapshot,now,_=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True)
    for _ in range(5):
        store.issue_otp(cid,'09120000000');now[0]+=61
    with pytest.raises(VerificationError,match='send_limit'):store.issue_otp(cid,'09120000000')


def test_different_case_cannot_redeem_code(fixture_case):
    store,cid,snapshot,_,deliveries=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.issue_otp(cid,'09120000000')
    other=store.create('https://divar.ir/v/gaCP64cf',snapshot)
    review(store,other);store.record_listing_check(other,snapshot,active=True)
    assert not store.verify_otp(other,deliveries[-1][1])


def test_consent_withdrawal_blocks_reuse(fixture_case):
    store,cid,snapshot,_,deliveries=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.issue_otp(cid,'09120000000')
    store.withdraw_consent(cid)
    with pytest.raises(VerificationError):store.verify_otp(cid,deliveries[-1][1])
    assert store._case(cid)['phone_tag'] is None
    assert not store.public_status(cid)['phone_control_verified']


def test_missing_secret_prevents_delivery(fixture_case):
    store,cid,snapshot,_,deliveries=fixture_case
    review(store,cid);store.record_listing_check(cid,snapshot,active=True);store.key=None
    with pytest.raises(VerificationError,match='secret_not_configured'):store.issue_otp(cid,'09120000000')
    assert not deliveries


@pytest.mark.parametrize('url',['https://evil.example/v/gaCP64cf','https://divar.ir.evil/v/gaCP64cf','https://user@divar.ir/v/gaCP64cf','https://divar.ir/v/gaCP64cf?x=1'])
def test_untrusted_url_rejected(url):
    with pytest.raises(VerificationError):token_from_url(url)
