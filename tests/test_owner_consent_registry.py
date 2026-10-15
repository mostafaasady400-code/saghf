import pytest
from verification.owner_consent import OwnerConsentStore


def test_separate_manager_expiry_and_withdrawal(tmp_path):
    now = [1000]
    s = OwnerConsentStore(tmp_path / 'consent.db', clock=lambda: now[0])
    try:
        values = dict(action='support_recorded', method='written', evidence='REF-123456', previous_id=0, acknowledged=True)
        s.record(47, 'snapshot', 1, **values)
        assert 'REF-123456' not in str(s.latest(47))
        values.update(action='management_approved', previous_id=s.latest(47)['id'])
        with pytest.raises(ValueError, match='separate_manager'): s.record(47, 'snapshot', 1, **values)
        s.record(47, 'snapshot', 2, **values)
        assert s.status(47, 'snapshot') == 'management_approved'
        assert s.status(47, 'changed') == 'needs_renewal'
        values.update(action='withdrawn', previous_id=s.latest(47)['id'])
        s.record(47, 'snapshot', 1, **values)
        assert s.status(47, 'snapshot') == 'withdrawn'
        with pytest.raises(ValueError, match='consent_conflict'): s.record(47, 'snapshot', 2, **values)
        now[0] += 7 * 86400
        assert s.status(47, 'snapshot') == 'withdrawn'
    finally: s.close()


def test_no_inferred_or_unrecorded_consent(tmp_path):
    s = OwnerConsentStore(tmp_path / 'consent.db')
    try:
        values = dict(action='management_approved', method='written', evidence='REF-123456', previous_id=0, acknowledged=True)
        with pytest.raises(ValueError, match='actual_consent'): s.record(47, 'snapshot', 2, **values)
        values.update(action='support_recorded', acknowledged=False)
        with pytest.raises(ValueError, match='human_attestation'): s.record(47, 'snapshot', 1, **values)
        assert s.status(47, 'snapshot') == 'awaiting_owner_consent'
    finally: s.close()
