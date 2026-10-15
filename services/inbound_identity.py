"""Canonical identity and channel validation for every inbound CRM event."""

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


SUPPORTED_INBOUND_CHANNELS = frozenset({
    'voip', 'call', 'sms', 'telegram', 'whatsapp', 'bale',
    'eitaa', 'rubika', 'instagram', 'web', 'crm', 'native_automation',
})

_PHONE_CHANNELS = frozenset({'voip', 'call', 'sms', 'whatsapp'})


class InboundValidationError(ValueError):
    """Raised when an inbound event cannot be attributed to a real contact."""


@dataclass(frozen=True)
class InboundIdentity:
    channel: str
    external_id: str
    phone_number: Optional[str]
    contact_key: str

    def as_metadata(self) -> Dict[str, Any]:
        return {
            'source_channel': self.channel,
            'source_external_id': self.external_id,
            'normalized_phone': self.phone_number,
            'contact_key': self.contact_key,
        }


def normalize_iran_phone(value: Any) -> Optional[str]:
    """Return an Iranian mobile in canonical 09xxxxxxxxx form, if present."""
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('0098'):
        digits = digits[4:]
    elif digits.startswith('98'):
        digits = digits[2:]
    if digits.startswith('9') and len(digits) == 10:
        digits = f'0{digits}'
    return digits if re.fullmatch(r'09\d{9}', digits) else None


def resolve_inbound_identity(
    channel: Any,
    sender_id: Any = None,
    phone_number: Any = None,
) -> InboundIdentity:
    normalized_channel = str(channel or '').strip().lower()
    if normalized_channel not in SUPPORTED_INBOUND_CHANNELS:
        raise InboundValidationError(f'کانال ورودی «{normalized_channel or "نامشخص"}» پشتیبانی نمی‌شود.')

    raw_external_id = str(sender_id or phone_number or '').strip()
    normalized_phone = normalize_iran_phone(phone_number or sender_id)
    if not raw_external_id:
        raise InboundValidationError('شناسه فرستنده یا شماره تماس واقعی الزامی است.')
    if normalized_channel in _PHONE_CHANNELS and not normalized_phone:
        raise InboundValidationError('برای این کانال، شماره موبایل معتبر ایران الزامی است.')

    # Messenger chat/user IDs are identities, not phone numbers. Keep them
    # namespaced so identical IDs from two platforms never merge in CRM.
    contact_key = normalized_phone or f'{normalized_channel}:{raw_external_id}'
    return InboundIdentity(
        channel=normalized_channel,
        external_id=raw_external_id,
        phone_number=normalized_phone,
        contact_key=contact_key,
    )
