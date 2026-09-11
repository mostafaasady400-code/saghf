from datetime import datetime
import json
from .db import db

class Agent(db.Model):
    __tablename__ = 'agents'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(50), default='مشاور املاک')
    avatar_color = db.Column(db.String(20), default='#00f2fe')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    properties = db.relationship('Property', backref='agent', lazy=True)
    clients = db.relationship('Client', backref='agent', lazy=True)
    interactions = db.relationship('Interaction', backref='agent', lazy=True)
    visits = db.relationship('Visit', backref='agent', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'role': self.role,
            'avatar_color': self.avatar_color,
            'active_properties_count': len([p for p in self.properties if p.status in ['verified', 'available']]),
            'active_clients_count': len([c for c in self.clients if c.lead_status not in ['contract_won', 'lost']])
        }

class Owner(db.Model):
    __tablename__ = 'owners'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(30), nullable=False, index=True)
    secondary_phone = db.Column(db.String(30), nullable=True)
    urgency = db.Column(db.String(20), default='medium')  # low, medium, high, very_urgent
    flexibility = db.Column(db.String(50), default='معمولی')  # تخفیف‌پذیر، مقطوع، منعطف
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    properties = db.relationship('Property', backref='owner', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'phone_number': self.phone_number,
            'secondary_phone': self.secondary_phone,
            'urgency': self.urgency,
            'flexibility': self.flexibility,
            'notes': self.notes,
            'properties_count': len(self.properties),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class Property(db.Model):
    __tablename__ = 'properties'
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(30), default='direct_owner', index=True)  # divar, sheypoor, direct_owner, colleague
    source_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    source_url = db.Column(db.String(300), nullable=True)
    
    title = db.Column(db.String(250), nullable=False)
    deal_type = db.Column(db.String(20), nullable=False, index=True)  # sale, rent
    property_type = db.Column(db.String(30), default='apartment', index=True)  # apartment, villa, commercial, land, office
    
    city = db.Column(db.String(50), default='تهران', index=True)
    district = db.Column(db.String(100), nullable=False, index=True)
    address = db.Column(db.String(250), nullable=True)
    
    # Financial fields
    total_price = db.Column(db.BigInteger, default=0)  # for sale in Tomans
    meter_price = db.Column(db.BigInteger, default=0)
    deposit = db.Column(db.BigInteger, default=0)      # رهن
    monthly_rent = db.Column(db.BigInteger, default=0) # اجاره
    
    # Physical specs
    area = db.Column(db.Integer, nullable=False, index=True)
    rooms = db.Column(db.Integer, default=1)
    floor = db.Column(db.Integer, default=1)
    total_floors = db.Column(db.Integer, nullable=True)
    units_per_floor = db.Column(db.Integer, nullable=True)
    build_year = db.Column(db.Integer, nullable=True)
    
    # Core Amenities
    has_elevator = db.Column(db.Boolean, default=False)
    has_parking = db.Column(db.Boolean, default=False)
    has_warehouse = db.Column(db.Boolean, default=False)
    has_balcony = db.Column(db.Boolean, default=False)
    
    features_json = db.Column(db.Text, default='[]')
    description = db.Column(db.Text, nullable=True)
    images_json = db.Column(db.Text, default='[]')
    
    # Status & scoring
    status = db.Column(db.String(30), default='raw_crawled', index=True) # raw_crawled, verified, available, reserved, sold, archived
    score = db.Column(db.Integer, default=70) # 0 to 100 quality score
    
    owner_id = db.Column(db.Integer, db.ForeignKey('owners.id'), nullable=True)
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    matches = db.relationship('MatchRecord', backref='property', lazy='dynamic', cascade="all, delete-orphan")
    visits = db.relationship('Visit', backref='property', lazy=True)
    interactions = db.relationship('Interaction', backref='property', lazy=True)

    @property
    def features(self):
        try:
            return json.loads(self.features_json or '[]')
        except Exception:
            return []

    @features.setter
    def features(self, val):
        self.features_json = json.dumps(val, ensure_ascii=False)

    @property
    def images(self):
        try:
            return json.loads(self.images_json or '[]')
        except Exception:
            return []

    @images.setter
    def images(self, val):
        self.images_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'source': self.source,
            'source_id': self.source_id,
            'source_url': self.source_url,
            'title': self.title,
            'deal_type': self.deal_type,
            'property_type': self.property_type,
            'city': self.city,
            'district': self.district,
            'address': self.address,
            'total_price': self.total_price,
            'meter_price': self.meter_price,
            'deposit': self.deposit,
            'monthly_rent': self.monthly_rent,
            'area': self.area,
            'rooms': self.rooms,
            'floor': self.floor,
            'build_year': self.build_year,
            'has_elevator': self.has_elevator,
            'has_parking': self.has_parking,
            'has_warehouse': self.has_warehouse,
            'has_balcony': self.has_balcony,
            'features': self.features,
            'description': self.description,
            'images': self.images,
            'status': self.status,
            'score': self.score,
            'owner': self.owner.to_dict() if self.owner else None,
            'agent_name': self.agent.name if self.agent else 'مشخص نشده',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class Client(db.Model):
    __tablename__ = 'clients'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(30), nullable=False, index=True)
    
    preferred_deal_type = db.Column(db.String(20), default='sale', index=True) # sale, rent
    property_types_json = db.Column(db.Text, default='["apartment"]')
    preferred_districts_json = db.Column(db.Text, default='[]')
    
    # Financial expectations
    min_budget = db.Column(db.BigInteger, default=0)
    max_budget = db.Column(db.BigInteger, default=0)
    max_deposit = db.Column(db.BigInteger, default=0)
    max_rent = db.Column(db.BigInteger, default=0)
    
    # Space & criteria
    min_area = db.Column(db.Integer, default=0)
    max_area = db.Column(db.Integer, default=0)
    min_rooms = db.Column(db.Integer, default=1)
    
    must_have_parking = db.Column(db.Boolean, default=False)
    must_have_elevator = db.Column(db.Boolean, default=False)
    must_have_warehouse = db.Column(db.Boolean, default=False)
    
    urgency = db.Column(db.String(20), default='normal')  # immediate, urgent, normal, looking
    lead_status = db.Column(db.String(30), default='new', index=True) # new, contacted, visiting, negotiating, contract_won, lost
    notes = db.Column(db.Text, nullable=True)
    
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    matches = db.relationship('MatchRecord', backref='client', lazy='dynamic', cascade="all, delete-orphan")
    visits = db.relationship('Visit', backref='client', lazy=True)
    interactions = db.relationship('Interaction', backref='client', lazy=True)

    @property
    def property_types(self):
        try:
            return json.loads(self.property_types_json or '[]')
        except Exception:
            return []

    @property
    def preferred_districts(self):
        try:
            return json.loads(self.preferred_districts_json or '[]')
        except Exception:
            return []

    @preferred_districts.setter
    def preferred_districts(self, val):
        self.preferred_districts_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'full_name': self.full_name,
            'phone_number': self.phone_number,
            'preferred_deal_type': self.preferred_deal_type,
            'property_types': self.property_types,
            'preferred_districts': self.preferred_districts,
            'min_budget': self.min_budget,
            'max_budget': self.max_budget,
            'max_deposit': self.max_deposit,
            'max_rent': self.max_rent,
            'min_area': self.min_area,
            'max_area': self.max_area,
            'min_rooms': self.min_rooms,
            'must_have_parking': self.must_have_parking,
            'must_have_elevator': self.must_have_elevator,
            'must_have_warehouse': self.must_have_warehouse,
            'urgency': self.urgency,
            'lead_status': self.lead_status,
            'notes': self.notes,
            'agent_name': self.agent.name if self.agent else 'مشخص نشده',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class MatchRecord(db.Model):
    __tablename__ = 'matching_records'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False, index=True)
    match_score = db.Column(db.Integer, nullable=False)  # 0 to 100
    match_reasons_json = db.Column(db.Text, default='[]')
    is_suggested = db.Column(db.Boolean, default=False)
    client_feedback = db.Column(db.String(30), default='pending') # pending, interested, rejected, visited
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def match_reasons(self):
        try:
            return json.loads(self.match_reasons_json or '[]')
        except Exception:
            return []

    @match_reasons.setter
    def match_reasons(self, val):
        self.match_reasons_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'property_id': self.property_id,
            'client_id': self.client_id,
            'match_score': self.match_score,
            'match_reasons': self.match_reasons,
            'is_suggested': self.is_suggested,
            'client_feedback': self.client_feedback,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class Interaction(db.Model):
    __tablename__ = 'interactions'
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(30), default='call')  # call, meeting, visit_followup, whatsapp, offer
    target_type = db.Column(db.String(20), default='client')  # client, owner
    target_id = db.Column(db.Integer, nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('owners.id'), nullable=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=True)
    
    summary = db.Column(db.Text, nullable=False)
    outcome = db.Column(db.String(30), default='interested') # interested, visit_scheduled, call_back, price_high, rejected
    next_followup_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'client_id': self.client_id,
            'owner_id': self.owner_id,
            'property_id': self.property_id,
            'property_title': self.property.title if self.property else None,
            'agent_name': self.agent.name if self.agent else 'مشاور سیستم',
            'summary': self.summary,
            'outcome': self.outcome,
            'next_followup_date': self.next_followup_date.strftime('%Y-%m-%d %H:%M') if self.next_followup_date else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class Visit(db.Model):
    __tablename__ = 'visits'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=True)
    
    scheduled_time = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(30), default='scheduled') # scheduled, completed, cancelled, no_show
    feedback = db.Column(db.Text, nullable=True)
    readiness_to_buy = db.Column(db.Integer, default=3) # 1 to 5
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'property_id': self.property_id,
            'property_title': self.property.title if self.property else 'ملک حذف شده',
            'property_district': self.property.district if self.property else '',
            'client_id': self.client_id,
            'client_name': self.client.full_name if self.client else 'مشتری نامشخص',
            'client_phone': self.client.phone_number if self.client else '',
            'agent_name': self.agent.name if self.agent else 'مشاور',
            'scheduled_time': self.scheduled_time.strftime('%Y-%m-%d %H:%M') if self.scheduled_time else '',
            'status': self.status,
            'feedback': self.feedback,
            'readiness_to_buy': self.readiness_to_buy
        }
