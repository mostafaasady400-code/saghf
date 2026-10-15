import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit


class VerificationError(ValueError):
    pass


def token_from_url(url):
    parsed = urlsplit(str(url))
    if parsed.scheme != "https" or parsed.hostname != "divar.ir" or parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VerificationError("invalid_listing_url")
    parts = parsed.path.strip("/").split("/")
    if len(parts) not in (2, 3) or parts[0] != "v" or not re.fullmatch(r"[A-Za-z0-9_-]{8}", parts[-1]):
        raise VerificationError("invalid_listing_url")
    return parts[-1]


def snapshot_hash(snapshot):
    required = ("token", "title", "district", "area", "deal_type")
    if not isinstance(snapshot, dict) or any(snapshot.get(k) in (None, "") for k in required):
        raise VerificationError("incomplete_listing_snapshot")
    return hashlib.sha256(json.dumps({k: snapshot[k] for k in required}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class VerificationStore:
    """Trusted local/admin application boundary, NOT an unauthenticated API.

    A review records a human decision; it is never a 100-percent guarantee.
    Sender is an explicit configured SMS provider, never a console fallback.
    """
    def __init__(self, path, *, key=None, sender=None, clock=time.time):
        self.db = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.key = key.encode() if isinstance(key, str) else key
        self.sender, self.clock = sender, clock
        self.db.execute("""CREATE TABLE IF NOT EXISTS verification_cases (
            case_id TEXT PRIMARY KEY, token TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
            state TEXT NOT NULL, reviewer TEXT, evidence_hash TEXT, reviewed_at REAL,
            consent_version TEXT, consent_at REAL, checked_at REAL,
            phone_tag TEXT, otp_digest TEXT, otp_expires REAL, attempts INTEGER DEFAULT 0,
            last_sent REAL, phone_verified_at REAL, sends INTEGER DEFAULT 0)""")
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def _case(self, case_id):
        row = self.db.execute("SELECT * FROM verification_cases WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise VerificationError("case_not_found")
        return row

    def create(self, url, snapshot):
        token = token_from_url(url)
        if snapshot.get("token") != token:
            raise VerificationError("listing_identity_mismatch")
        digest = snapshot_hash(snapshot)
        case_id = secrets.token_urlsafe(18)
        with self.transaction():
            self.db.execute("INSERT INTO verification_cases(case_id,token,snapshot_hash,state) VALUES(?,?,?,?)", (case_id, token, digest, "pending_review"))
        return case_id

    def record_human_review(self, case_id, *, reviewer, evidence_hash, consent_version):
        # Caller must authenticate/authorize the reviewer externally. No route
        # is exposed until that integration exists. Evidence is not stored here.
        if not isinstance(reviewer, str) or not reviewer.strip() or not re.fullmatch(r"[a-f0-9]{64}", str(evidence_hash)) or consent_version != "owner-contact-v1":
            raise VerificationError("review_evidence_and_explicit_consent_required")
        with self.transaction():
            self._case(case_id)
            self.db.execute("""UPDATE verification_cases SET state='reviewed', reviewer=?,evidence_hash=?,reviewed_at=?,consent_version=?,consent_at=?,checked_at=NULL,phone_tag=NULL,otp_digest=NULL,otp_expires=NULL,attempts=0,phone_verified_at=NULL WHERE case_id=?""", (reviewer, evidence_hash, self.clock(), consent_version, self.clock(), case_id))

    def require_review(self, case_id):
        row = self._case(case_id)
        if row['state'] not in ('reviewed', 'listing_matched', 'otp_pending', 'phone_control_verified') or not row['consent_at'] or row['consent_version'] != 'owner-contact-v1' or self.clock() - row['reviewed_at'] > 7 * 86400:
            raise VerificationError("human_review_and_consent_required")
        return row

    def record_listing_check(self, case_id, snapshot, *, active):
        with self.transaction():
            row = self.require_review(case_id)
            matched = active is True and snapshot.get('token') == row['token'] and snapshot_hash(snapshot) == row['snapshot_hash']
            self.db.execute("UPDATE verification_cases SET state=?,checked_at=?,otp_digest=NULL,otp_expires=NULL,phone_tag=NULL,phone_verified_at=NULL WHERE case_id=?", ('listing_matched' if matched else 'needs_review', self.clock() if matched else None, case_id))
        return matched

    def _digest(self, purpose, value):
        if not isinstance(self.key, bytes) or len(self.key) < 32:
            raise VerificationError('verification_secret_not_configured')
        return hmac.new(self.key, (purpose + ':' + value).encode(), hashlib.sha256).hexdigest()

    def issue_otp(self, case_id, phone):
        # Phone must be voluntarily submitted by the reviewed applicant.
        if not isinstance(phone, str) or not re.fullmatch(r'09[0-9]{9}', phone):
            raise VerificationError('invalid_phone_format')
        if self.sender is None:
            raise VerificationError('sms_provider_not_configured')
        with self.transaction():
            row = self.require_review(case_id)
            if row['state'] not in ('listing_matched', 'otp_pending') or row['checked_at'] is None or self.clock() - row['checked_at'] > 900:
                raise VerificationError('recent_listing_match_required')
            if row['last_sent'] is not None and self.clock() - row['last_sent'] < 60:
                raise VerificationError('otp_cooldown')
            if row['sends'] >= 5:
                raise VerificationError('otp_send_limit')
            code = f'{secrets.randbelow(1000000):06d}'
            phone_tag = self._digest('phone', phone)
            digest = self._digest('otp', case_id + ':' + phone_tag + ':' + code)
            # Reserve under the DB lock so concurrent sends cannot bypass limits.
            self.db.execute("UPDATE verification_cases SET state='otp_sending',phone_tag=?,otp_digest=?,otp_expires=?,attempts=0,last_sent=?,phone_verified_at=NULL,sends=sends+1 WHERE case_id=?", (phone_tag, digest, self.clock()+300, self.clock(), case_id))
        try:
            sent = self.sender(phone, code)
            if sent is not True:
                raise RuntimeError()
        except Exception:
            with self.transaction():
                self.db.execute("UPDATE verification_cases SET state='listing_matched',otp_digest=NULL,otp_expires=NULL WHERE case_id=? AND otp_digest=?", (case_id, digest))
            raise VerificationError('sms_delivery_unconfirmed') from None
        with self.transaction():
            self.db.execute("UPDATE verification_cases SET state='otp_pending' WHERE case_id=? AND otp_digest=? AND state='otp_sending'", (case_id, digest))

    def verify_otp(self, case_id, code):
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
            return False
        with self.transaction():
            row = self.require_review(case_id)
            if row['state'] != 'otp_pending' or not row['otp_digest'] or self.clock() >= row['otp_expires'] or row['attempts'] >= 5:
                return False
            self.db.execute('UPDATE verification_cases SET attempts=attempts+1 WHERE case_id=?', (case_id,))
            digest = self._digest('otp', case_id + ':' + row['phone_tag'] + ':' + str(code))
            valid = hmac.compare_digest(digest, row['otp_digest'])
            if valid:
                self.db.execute("UPDATE verification_cases SET state='phone_control_verified',phone_verified_at=?,otp_digest=NULL,otp_expires=NULL WHERE case_id=?", (self.clock(), case_id))
            return valid

    def public_status(self, case_id):
        row = self._case(case_id)
        fresh = row['reviewed_at'] is not None and self.clock()-row['reviewed_at'] <= 7*86400 and row['checked_at'] is not None and self.clock()-row['checked_at'] <= 900
        return {'case_id': row['case_id'], 'listing_url': 'https://divar.ir/v/' + row['token'],
                'state': row['state'], 'ownership_guaranteed': False,
                'phone_control_verified': row['state'] == 'phone_control_verified' and fresh,
                'phone_matches_divar': None}

    def withdraw_consent(self, case_id):
        with self.transaction():
            self._case(case_id)
            self.db.execute("UPDATE verification_cases SET state='consent_withdrawn',consent_version=NULL,consent_at=NULL,checked_at=NULL,phone_tag=NULL,otp_digest=NULL,otp_expires=NULL,phone_verified_at=NULL WHERE case_id=?", (case_id,))

    def close(self):
        self.db.close()
