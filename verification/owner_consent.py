# Internal evidence registry. No phone collection, no implied consent.
import hashlib
import sqlite3
import time


class OwnerConsentStore:
    def __init__(self, path, *, clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(str(path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS consent_events (id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, actor_id INTEGER NOT NULL, action TEXT NOT NULL, method TEXT NOT NULL, evidence_hash TEXT NOT NULL, support_id INTEGER NOT NULL, observed_at REAL NOT NULL, expires_at REAL NOT NULL)')
        self.db.commit()

    def latest(self, listing_id):
        row = self.db.execute('SELECT * FROM consent_events WHERE listing_id=? ORDER BY id DESC LIMIT 1', (listing_id,)).fetchone()
        return dict(row) if row else None

    def history(self, listing_id):
        rows = self.db.execute('SELECT id,actor_id,action,method,observed_at FROM consent_events WHERE listing_id=? ORDER BY id DESC LIMIT 20', (listing_id,)).fetchall()
        return [dict(row) for row in rows]

    def status(self, listing_id, fingerprint):
        row = self.latest(listing_id)
        if not row:
            return 'awaiting_owner_consent'
        if row['action'] in {'withdrawn', 'rejected'}:
            return row['action']
        if row['fingerprint'] != fingerprint or self.clock() >= row['expires_at']:
            return 'needs_renewal'
        return row['action']

    def record(self, listing_id, fingerprint, actor_id, *, action, method, evidence, previous_id, acknowledged):
        if type(listing_id) is not int or listing_id <= 0 or not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError('invalid_listing')
        if type(actor_id) is not int or actor_id <= 0 or acknowledged is not True:
            raise ValueError('human_attestation_required')
        if not isinstance(evidence, str) or not 6 <= len(evidence.strip()) <= 200:
            raise ValueError('evidence_required')
        if action not in {'support_recorded', 'management_approved', 'rejected', 'withdrawn'}:
            raise ValueError('invalid_action')
        if method not in {'written', 'recorded_verbal', 'in_person_signed'}:
            raise ValueError('invalid_method')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.latest(listing_id)
            if (old['id'] if old else 0) != previous_id:
                raise ValueError('consent_conflict')
            if action in {'rejected', 'withdrawn'} and not old:
                raise ValueError('consent_missing')
            if action == 'management_approved':
                if not old or old['action'] != 'support_recorded' or old['fingerprint'] != fingerprint or old['expires_at'] <= self.clock():
                    raise ValueError('actual_consent_required')
                if old['support_id'] == actor_id:
                    raise ValueError('separate_manager_required')
            support = actor_id if action == 'support_recorded' else (old['support_id'] if old else actor_id)
            now = self.clock()
            expiry = now + 7 * 86400 if action == 'support_recorded' else (old['expires_at'] if old else now)
            self.db.execute('INSERT INTO consent_events(listing_id,fingerprint,actor_id,action,method,evidence_hash,support_id,observed_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (listing_id, fingerprint, actor_id, action, method, hashlib.sha256(evidence.strip().encode()).hexdigest(), support, now, expiry))

    def close(self):
        self.db.close()
