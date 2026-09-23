from typing import Dict, Any, List, Tuple, Optional

class PropertyScorer:
    """
    موتور امتیازدهی و رتبه‌بندی هوشمند سقف (Scoring & Ranking Engine)
    ارزیابی کیفیت فایل‌ها و انطباق چندعاملی با نیازهای متقاضیان (Match Score از ۰ تا ۱۰۰)
    """

    @staticmethod
    def calculate_score(prop: Any) -> int:
        """
        ارزیابی کیفیت ذاتی، مشخصات ساختمانی و پتانسیل تجاری ملک
        """
        def get_val(key, default=None):
            if isinstance(prop, dict):
                return prop.get(key, default)
            return getattr(prop, key, default)

        score = 65  # امتیاز پایه

        # امتیاز امکانات کلیدی
        if get_val('has_parking'):
            score += 8
        if get_val('has_elevator'):
            score += 7
        if get_val('has_warehouse'):
            score += 4
        if get_val('has_balcony'):
            score += 3

        # سال ساخت
        byear = get_val('build_year')
        if byear:
            if byear >= 1401:
                score += 8  # نوساز یا زیر ۳ سال
            elif byear >= 1396:
                score += 5  # زیر ۸ سال
            elif byear <= 1385:
                score -= 6  # قدیمی ساخت

        # طبقه مناسب
        floor = get_val('floor')
        if floor in [2, 3, 4]:
            score += 4
        elif floor == 1 or (floor and floor >= 6 and not get_val('has_elevator')):
            score -= 5

        # تصاویر و مستندات
        images = get_val('images')
        if images and len(images) > 0:
            score += 5

        return min(99, max(50, score))

    @classmethod
    def calculate_match_score(cls, prop: Any, criteria: Dict[str, Any]) -> Tuple[int, List[str]]:
        """
        سیستم وزن‌دهی و امتیازدهی هوشمند بر اساس نیاز متقاضی (Match Score از ۰ تا ۱۰۰):
        - تطابق منطقه و محله (وزن ۳۵)
        - تطابق با بودجه رهن و اجاره یا قیمت کل با تلورانس تعریف‌شده (وزن ۳۵)
        - تطابق متراژ و تعداد خواب (وزن ۱۵)
        - تطابق امکانات الزامی مانند پارکینگ و آسانسور (وزن ۱۵)
        """
        def get_val(key, default=None):
            if isinstance(prop, dict):
                return prop.get(key, default)
            return getattr(prop, key, default)

        p_deal = (get_val('deal_type') or 'sale').lower().strip()
        c_deal = (criteria.get('deal_type') or 'all').lower().strip()
        if c_deal not in ['all', '']:
            if p_deal != c_deal:
                return 0, ['عدم تطابق نوع معامله (فروش/اجاره)']

        score = 0
        reasons: List[str] = []

        # ۱. تطابق منطقه و محله (وزن ۳۵ نمره)
        req_districts = criteria.get('districts') or []
        req_district = criteria.get('district')
        if req_district and req_district not in ['all', '']:
            req_districts = list(req_districts) + [req_district]
        
        # پاکسازی محله‌های درخواستی
        clean_districts = [
            str(d).strip() for d in req_districts 
            if d and str(d).strip() not in ['all', 'تهران', 'نامشخص', 'کل شهر', 'همه']
        ]

        p_district = str(get_val('district') or 'تهران').strip()

        if clean_districts:
            exact_match = any(d in p_district or p_district in d for d in clean_districts)
            if exact_match:
                score += 35
                reasons.append(f"تطابق دقیق منطقه و محله ({p_district})")
            else:
                reasons.append(f"عدم تطابق منطقه (متقاضی: {', '.join(clean_districts)} | ملک: {p_district})")
        else:
            score += 25
            reasons.append("جستجوی سراسری شهر (منطقه باز)")

        # اولویت طلایی و امتیاز ویژه مالک مستقیم و شخصی
        p_desc = f"{get_val('title') or ''} {get_val('description') or ''}".lower()
        if any(m in p_desc for m in ['مالک هستم', 'مالکم', 'من مالک', 'بی واسطه', 'بی‌واسطه', 'بدون واسطه', 'مستقیم از مالک', 'تماس با مالک']):
            score += 20
            reasons.append("👑 اولویت طلایی: اعلام صریح مالکیت مستقیم و شخصی (بی‌واسطه)")

        # ۲. تطابق مالی و بودجه با تلورانس (وزن ۳۵ نمره)
        if p_deal == 'sale':
            total = int(get_val('total_price') or 0)
            min_b = criteria.get('min_price')
            max_b = criteria.get('max_price')

            if max_b and max_b > 0:
                min_b = min_b or 0
                if min_b <= total <= max_b:
                    score += 35
                    reasons.append("قیمت دقیقاً در بازه بودجه خریدار")
                elif total <= max_b * 1.10:
                    score += 25
                    reasons.append("قیمت نزدیک به بودجه خریدار (با ۱۰٪ تلورانس و تخفیف)")
                elif total <= max_b * 1.20:
                    score += 15
                    reasons.append("قیمت با تلورانس ۲۰٪ سازگار")
                else:
                    score += 5
            else:
                score += 25
                reasons.append("بودجه باز و بدون محدودیت سقف")
        else:
            # رهن و اجاره
            dep = int(get_val('deposit') or 0)
            rent = int(get_val('monthly_rent') or 0)
            max_dep = criteria.get('max_deposit')
            max_rent = criteria.get('max_rent')

            budget_pts = 0
            if max_dep and max_dep > 0:
                if dep <= max_dep:
                    budget_pts += 18
                    reasons.append("ودیعه منطبق بر سقف بودجه")
                elif dep <= max_dep * 1.15:
                    budget_pts += 12
                    reasons.append("ودیعه با تلورانس ۱۵٪ قابل مذاکره")
                else:
                    budget_pts += 4
            else:
                budget_pts += 15

            if max_rent and max_rent > 0:
                if rent <= max_rent:
                    budget_pts += 17
                    reasons.append("اجاره ماهانه منطبق بر سقف بودجه")
                elif rent <= max_rent * 1.15:
                    budget_pts += 11
                    reasons.append("اجاره بها با تلورانس ۱۵٪ قابل مذاکره")
                else:
                    budget_pts += 3
            else:
                budget_pts += 15

            score += min(35, budget_pts)

        # ۳. تطابق متراژ و تعداد خواب (وزن ۱۵ نمره)
        area = int(get_val('area') or 0)
        min_a = criteria.get('min_area')
        max_a = criteria.get('max_area')
        area_pts = 8
        if min_a and min_a > 0:
            if area >= min_a * 0.9:
                area_pts = 10
                reasons.append(f"متراژ متناسب ({area} متر)")
            else:
                area_pts = 2
        score += area_pts

        rooms = int(get_val('rooms') or 1)
        req_rooms = criteria.get('rooms')
        if req_rooms and int(req_rooms) > 0:
            if rooms >= int(req_rooms):
                score += 5
                reasons.append(f"تعداد خواب مورد انتظار ({rooms} خواب)")
            else:
                score += 1
        else:
            score += 4

        # ۴. امکانات الزامی و رفاهی (وزن ۱۵ نمره)
        amenity_pts = 0
        req_parking = criteria.get('has_parking')
        p_park = bool(get_val('has_parking'))
        if req_parking in [True, 1, '1']:
            if p_park:
                amenity_pts += 5
                reasons.append("دارای پارکینگ سندی الزامی")
            else:
                score = max(0, score - 15)  # جریمه کسری پارکینگ الزامی
        else:
            if p_park:
                amenity_pts += 3

        req_elev = criteria.get('has_elevator')
        p_elev = bool(get_val('has_elevator'))
        p_floor = int(get_val('floor') or 1)
        if req_elev in [True, 1, '1']:
            if p_elev or p_floor <= 1:
                amenity_pts += 5
                reasons.append("دارای آسانسور یا طبقه همکف/اول")
            else:
                score = max(0, score - 10)  # جریمه کسری آسانسور
        else:
            if p_elev:
                amenity_pts += 3

        if bool(get_val('has_warehouse')):
            amenity_pts += 2
        if bool(get_val('has_balcony')):
            amenity_pts += 2

        score += min(15, amenity_pts)

        # نمره کیفیت ساختمانی به عنوان بونوس تا سقف ۱۰۰
        quality = cls.calculate_score(prop)
        if quality >= 85:
            score += 3

        final_score = min(100, max(0, score))
        return final_score, reasons

    @classmethod
    def rank_properties(cls, properties: List[Any], criteria: Optional[Dict[str, Any]] = None) -> List[Tuple[Any, int, List[str]]]:
        """
        محاسبه نمره تطابق تمامی آگهی‌ها و مرتب‌سازی نزولی خروجی از بیشترین امتیاز تا کمترین امتیاز
        """
        criteria = criteria or {}
        ranked = []
        for p in properties:
            score, reasons = cls.calculate_match_score(p, criteria)
            ranked.append((p, score, reasons))

        # سورت نزولی بر اساس بیشترین امتیاز
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    @classmethod
    def sort_properties(cls, properties: List[Any], criteria: Optional[Dict[str, Any]] = None) -> List[Any]:
        """
        مرتب‌سازی لیست اشیاء ملک و افزودن اتریبیوت‌های match_score و match_reasons به هر شیء
        """
        criteria = criteria or {}
        scored_list = []
        for p in properties:
            score, reasons = cls.calculate_match_score(p, criteria)
            if isinstance(p, dict):
                p['match_score'] = score
                p['match_reasons'] = reasons
            else:
                try:
                    setattr(p, 'match_score', score)
                    setattr(p, 'match_reasons', reasons)
                except Exception:
                    pass
            scored_list.append((p, score))

        scored_list.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in scored_list]
