class PropertyScorer:
    """
    سیستم ارزش‌گذاری و نمره‌دهی هوشمند به کیفیت و قابلیت فروش فایل‌های ملکی
    """
    @staticmethod
    def calculate_score(prop):
        score = 65  # امتیاز پایه

        # امتیاز امکانات کلیدی
        if prop.has_parking:
            score += 8
        if prop.has_elevator:
            score += 7
        if prop.has_warehouse:
            score += 4
        if prop.has_balcony:
            score += 3

        # سال ساخت
        if prop.build_year:
            if prop.build_year >= 1401:
                score += 8  # نوساز یا زیر ۳ سال
            elif prop.build_year >= 1396:
                score += 5  # زیر ۸ سال
            elif prop.build_year <= 1385:
                score -= 6  # قدیمی ساخت

        # طبقه مناسب
        if prop.floor in [2, 3, 4]:
            score += 4
        elif prop.floor == 1 or (prop.floor >= 6 and not prop.has_elevator):
            score -= 5

        # تصاویر و مستندات
        if prop.images and len(prop.images) > 0:
            score += 5

        # بررسی امتیاز نهایی
        return min(99, max(50, score))
