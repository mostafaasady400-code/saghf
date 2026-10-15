"""Explicit Telegram-to-office membership; never infer an agent from a user ID."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import CheckConstraint, func, inspect

from database.db import db
from database.models import Agent, User


class OfficeMembership(db.Model):
    __tablename__ = 'telegram_office_memberships'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=False, index=True)
    office_key = db.Column(db.String(80), nullable=False, index=True)
    office_role = db.Column(db.String(20), nullable=False, default='agent')
    active = db.Column(db.Boolean, nullable=False, default=True)
    panel_mode = db.Column(db.String(20), nullable=False, default='office')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (CheckConstraint("office_role IN ('agent', 'manager')", name='ck_telegram_office_role'),)


class OfficeAction(db.Model):
    """Durable one-use form/confirmation tokens; consumption and mutation commit together."""
    __tablename__ = 'telegram_office_actions'
    token = db.Column(db.String(32), primary_key=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('telegram_office_memberships.id'), nullable=False, index=True)
    kind = db.Column(db.String(30), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    payload = db.Column(db.Text, nullable=False, default='')
    stage = db.Column(db.String(20), nullable=False, default='input')
    consumed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)


def ensure_office_schema():
    """Only add this feature's tables; never create/alter existing CRM tables."""
    OfficeMembership.__table__.create(bind=db.engine, checkfirst=True)
    OfficeAction.__table__.create(bind=db.engine, checkfirst=True)


@dataclass(frozen=True)
class OfficePrincipal:
    telegram_id: str
    membership_id: int
    user_id: int
    agent_id: int
    office_key: str
    office_role: str
    agent_ids: tuple


def _telegram_key(telegram_id):
    if isinstance(telegram_id, bool):
        return None
    value = str(telegram_id)
    if (not 1 <= len(value) <= 19 or not value.isascii() or not value.isdigit()
            or not 0 < int(value) < 2 ** 63 or str(int(value)) != value):
        return None
    return value


def _active_members():
    unambiguous_ids = (db.session.query(User.telegram_id).filter(User.is_active.is_(True))
                       .group_by(User.telegram_id).having(func.count(User.id) == 1))
    return (db.session.query(OfficeMembership)
            .join(User, User.id == OfficeMembership.user_id)
            .join(Agent, Agent.id == OfficeMembership.agent_id)
            .filter(OfficeMembership.active.is_(True), User.is_active.is_(True),
                    Agent.is_active.is_(True), User.role.in_(('agent', 'admin', 'super_admin')),
                    User.telegram_id == OfficeMembership.telegram_id,
                    OfficeMembership.telegram_id.in_(unambiguous_ids),
                    OfficeMembership.office_role.in_(('agent', 'manager'))))


def principal_for(telegram_id):
    key = _telegram_key(telegram_id)
    if key is None or not inspect(db.engine).has_table(OfficeMembership.__tablename__):
        return None
    # Duplicate active platform identities are ambiguous and fail closed.
    users = User.query.filter_by(telegram_id=key, is_active=True).limit(2).all()
    if len(users) != 1:
        return None
    member = (_active_members().filter(OfficeMembership.telegram_id == key,
                                       OfficeMembership.user_id == users[0].id)
              .populate_existing().one_or_none())
    if not member or not (member.office_key or '').strip():
        return None
    all_members = _active_members().populate_existing().all()
    offices = {}
    for row in all_members:
        offices.setdefault(row.agent_id, set()).add(row.office_key)
    # Even malformed manual provisioning must not bridge two offices.
    if offices.get(member.agent_id) != {member.office_key}:
        return None
    agent_ids = (member.agent_id,)
    if member.office_role == 'manager':
        agent_ids = tuple(sorted({row.agent_id for row in all_members
                                  if row.office_key == member.office_key
                                  and offices[row.agent_id] == {member.office_key}}))
    return OfficePrincipal(key, member.id, member.user_id, member.agent_id,
                           member.office_key, member.office_role, agent_ids)


def provision_membership(*, telegram_id, user_id, agent_id, office_key, office_role='agent', active=True):
    """Explicit administrator CLI provisioning; no phone lookup or implicit role upgrades."""
    key = _telegram_key(telegram_id)
    if (key is None or office_role not in ('agent', 'manager') or
            not isinstance(office_key, str) or not office_key.strip() or len(office_key) > 80):
        raise ValueError('invalid_membership')
    user, agent = db.session.get(User, user_id), db.session.get(Agent, agent_id)
    if (not user or not user.is_active or user.role not in ('agent', 'admin', 'super_admin')
            or user.telegram_id != key or not agent or not agent.is_active):
        raise ValueError('explicit_active_user_agent_required')
    if User.query.filter_by(telegram_id=key, is_active=True).count() != 1:
        raise ValueError('ambiguous_telegram_identity')
    member = OfficeMembership.query.filter_by(telegram_id=key).one_or_none()
    others = OfficeMembership.query.filter(OfficeMembership.agent_id == agent_id,
                                           OfficeMembership.telegram_id != key,
                                           OfficeMembership.active.is_(True)).all()
    if active and any(row.office_key != office_key.strip() for row in others):
        raise ValueError('agent_already_assigned_to_other_office')
    if member is None:
        member = OfficeMembership(telegram_id=key)
        db.session.add(member)
    member.user_id, member.agent_id = user.id, agent.id
    member.office_key, member.office_role, member.active = office_key.strip(), office_role, bool(active)
    db.session.commit()
    return member


def main(argv=None):
    import argparse
    from telegram_bot.runtime import create_crm_context
    parser = argparse.ArgumentParser(description='Provision an explicit Telegram office membership.')
    parser.add_argument('--telegram-id', required=True)
    parser.add_argument('--user-id', required=True, type=int)
    parser.add_argument('--agent-id', required=True, type=int)
    parser.add_argument('--office-key', required=True)
    parser.add_argument('--office-role', choices=('agent', 'manager'), default='agent')
    parser.add_argument('--inactive', action='store_true')
    args = parser.parse_args(argv)
    app = create_crm_context()
    with app.app_context():
        ensure_office_schema()
        try:
            provision_membership(telegram_id=args.telegram_id, user_id=args.user_id,
                                 agent_id=args.agent_id, office_key=args.office_key,
                                 office_role=args.office_role, active=not args.inactive)
        except ValueError as exc:
            db.session.rollback()
            parser.error(str(exc))
    print('Office membership saved; no credentials or customer data displayed.')


if __name__ == '__main__':
    main()
