from database.db import db
from database.models import Property, Client, MatchRecord, PropertyListing
from services.unified_matcher import UnifiedMatcher, DemandProfile, _Scorer

class MatchingEngine:
    """
    موتور تطبیق هوشمند دوطرفه ملک و متقاضی با محاسبه درصد سازگاری و دلایل تطابق
    مبتنی بر UnifiedMatcher فاز ۲
    """

    @staticmethod
    def calculate_match(prop: Property, client: Client):
        """
        محاسبه نمره تطابق بین یک ملک و یک متقاضی (از ۰ تا ۱۰۰) با UnifiedMatcher Scorer
        """
        profile = DemandProfile.from_client(client)
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
            'floor': getattr(prop, 'floor', 0) or 0,
        }
        return _Scorer.score(raw_prop, profile)

    @classmethod
    def match_property_with_clients(cls, property_id, threshold=45, limit=15):
        """
        یافتن تمام مشتریان واجد شرایط و علاقه‌مند به یک ملک خاص
        """
        prop = Property.query.get(property_id)
        if not prop:
            return []
        return UnifiedMatcher.match_property_to_clients(prop, threshold=threshold, limit=limit)

    @classmethod
    def match_client_with_properties(cls, client_id, threshold=45, limit=15):
        """
        یافتن املاک متناسب با نیازها، محله و بودجه یک متقاضی خاص
        """
        client = Client.query.get(client_id)
        if not client:
            return []
        candidates = UnifiedMatcher.match(client, threshold=threshold, limit=limit)
        results = []
        for c in candidates:
            results.append({
                'property': c.to_dict(),
                'score': c.score,
                'reasons': c.reasons
            })
        return results

    @classmethod
    def refresh_matches_for_all(cls, threshold=45):
        """
        بروزرسانی جدول matching_records برای کل پایگاه داده
        صرفاً مبتنی بر فایل‌های مالک واقعی (بدون واسطه و بدون ترفندهای فایل شخصی املاک)
        """
        # فقط فایل‌های شخصی تاییدشده مالک
        props = Property.query.filter(
            Property.status.notin_(['sold', 'archived']),
            Property.is_personal_owner.is_(True)
        ).all()
        clients = Client.query.filter(Client.lead_status.notin_(['contract_won', 'lost'])).all()

        active_match_ids = set()
        created_count = 0

        for p in props:
            for c in clients:
                score, reasons = cls.calculate_match(p, c)
                if score >= threshold:
                    rec = MatchRecord.query.filter_by(property_id=p.id, client_id=c.id, source_type='property').first()
                    if not rec:
                        rec = MatchRecord(
                            source_type='property',
                            property_id=p.id,
                            client_id=c.id,
                            match_score=score,
                            algorithm_version='v2.0'
                        )
                        rec.match_reasons = reasons
                        db.session.add(rec)
                        db.session.flush()
                        created_count += 1
                    else:
                        rec.match_score = score
                        rec.match_reasons = reasons
                        rec.algorithm_version = 'v2.0'
                    active_match_ids.add(rec.id)

        # همچنین تطبیق PropertyListing های تاییدشده شخصی با کلاینت‌ها
        listings = PropertyListing.query.filter_by(is_personal_owner=True).all()
        for item in listings:
            raw_item = {
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
            for c in clients:
                profile = DemandProfile.from_client(c)
                score, reasons = _Scorer.score(raw_item, profile)
                if score >= threshold:
                    rec = MatchRecord.query.filter_by(listing_id=item.id, client_id=c.id, source_type='listing').first()
                    if not rec:
                        rec = MatchRecord(
                            source_type='listing',
                            listing_id=item.id,
                            client_id=c.id,
                            match_score=score,
                            algorithm_version='v2.0'
                        )
                        rec.match_reasons = reasons
                        db.session.add(rec)
                        db.session.flush()
                        created_count += 1
                    else:
                        rec.match_score = score
                        rec.match_reasons = reasons
                        rec.algorithm_version = 'v2.0'
                    active_match_ids.add(rec.id)

        # پاکسازی و حذف رکوردهای تطابق تاریخ‌گذشته، نامعتبر یا وابسته به واسطه‌ها
        stale_records = MatchRecord.query.filter(MatchRecord.id.notin_(active_match_ids)).all()
        for stale in stale_records:
            db.session.delete(stale)

        db.session.commit()
        return len(active_match_ids)
