import pytest

from services.inbound_identity import (
    InboundValidationError,
    normalize_iran_phone,
    resolve_inbound_identity,
)


def test_phone_is_normalized_to_one_crm_identity():
    assert normalize_iran_phone('+98 912 345 6789') == '09123456789'
    identity = resolve_inbound_identity('sms', '989123456789')
    assert identity.contact_key == '09123456789'
    assert identity.phone_number == '09123456789'


def test_messenger_identity_is_namespaced_and_not_fabricated_as_phone():
    telegram = resolve_inbound_identity('telegram', 12345)
    bale = resolve_inbound_identity('bale', 12345)
    assert telegram.contact_key == 'telegram:12345'
    assert bale.contact_key == 'bale:12345'
    assert telegram.phone_number is None
    assert telegram.contact_key != bale.contact_key


def test_phone_channel_rejects_missing_or_invalid_phone():
    with pytest.raises(InboundValidationError):
        resolve_inbound_identity('voip', 'anonymous')


def test_unknown_channel_is_rejected():
    with pytest.raises(InboundValidationError):
        resolve_inbound_identity('unknown-network', '123')
