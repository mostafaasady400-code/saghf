"""
موتور تطبیق هوشمند یکپارچه فاز 2 (Unified Smart Matching Engine)

یک scorer واحد برای هر دو منبع:
 - Property  (فایل های داخلی CRM سقف)
 - PropertyListing (کراول دیوار/شیپور)

خروجی یکسان MatchCandidate با فیلدهای:
  score, reasons, source_type, source_id, ad_link, ...
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = 'v2.0'
DEFAULT_THRESHOLD = 45
DEFAULT_LIMIT = 15


@dataclass
class MatchCandidate:
    source_type: str
    source_id: int
    ad_code: str
    title: str
    district: str
    city: str
    deal_type: str
    area: int
    rooms: int
    floor: int
    deposit: int
    monthly_rent: int
    total_price: int
    build_year: int
    has_parking: bool
    has_elevator: bool
    has_warehouse: bool
    has_balcony: bool
    phone_number: Optional[str]
    images: list
    source_url: str
    score: int
    reasons: List[str] = field(default_factory=list)

    @property
    def ad_link_html(self) -> str:
        url = self.source_url or 'https://divar.ir'
        return (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:#fbbf24;font-weight:bold;text-decoration:underline;">لینک آگهی</a>'
        )

    def to_dict(self) -> dict:
        return {
            'source_type': self.source_type,
            'id': self.source_id,
            'ad_code': self.ad_code,
            'title': self.title,
            'district': self.district,
            'city': self.city,
            'deal_type': self.deal_type,
            'area': self.area,
            'rooms': self.rooms,
            'floor': self.floor,
            'deposit': self.deposit,
            'monthly_rent': self.monthly_rent,
            'total_price': self.total_price,
            'build_year': self.build_year,
            'has_parking': self.has_parking,
            'has_elevator': self.has_elevator,
            'has_warehouse': self.has_warehouse,
            'has_balcony': self.has_balcony,
            'phone_number': self.phone_number,
            'images': self.images,
            'source_url': self.source_url,
            'ad_link_html': self.ad_link_html,
            'match_score': self.score,
            'match_reasons': self.reasons,
        }


@dataclass
class DemandProfile:
    deal_type: str
    districts: List[str]
    max_deposit: int
    max_rent: int
    max_budget: int
    min_budget: int
    min_area: int
    max_area: int
    features: List[str]
    must_parking: bool = False
    must_elevator: bool = False
    must_warehouse: bool = False

    @classmethod
    def from_lead(cls, lead) -> 'DemandProfile':
        feats = lead.preferred_features or []
        return cls(
            deal_type=lead.deal_type or 'rent',
            districts=lead.preferred_districts or [],
            max_deposit=lead.max_deposit or 0,
            max_rent=lead.max_rent or 0,
            max_budget=lead.max_budget or 0,
            min_budget=lead.min_budget or 0,
            min_area=lead.min_area or 0,
            max_area=0,
            features=feats,
            must_parking='پارکینگ' in feats,
            must_elevator='آسانسور' in feats,
            must_warehouse='انباری' in feats,
        )

    @classmethod
    def from_client(cls, client) -> 'DemandProfile':
        return cls(
            deal_type=client.preferred_deal_type or 'rent',
            districts=client.preferred_districts or [],
            max_deposit=client.max_deposit or 0,
            max_rent=client.max_rent or 0,
            max_budget=client.max_budget or 0,
            min_budget=client.min_budget or 0,
            min_area=client.min_area or 0,
            max_area=client.max_area or 0,
            features=[],
            must_parking=bool(client.must_have_parking),
            must_elevator=bool(client.must_have_elevator),
            must_warehouse=bool(client.must_have_warehouse),
        )


class _Scorer:
    @staticmethod
    def score(candidate: dict, profile: DemandProfile):
        if candidate.get('deal_type', 'rent') != profile.deal_type:
            return 0, []

        sc = 0
        reasons = []

        # 1. بودجه (تا 35 امتیاز، تلورانس 10٪)
        if profile.deal_type == 'rent':
            dep = candidate.get('deposit', 0)
            rent = candidate.get('monthly_rent', 0)
            if profile.max_deposit > 0 and dep > profile.max_deposit * 1.10:
                return 0, []
            if profile.max_rent > 0 and rent > profile.max_rent * 1.10:
                return 0, []
            dep_ok = (profile.max_deposit == 0) or dep <= profile.max_deposit
            rent_ok = (profile.max_rent == 0) or rent <= profile.max_rent
            if dep_ok and rent_ok:
                sc += 35
                reasons.append('ودیعه و اجاره در سقف بودجه متقاضی')
            elif dep_ok or rent_ok:
                sc += 20
                reasons.append('همخوانی نسبی ودیعه یا اجاره')
            else:
                sc += 10
        else:
            price = candidate.get('total_price', 0)
            if profile.max_budget > 0 and price > profile.max_budget * 1.10:
                return 0, []
            if profile.max_budget > 0:
                if price <= profile.max_budget:
                    sc += 35
                    reasons.append('قیمت دقیقا در بازه بودجه متقاضی')
                elif price <= profile.max_budget * 1.05:
                    sc += 25
                    reasons.append('قیمت نزدیک به بودجه (قابل مذاکره)')
                else:
                    sc += 12
            else:
                sc += 25

        # 2. محله (تا 30 امتیاز)
        district = candidate.get('district') or ''
        if profile.districts:
            matched = any(d.strip() in district or district in d for d in profile.districts)
            if matched:
                sc += 30
                reasons.append(f'تطابق دقیق منطقه: {district}')
            else:
                sc += 5
                reasons.append(f'محدوده مجاور ({district})')
        else:
            sc += 20
            reasons.append(f'واقع در محدوده {district}')

        # 3. متراژ (تا 15 امتیاز، تلورانس 5٪ حداقل)
        area = candidate.get('area', 0)
        if profile.min_area > 0 and area < profile.min_area * 0.95:
            return 0, []
        max_a = profile.max_area
        area_ok = (max_a == 0) or (area <= max_a * 1.10)
        if area_ok:
            sc += 15
            reasons.append(f'متراژ مناسب ({area} مربع)')

        # 4. امکانات الزامی (تا 15 امتیاز)
        amenity_pts = 0
        if profile.must_parking:
            if candidate.get('has_parking'):
                amenity_pts += 5
                reasons.append('دارای پارکینگ الزامی')
            else:
                sc = max(0, sc - 15)
        else:
            if candidate.get('has_parking'):
                amenity_pts += 5

        if profile.must_elevator:
            floor = candidate.get('floor', 0)
            if candidate.get('has_elevator') or floor <= 1:
                amenity_pts += 5
                reasons.append('دارای آسانسور یا طبقه همکف/اول')
            else:
                sc = max(0, sc - 15)
        else:
            if candidate.get('has_elevator'):
                amenity_pts += 5

        if profile.must_warehouse:
            if candidate.get('has_warehouse'):
                amenity_pts += 5
                reasons.append('دارای انباری اختصاصی')
        else:
            if candidate.get('has_warehouse'):
                amenity_pts += 5

        sc += min(15, amenity_pts)

        # 5. نوساز (تا 5 امتیاز)
        build_year = candidate.get('build_year', 0)
        if build_year and build_year >= 1400:
            sc += 5
            reasons.append('نوساز / زیر 5 سال')
        elif build_year and build_year >= 1395:
            sc += 3

        return min(100, max(0, sc)), reasons


class UnifiedMatcher:
    """موتور تطبیق یکپارچه فاز 2."""

    @classmethod
    def match(cls, requester, threshold=DEFAULT_THRESHOLD, limit=DEFAULT_LIMIT):
        from database.models import CustomerLead, Client, Property, PropertyListing
        if isinstance(requester, CustomerLead):
            profile = DemandProfile.from_lead(requester)
        elif isinstance(requester, Client):
            profile = DemandProfile.from_client(requester)
        else:
            logger.error(f'UnifiedMatcher.match: invalid requester type {type(requester)}')
            return []

        candidates = []

        # منبع 1: PropertyListing (کراول تاییدشده مالک شخصی)
        try:
            listings = PropertyListing.query.filter_by(deal_type=profile.deal_type, is_personal_owner=True).all()
            for item in listings:
                raw = {
                    'deal_type': item.deal_type,
                    'deposit': item.deposit or 0,
                    'monthly_rent': item.monthly_rent or 0,
                    'total_price': item.total_price or 0,
                    'district': item.district or '',
                    'area': item.area or 0,
                    'build_year': item.build_year or 0,
                    'has_parking': bool(item.has_parking),
                    'has_elevator': bool(item.has_elevator),
                    'has_warehouse': bool(item.has_warehouse),
                    'floor': 0,
                }
                sc, reasons = _Scorer.score(raw, profile)
                if sc >= threshold:
                    candidates.append(MatchCandidate(
                        source_type='listing', source_id=item.id,
                        ad_code=item.ad_code or str(item.id),
                        title=item.title or 'آگهی کراول‌شده',
                        district=item.district or '', city=item.city or 'تهران',
                        deal_type=item.deal_type, area=item.area or 0, rooms=item.rooms or 0,
                        floor=0, deposit=item.deposit or 0,
                        monthly_rent=item.monthly_rent or 0, total_price=item.total_price or 0,
                        build_year=item.build_year or 0,
                        has_parking=bool(item.has_parking), has_elevator=bool(item.has_elevator),
                        has_warehouse=bool(item.has_warehouse), has_balcony=bool(item.has_balcony),
                        phone_number=item.phone_number, images=item.images or [],
                        source_url=item.source_url or 'https://divar.ir',
                        score=sc, reasons=reasons,
                    ))
        except Exception as e:
            logger.warning(f'UnifiedMatcher: PropertyListing query error: {e}')

        # منبع 2: Property (CRM داخلی مالک شخصی)
        try:
            props = Property.query.filter(
                Property.deal_type == profile.deal_type,
                Property.status.notin_(['sold', 'archived']),
                Property.is_personal_owner.is_(True)
            ).all()
            for p in props:
                raw = {
                    'deal_type': p.deal_type,
                    'deposit': p.deposit or 0,
                    'monthly_rent': p.monthly_rent or 0,
                    'total_price': p.total_price or 0,
                    'district': p.district or '',
                    'area': p.area or 0,
                    'build_year': p.build_year or 0,
                    'has_parking': bool(p.has_parking),
                    'has_elevator': bool(p.has_elevator),
                    'has_warehouse': bool(p.has_warehouse),
                    'floor': p.floor or 0,
                }
                sc, reasons = _Scorer.score(raw, profile)
                if sc >= threshold:
                    owner_phone = p.owner.phone_number if p.owner else None
                    candidates.append(MatchCandidate(
                        source_type='property', source_id=p.id,
                        ad_code=str(p.file_code or p.id),
                        title=p.title or 'ملک داخلی',
                        district=p.district or '', city=p.city or 'تهران',
                        deal_type=p.deal_type, area=p.area or 0, rooms=p.rooms or 0,
                        floor=p.floor or 0, deposit=p.deposit or 0,
                        monthly_rent=p.monthly_rent or 0, total_price=p.total_price or 0,
                        build_year=p.build_year or 0,
                        has_parking=bool(p.has_parking), has_elevator=bool(p.has_elevator),
                        has_warehouse=bool(p.has_warehouse), has_balcony=bool(p.has_balcony),
                        phone_number=owner_phone, images=p.images or [],
                        source_url=p.source_url or f'http://127.0.0.1:5000/properties/{p.id}',
                        score=sc, reasons=reasons,
                    ))
        except Exception as e:
            logger.warning(f'UnifiedMatcher: Property query error: {e}')

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:limit]

    @classmethod
    def match_property_to_clients(cls, prop, threshold=DEFAULT_THRESHOLD, limit=DEFAULT_LIMIT):
        from database.models import Client
        active_clients = Client.query.filter(
            Client.preferred_deal_type == prop.deal_type,
            Client.lead_status.notin_(['contract_won', 'lost'])
        ).all()
        raw_prop = {
            'deal_type': prop.deal_type,
            'deposit': prop.deposit or 0,
            'monthly_rent': prop.monthly_rent or 0,
            'total_price': prop.total_price or 0,
            'district': prop.district or '',
            'area': prop.area or 0,
            'build_year': prop.build_year or 0,
            'has_parking': bool(prop.has_parking),
            'has_elevator': bool(prop.has_elevator),
            'has_warehouse': bool(prop.has_warehouse),
            'floor': prop.floor or 0,
        }
        results = []
        for client in active_clients:
            profile = DemandProfile.from_client(client)
            sc, reasons = _Scorer.score(raw_prop, profile)
            if sc >= threshold:
                results.append({'client': client.to_dict(), 'score': sc, 'reasons': reasons})
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    @staticmethod
    def make_idempotency_key(lead_id, ad_code: str, platform: str) -> str:
        raw = f'{lead_id}:{ad_code}:{platform}:{date.today().isoformat()}'
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


unified_matcher = UnifiedMatcher()
