from database.db import db
from database.models import Property, Client, MatchRecord

class MatchingEngine:
    """
    موتور تطبیق هوشمند دوطرفه ملک و متقاضی با محاسبه درصد سازگاری و دلایل تطابق
    """

    @staticmethod
    def calculate_match(prop: Property, client: Client):
        """
        محاسبه نمره تطابق بین یک ملک و یک متقاضی (از ۰ تا ۱۰۰)
        """
        # شرط اصلی: نوع معامله (فروش یا رهن/اجاره)
        if prop.deal_type != client.preferred_deal_type:
            return 0, []

        score = 0
        reasons = []

        # ۱. سازگاری محله و لوکیشن (تا ۳۰ نمره)
        preferred_districts = client.preferred_districts or []
        if preferred_districts:
            matched_districts = [d for d in preferred_districts if d.strip() in prop.district or prop.district in d]
            if matched_districts:
                score += 30
                reasons.append(f"تطابق دقیق منطقه: {prop.district}")
            else:
                score += 8  # حداقل امتیاز حضور در همان شهر
        else:
            score += 22  # مشتری محدودیت محله‌ای تعیین نکرده
            reasons.append("منطقه آزاد و سازگار با درخواست متقاضی")

        # ۲. سازگاری مالی و بودجه (تا ۳۵ نمره)
        if prop.deal_type == 'sale':
            total = prop.total_price or 0
            min_b = client.min_budget or 0
            max_b = client.max_budget or 0

            if max_b > 0:
                if (min_b == 0 or total >= min_b) and total <= max_b:
                    score += 35
                    reasons.append("قیمت دقیقاً در بازه بودجه متقاضی")
                elif total <= max_b * 1.12:  # تا ۱۲ درصد بالاتر، با فرض تخفیف
                    score += 25
                    reasons.append("قیمت نزدیک به بودجه متقاضی (قابل مذاکره و تخفیف)")
                elif total <= max_b * 1.25:
                    score += 10
                else:
                    score += 0
            else:
                score += 25
        else:
            # رهن و اجاره
            dep = prop.deposit or 0
            rent = prop.monthly_rent or 0
            max_dep = client.max_deposit or 0
            max_rent = client.max_rent or 0

            dep_ok = (max_dep == 0) or (dep <= max_dep * 1.15)
            rent_ok = (max_rent == 0) or (rent <= max_rent * 1.15)

            if dep_ok and rent_ok:
                score += 35
                reasons.append("ودیعه و اجاره متناسب با سقف پرداختی متقاضی")
            elif dep_ok or rent_ok:
                score += 20
                reasons.append("همخوانی نسبی ودیعه یا اجاره بها")

        # ۳. متراژ و تعداد خواب (تا ۲۰ نمره)
        min_a = client.min_area or 0
        max_a = client.max_area or 0
        prop_a = prop.area or 0

        area_match = True
        if min_a > 0 and prop_a < min_a * 0.9:
            area_match = False
        if max_a > 0 and prop_a > max_a * 1.15:
            area_match = False

        if area_match:
            score += 12
            reasons.append(f"متراژ مناسب ({prop_a} متر)")
        
        if prop.rooms >= (client.min_rooms or 1):
            score += 8
            reasons.append(f"تعداد خواب کافی ({prop.rooms} خواب)")

        # ۴. امکانات الزامی متقاضی (تا ۱۵ نمره)
        amenity_points = 0
        if client.must_have_parking:
            if prop.has_parking:
                amenity_points += 5
                reasons.append("دارای پارکینگ سندی الزامی")
            else:
                score = max(0, score - 15) # جریمه عدم وجود پارکینگ ضروری
        else:
            amenity_points += 5

        if client.must_have_elevator:
            if prop.has_elevator or prop.floor <= 1:
                amenity_points += 5
                reasons.append("دارای آسانسور یا طبقه اول")
            else:
                score = max(0, score - 15)
        else:
            amenity_points += 5

        if client.must_have_warehouse:
            if prop.has_warehouse:
                amenity_points += 5
                reasons.append("دارای انباری اختصاصی")
        else:
            amenity_points += 5

        score += amenity_points
        final_score = min(100, max(0, score))
        return final_score, reasons

    @classmethod
    def match_property_with_clients(cls, property_id, threshold=50, limit=15):
        """
        یافتن تمام مشتریان واجد شرایط و علاقه‌مند به یک ملک خاص
        """
        prop = Property.query.get(property_id)
        if not prop:
            return []

        active_clients = Client.query.filter(
            Client.preferred_deal_type == prop.deal_type,
            Client.lead_status.notin_(['contract_won', 'lost'])
        ).all()

        results = []
        for client in active_clients:
            score, reasons = cls.calculate_match(prop, client)
            if score >= threshold:
                results.append({
                    'client': client.to_dict(),
                    'score': score,
                    'reasons': reasons
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    @classmethod
    def match_client_with_properties(cls, client_id, threshold=50, limit=15):
        """
        یافتن املاک متناسب با نیازها، محله و بودجه یک متقاضی خاص
        """
        client = Client.query.get(client_id)
        if not client:
            return []

        active_props = Property.query.filter(
            Property.deal_type == client.preferred_deal_type,
            Property.status.notin_(['sold', 'archived'])
        ).all()

        results = []
        for prop in active_props:
            score, reasons = cls.calculate_match(prop, client)
            if score >= threshold:
                results.append({
                    'property': prop.to_dict(),
                    'score': score,
                    'reasons': reasons
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:limit]

    @classmethod
    def refresh_matches_for_all(cls, threshold=65):
        """
        بروزرسانی جدول matching_records برای کل پایگاه داده
        """
        props = Property.query.filter(Property.status.notin_(['sold', 'archived'])).all()
        clients = Client.query.filter(Client.lead_status.notin_(['contract_won', 'lost'])).all()

        created_count = 0
        for p in props:
            for c in clients:
                score, reasons = cls.calculate_match(p, c)
                if score >= threshold:
                    rec = MatchRecord.query.filter_by(property_id=p.id, client_id=c.id).first()
                    if not rec:
                        rec = MatchRecord(
                            property_id=p.id,
                            client_id=c.id,
                            match_score=score
                        )
                        rec.match_reasons = reasons
                        db.session.add(rec)
                        created_count += 1
                    else:
                        rec.match_score = score
                        rec.match_reasons = reasons
        db.session.commit()
        return created_count
