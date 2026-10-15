import hashlib
import json
import sqlite3
import time


def listing_fingerprint(listing):
    keys = ('id', 'source_id', 'source_url', 'title', 'district', 'area', 'deal_type')
    data = {k: getattr(listing, k, None) for k in keys}
    if any(v in (None, '') for v in data.values()):
        raise ValueError('incomplete_listing')
    for key in ('description', 'rooms', 'deposit', 'monthly_rent', 'total_price', 'published_at'):
        data[key] = getattr(listing, key, None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class TeamReviewStore:
    def __init__(self, path, *, clock=time.time):
        self.clock = clock
        self.db = sqlite3.connect(str(path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS team_ownership_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL, reviewer_id INTEGER NOT NULL,
            decision TEXT NOT NULL, method TEXT NOT NULL, evidence_hash TEXT NOT NULL,
            reviewed_at REAL NOT NULL, expires_at REAL NOT NULL)''')
        self.db.commit()

    def latest(self, listing_id):
        row = self.db.execute('SELECT * FROM team_ownership_reviews WHERE listing_id=? ORDER BY id DESC LIMIT 1', (listing_id,)).fetchone()
        return dict(row) if row else None

    def status(self, listing_id, fingerprint):
        row = self.latest(listing_id)
        if not row:
            return 'pending_review'
        if row['fingerprint'] != fingerprint or self.clock() >= row['expires_at']:
            return 'needs_review'
        return row['decision']

    def record(self, listing_id, fingerprint, reviewer_id, *, decision, method, evidence, previous_id, acknowledged):
        if decision not in {'team_approved', 'rejected', 'needs_review'}:
            raise ValueError('invalid_decision')
        if method not in {'owner_interview', 'document_review', 'in_person', 'insufficient_evidence'}:
            raise ValueError('invalid_method')
        if decision == 'team_approved' and method == 'insufficient_evidence':
            raise ValueError('approval_needs_evidence')
        if acknowledged is not True or not isinstance(evidence, str) or not 6 <= len(evidence.strip()) <= 200:
            raise ValueError('evidence_required')
        if type(reviewer_id) is not int or reviewer_id <= 0:
            raise ValueError('invalid_reviewer')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.latest(listing_id)
            if (old['id'] if old else 0) != previous_id:
                raise ValueError('review_conflict')
            now = self.clock()
            self.db.execute('INSERT INTO team_ownership_reviews(listing_id,fingerprint,reviewer_id,decision,method,evidence_hash,reviewed_at,expires_at) VALUES(?,?,?,?,?,?,?,?)',
                (listing_id, fingerprint, reviewer_id, decision, method, hashlib.sha256(evidence.strip().encode()).hexdigest(), now, now + 7 * 86400))

    def close(self):
        self.db.close()
