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
    status = db.Column(db.String(30), default='raw_crawled', index=True) # raw_crawled, verified, available, reserved, sold, archived, needs_followup
    score = db.Column(db.Integer, default=70) # 0 to 100 quality score
    
    # 7-Day Lifecycle & Omni-Messenger Inquiry
    inquiry_status = db.Column(db.String(30), default='none', index=True) # none, waiting_reply, confirmed_available, confirmed_sold
    last_inquiry_at = db.Column(db.DateTime, nullable=True)
    
    # Owner verification and filtering
    owner_type = db.Column(db.String(30), default='personal', index=True) # personal, agency
    is_personal_owner = db.Column(db.Boolean, default=True, index=True)
    filter_log = db.Column(db.String(250), nullable=True)
    
    owner_id = db.Column(db.Integer, db.ForeignKey('owners.id'), nullable=True)
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey('agents.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    matches = db.relationship('MatchRecord', backref='property', lazy='dynamic', cascade="all, delete-orphan")
    visits = db.relationship('Visit', backref='property', lazy=True)
    interactions = db.relationship('Interaction', backref='property', lazy=True)

    @property
    def age_in_days(self):
        """محاسبه دقیق تعداد روزهای سپری شده از زمان ثبت یا آخرین تمدید"""
        if not self.created_at:
            return 0
        delta = datetime.utcnow() - self.created_at
        return max(0, delta.days)

    @property
    def is_expired(self):
        """بررسی رد شدن از بازه ۷ روزه یا وضعیت نیازمند پیگیری"""
        return self.age_in_days >= 7 or self.status == 'needs_followup'

    def reactivate(self):
        """تایید مجدد موجودی توسط مالک یا کارشناس: بازنشانی تایمر ۷ روزه و انتقال به فایل‌های فعال"""
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.status = 'available'
        self.inquiry_status = 'confirmed_available'

    def archive(self, reason='sold'):
        """بایگانی قطعی ملک به دلیل واگذاری یا انصراف مالک"""
        self.status = 'archived'
        self.updated_at = datetime.utcnow()
        if reason == 'sold':
            self.inquiry_status = 'confirmed_sold'
        else:
            self.inquiry_status = 'archived'

    @property
    def file_code(self):
        """کد ۵ رقمی کوتاه و اختصاصی ملک جهت پرزنت، استعلام تلفنی و ربات تلگرام (مانند 10001)"""
        if not self.id:
            return ""
        return str(10000 + self.id)

    @property
    def time_ago(self):
        """نمایش متنی زمان ثبت آگهی به صورت نسبی (مثلاً: ۲ ساعت پیش)"""
        if not self.created_at:
            return "به تازگی"
        diff = datetime.utcnow() - self.created_at
        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = max(1, diff.seconds // 60)
                return f"{mins} دقیقه پیش"
            return f"{hours} ساعت پیش"
        elif diff.days == 1:
            return "دیروز"
        elif diff.days < 7:
            return f"{diff.days} روز پیش"
        elif diff.days < 30:
            weeks = max(1, diff.days // 7)
            return f"{weeks} هفته پیش"
        else:
            months = max(1, diff.days // 30)
            return f"{months} ماه پیش"

    @classmethod
    def get_by_code(cls, code):
        """
        جستجوی سریع ملک با کد ۵ رقمی یا شناسه عددی.
        پشتیبانی از ارقام فارسی و انگلیسی.
        """
        if not code:
            return None
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        clean_code = ''.join(filter(str.isdigit, str(code).translate(fa_to_en)))
        if not clean_code:
            return None
        try:
            num = int(clean_code)
            if num >= 10000:
                target_id = num - 10000
                prop = db.session.get(cls, target_id)
                if prop:
                    return prop
            return db.session.get(cls, num)
        except Exception:
            return None

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
        """لیست URLهای مستقیم تصاویر در CDN مبدأ (بدون ذخیره فایل فیزیکی یا باینری)"""
        try:
            urls = json.loads(self.images_json or '[]')
            if isinstance(urls, list):
                # فقط URLهای معتبر و مستقیم CDN برگردانده می‌شوند (عدم اجازه به Base64)
                return [
                    u for u in urls
                    if isinstance(u, str) and u.startswith(('http://', 'https://')) and not u.startswith('data:')
                ]
            elif isinstance(urls, str) and urls.startswith(('http://', 'https://')):
                return [urls]
            return []
        except Exception:
            return []

    @images.setter
    def images(self, val):
        """
        قانون بهینه‌سازی دیتابیس (جلوگیری از اشغال فضای دیتابیس):
        - به هیچ عنوان داده باینری (Base64 / Blob) یا فایل فیزیکی در دیتابیس ذخیره نمی‌شود.
        - فقط آدرس مستقیم تصویر در سایت مبدأ (URL مستقیم CDN منبع) به عنوان آرایه‌ای از رشته‌ها ذخیره می‌شود.
        """
        clean_urls = []
        if isinstance(val, str):
            val = val.strip()
            if val.startswith('[') and val.endswith(']'):
                try:
                    val = json.loads(val)
                except Exception:
                    val = [val]
            else:
                val = [val]

        if isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str):
                    item = item.strip()
                    # اکیداً فیلتر و رد کردن هرگونه رشته Base64 یا باینری
                    if item.startswith('data:') or ';base64,' in item or len(item) > 1500:
                        continue
                    if item.startswith(('http://', 'https://')):
                        clean_urls.append(item)

        self.images_json = json.dumps(clean_urls, ensure_ascii=False)

    def to_messenger_dict(self):
        """ساختار استاندارد و آماده جهت ارسال به پایپ‌لاین پیام‌رسان‌ها (تلگرام، بله، ایتا و پیامک)"""
        deal_label = 'فروش' if self.deal_type == 'sale' else 'رهن و اجاره'
        if self.deal_type == 'sale':
            price_txt = f"{self.total_price:,} تومان" if self.total_price else "توافقی"
        else:
            price_txt = f"ودیعه: {self.deposit:,} تومان | اجاره: {self.monthly_rent:,} تومان"

        owner_name = self.owner.full_name if self.owner else 'مالک محترم'
        owner_phone = self.owner.phone_number if self.owner else 'ثبت در سیستم'

        features_str = ' | '.join(self.features) if self.features else 'سند رسمی، نورگیر عالی'
        messenger_text = (
            f"💎 **فایل شخصی (مالک مستقیم)**\n\n"
            f"📌 **{self.title}**\n"
            f"📍 **منطقه:** {self.city}، {self.district}\n"
            f"📐 **متراژ:** {self.area} متر | {self.rooms} خواب | طبقه {self.floor}\n"
            f"💰 **قیمت:** {price_txt}\n"
            f"👤 **مالک:** {owner_name}\n"
            f"📞 **تماس:** `{owner_phone}`\n"
            f"🔗 **لینک آگهی:** {self.source_url}\n"
            f"✨ **امکانات:** {features_str}\n\n"
            f"🆔 #فایل_شخصی #{self.district.replace(' ', '_')} #{deal_label}"
        )

        return {
            'property_id': self.id,
            'file_code': self.file_code,
            'source': self.source,
            'source_url': self.source_url,
            'is_personal_owner': self.is_personal_owner if self.is_personal_owner is not None else True,
            'owner_type': self.owner_type or 'personal',
            'title': self.title,
            'deal_type': self.deal_type,
            'deal_label': deal_label,
            'city': self.city,
            'district': self.district,
            'address': self.address,
            'total_price': self.total_price,
            'deposit': self.deposit,
            'monthly_rent': self.monthly_rent,
            'price_formatted': price_txt,
            'area': self.area,
            'rooms': self.rooms,
            'floor': self.floor,
            'build_year': self.build_year,
            'has_elevator': self.has_elevator,
            'has_parking': self.has_parking,
            'has_warehouse': self.has_warehouse,
            'has_balcony': self.has_balcony,
            'features': self.features,
            'images': self.images,
            'owner_name': owner_name,
            'owner_phone': owner_phone,
            'messenger_text': messenger_text,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

    def to_dict(self):
        deal_label = 'خرید و فروش' if self.deal_type == 'sale' else 'رهن و اجاره'
        type_labels = {
            'apartment': 'آپارتمان',
            'villa': 'ویلا / باغ',
            'commercial': 'تجاری / مغازه',
            'office': 'اداری / دفتر کار',
            'land': 'زمین / کلنگی'
        }
        type_label = type_labels.get(self.property_type, 'آپارتمان')

        return {
            'id': self.id,
            'file_code': self.file_code,
            'source': self.source,
            'source_id': self.source_id,
            'source_url': self.source_url,
            'title': self.title,
            'deal_type': self.deal_type,
            'deal_label': deal_label,
            'property_type': self.property_type,
            'property_type_label': type_label,
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
            'total_floors': self.total_floors,
            'units_per_floor': self.units_per_floor,
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
            'age_in_days': self.age_in_days,
            'time_ago': self.time_ago,
            'is_expired': self.is_expired,
            'inquiry_status': self.inquiry_status or 'none',
            'last_inquiry_at': self.last_inquiry_at.strftime('%Y-%m-%d %H:%M') if self.last_inquiry_at else '',
            'is_personal_owner': self.is_personal_owner if self.is_personal_owner is not None else True,
            'owner_type': self.owner_type or 'personal',
            'filter_log': self.filter_log,
            'owner': self.owner.to_dict() if self.owner else None,
            'agent_name': self.agent.name if self.agent else 'مشخص نشده',
            'messenger_payload': self.to_messenger_dict(),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'created_at_formatted': f"{self.created_at.strftime('%Y/%m/%d')} ساعت {self.created_at.strftime('%H:%M')}" if self.created_at else ''
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

# =====================================================================
# Real Estate Event-Driven Automation Models (Phase 2)
# =====================================================================

class PropertyListing(db.Model):
    """
    جدول اختصاصی فایل‌های استخراج‌شده هدفمند بر اساس مناطق و فیلترهای دیوار/شیپور
    """
    __tablename__ = 'property_listings'
    id = db.Column(db.Integer, primary_key=True)
    ad_code = db.Column(db.String(50), unique=True, index=True, nullable=False) # کد یکتای ۵ رقمی
    source = db.Column(db.String(30), default='divar', index=True) # divar, sheypoor, direct
    source_url = db.Column(db.String(350), nullable=True)
    
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(50), default='تهران', index=True)
    region = db.Column(db.String(50), default='5', index=True) # منطقه شهرداری (مثلاً ۵)
    district = db.Column(db.String(100), nullable=False, index=True) # محله (پونک، جنت‌آباد، ...)
    
    deal_type = db.Column(db.String(20), nullable=False, index=True) # sale, rent
    property_type = db.Column(db.String(30), default='apartment') # apartment, villa, commercial
    
    # Financial fields in Tomans
    deposit = db.Column(db.BigInteger, default=0) # ودیعه / رهن
    monthly_rent = db.Column(db.BigInteger, default=0) # اجاره ماهانه
    total_price = db.Column(db.BigInteger, default=0) # قیمت کل
    
    # Physical specs
    area = db.Column(db.Integer, nullable=False, index=True)
    rooms = db.Column(db.Integer, default=1)
    floor = db.Column(db.Integer, default=1)
    build_year = db.Column(db.Integer, nullable=True)
    
    # Core Amenities
    has_elevator = db.Column(db.Boolean, default=False)
    has_parking = db.Column(db.Boolean, default=False)
    has_warehouse = db.Column(db.Boolean, default=False)
    has_balcony = db.Column(db.Boolean, default=False)
    
    images_json = db.Column(db.Text, default='[]')
    phone_number = db.Column(db.String(30), nullable=True, index=True)
    is_personal_owner = db.Column(db.Boolean, default=True)
    
    published_at = db.Column(db.DateTime, nullable=True)
    extracted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

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
            'ad_code': self.ad_code,
            'source': self.source,
            'source_url': self.source_url,
            'title': self.title,
            'description': self.description,
            'city': self.city,
            'region': self.region,
            'district': self.district,
            'deal_type': self.deal_type,
            'property_type': self.property_type,
            'deposit': self.deposit,
            'monthly_rent': self.monthly_rent,
            'total_price': self.total_price,
            'area': self.area,
            'rooms': self.rooms,
            'floor': self.floor,
            'build_year': self.build_year,
            'has_elevator': self.has_elevator,
            'has_parking': self.has_parking,
            'has_warehouse': self.has_warehouse,
            'has_balcony': self.has_balcony,
            'images': self.images,
            'phone_number': self.phone_number,
            'is_personal_owner': self.is_personal_owner,
            'published_at': self.published_at.strftime('%Y-%m-%d %H:%M') if self.published_at else '',
            'extracted_at': self.extracted_at.strftime('%Y-%m-%d %H:%M') if self.extracted_at else ''
        }

class FilterProfile(db.Model):
    """
    جدول ذخیره‌سازی پروفایل‌های فیلتر هدفمند کراولر (مانند رهن و اجاره منطقه ۵)
    """
    __tablename__ = 'filter_profiles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    city = db.Column(db.String(50), default='تهران')
    region = db.Column(db.String(50), default='5') # منطقه شهرداری
    active_districts_json = db.Column(db.Text, default='[]') # لیست محله‌ها: ["پونک", "جنت‌آباد"]
    
    deal_type = db.Column(db.String(20), default='rent') # sale, rent
    min_deposit = db.Column(db.BigInteger, default=0)
    max_deposit = db.Column(db.BigInteger, default=0)
    min_rent = db.Column(db.BigInteger, default=0)
    max_rent = db.Column(db.BigInteger, default=0)
    min_price = db.Column(db.BigInteger, default=0)
    max_price = db.Column(db.BigInteger, default=0)
    
    min_area = db.Column(db.Integer, default=0)
    max_area = db.Column(db.Integer, default=0)
    min_year = db.Column(db.Integer, default=0)
    
    is_auto_crawl_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def active_districts(self):
        try:
            return json.loads(self.active_districts_json or '[]')
        except Exception:
            return []

    @active_districts.setter
    def active_districts(self, val):
        self.active_districts_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'city': self.city,
            'region': self.region,
            'active_districts': self.active_districts,
            'deal_type': self.deal_type,
            'min_deposit': self.min_deposit,
            'max_deposit': self.max_deposit,
            'min_rent': self.min_rent,
            'max_rent': self.max_rent,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'min_area': self.min_area,
            'max_area': self.max_area,
            'min_year': self.min_year,
            'is_auto_crawl_active': self.is_auto_crawl_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class CallRecord(db.Model):
    """
    جدول لاگ تماس‌های ضبط‌شده مرکز تماس VoIP و تحلیل متن و صوت
    """
    __tablename__ = 'call_records'
    id = db.Column(db.Integer, primary_key=True)
    call_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    caller_phone = db.Column(db.String(30), nullable=False, index=True)
    audio_url = db.Column(db.String(500), nullable=True)
    transcribed_text = db.Column(db.Text, nullable=True)
    extracted_criteria_json = db.Column(db.Text, default='{}')
    processing_status = db.Column(db.String(30), default='pending', index=True) # pending, transcribed, analyzed, failed
    duration_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @property
    def extracted_criteria(self):
        try:
            return json.loads(self.extracted_criteria_json or '{}')
        except Exception:
            return {}

    @extracted_criteria.setter
    def extracted_criteria(self, val):
        self.extracted_criteria_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'call_id': self.call_id,
            'caller_phone': self.caller_phone,
            'audio_url': self.audio_url,
            'transcribed_text': self.transcribed_text,
            'extracted_criteria': self.extracted_criteria,
            'processing_status': self.processing_status,
            'duration_seconds': self.duration_seconds,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class CustomerLead(db.Model):
    """
    جدول سرنخ‌های ورودی مشتریان بر اساس تحلیل هوشمند مکالمات تلفنی
    """
    __tablename__ = 'customer_leads'
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(100), default='مشتری تماس صوتی')
    deal_type = db.Column(db.String(20), default='rent', index=True) # sale, rent
    preferred_districts_json = db.Column(db.Text, default='[]') # ["پونک", "جنت‌آباد"]
    
    min_budget = db.Column(db.BigInteger, default=0)
    max_budget = db.Column(db.BigInteger, default=0)
    max_deposit = db.Column(db.BigInteger, default=0)
    max_rent = db.Column(db.BigInteger, default=0)
    min_area = db.Column(db.Integer, default=0)
    
    preferred_features_json = db.Column(db.Text, default='[]') # ["پارکینگ", "آسانسور"]
    active_messenger = db.Column(db.String(30), default='telegram') # telegram, bale, whatsapp, eitaa, rubika
    last_interaction_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    outreach_logs = db.relationship('OutreachLog', backref='lead', lazy=True, cascade="all, delete-orphan")

    @property
    def preferred_districts(self):
        try:
            return json.loads(self.preferred_districts_json or '[]')
        except Exception:
            return []

    @preferred_districts.setter
    def preferred_districts(self, val):
        self.preferred_districts_json = json.dumps(val, ensure_ascii=False)

    @property
    def preferred_features(self):
        try:
            return json.loads(self.preferred_features_json or '[]')
        except Exception:
            return []

    @preferred_features.setter
    def preferred_features(self, val):
        self.preferred_features_json = json.dumps(val, ensure_ascii=False)

    def to_dict(self):
        return {
            'id': self.id,
            'phone_number': self.phone_number,
            'full_name': self.full_name,
            'deal_type': self.deal_type,
            'preferred_districts': self.preferred_districts,
            'min_budget': self.min_budget,
            'max_budget': self.max_budget,
            'max_deposit': self.max_deposit,
            'max_rent': self.max_rent,
            'min_area': self.min_area,
            'preferred_features': self.preferred_features,
            'active_messenger': self.active_messenger,
            'last_interaction_at': self.last_interaction_at.strftime('%Y-%m-%d %H:%M') if self.last_interaction_at else '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else ''
        }

class OutreachLog(db.Model):
    """
    جدول ثبت لاگ و وضعیت ارسال‌های چندکاناله به متقاضیان (Omnichannel Logs)
    """
    __tablename__ = 'outreach_logs'
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey('customer_leads.id'), nullable=False, index=True)
    property_listing_id = db.Column(db.Integer, db.ForeignKey('property_listings.id'), nullable=True, index=True)
    property_code = db.Column(db.String(50), nullable=False)
    platform = db.Column(db.String(30), nullable=False, index=True) # telegram, bale, whatsapp, eitaa, rubika
    status = db.Column(db.String(30), default='sent', index=True) # sent, failed, delivered, retry
    server_response = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'lead_id': self.lead_id,
            'property_listing_id': self.property_listing_id,
            'property_code': self.property_code,
            'platform': self.platform,
            'status': self.status,
            'server_response': self.server_response,
            'sent_at': self.sent_at.strftime('%Y-%m-%d %H:%M') if self.sent_at else ''
        }

