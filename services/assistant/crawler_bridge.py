"""
پل اتصال دستیار هوش مصنوعی به پایپلاین کرولر و دیتابیس آگهی‌های آنلاین (AI → Crawler Bridge)
وظایف و الزامات:
۱. استخراج قصد کاربر و بازه پویا (بازه اصلی ۷۵-۹۰ و بازه پیشنهادی ۷۰-۱۰۰ برای ۸۰ متری)
۲. فیلتر سخت‌گیرانه مالکین شخصی و رد قطعی واسطه‌ها (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار)
۳. اولویت‌بندی زمانی دقیق در بازه ۲۴ ساعت:
   - اولویت ۱: ۲ تا ۳۰ دقیقه گذشته (لحظه‌ای و تازه)
   - اولویت ۲: تا ۲۴ ساعت گذشته
   - حذف تمام فایل‌های قدیمی‌تر از ۲۴ ساعت
۴. ساختار خروجی دو بخشی:
   - بخش اول: ۱۵ تا ۲۰ آگهی دقیق درخواستی، سورت‌شده از جدیدترین به قدیمی‌ترین
   - بخش دوم: ۵ تا ۱۰ پیشنهاد هوشمند در همان منطقه با دلیل کوتاه پیشنهاد
۵. ارائه فیلدهای ضروری: شماره تماس مستقیم مالک، زمان دقیق انتشار، لینک مستقیم و تگ <a> با عنوان «لینک آگهی»
"""

import re
import logging
import threading
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_, func

from database.db import db
from database.models import AccessibleListing
from crawler.publisher_classifier import EXPLICIT_AGENCY, LIKELY_INTERMEDIARY, LIKELY_OWNER, UNKNOWN
from crawler.owner_filter import extract_phone_number
from services.nlp_extractor import PropertyLeadNLPExtractor, normalize_persian_text

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# کلمات ممنوعه برای فیلتر سخت‌گیرانه واسطه‌ها                                  #
# --------------------------------------------------------------------------- #
AGENCY_FORBIDDEN_WORDS = [
    'املاک', 'مسکن', 'خانه', 'مشاور', 'کارشناس', 'کمیسیون', 'همکار',
    'آژانس', 'دپارتمان', 'بنگاه', 'همکاری', 'مشاوره', 'هلدینگ',
]


def _compute_area_ranges(min_area: int = 0, max_area: int = 0) -> Tuple[int, int, int, int]:
    """
    محاسبه بازه اصلی و بازه پیشنهادی مکمل بر اساس متراژ هدف:
    - بازه اصلی: متراژ تقریبی با تلورانس نزدیک (مثلاً ۷۵ تا ۹۰ متر برای ۸۰ متری).
    - بازه پیشنهادی مکمل: تلورانس بازتر برای پیشنهادات هوشمند (مثلاً ۷۰ تا ۱۰۰ متر برای ۸۰ متری).
    """
    if min_area > 0 and max_area > 0 and min_area != max_area:
        tight_lo = min_area
        tight_hi = max_area
        wide_lo = max(1, int(round(min_area * 0.88)))
        wide_hi = int(round(max_area * 1.15))
        return tight_lo, tight_hi, wide_lo, wide_hi

    target_area = min_area or max_area or 0
    if target_area <= 0:
        return 0, 0, 0, 0

    # برای متراژ هدف ۸۰ متر: بازه اصلی ۷۵ تا ۹۰، بازه مکمل ۷۰ تا ۱۰۰
    tight_lo = max(1, int(round(target_area * 0.9375)))
    tight_hi = int(round(target_area * 1.125))
    wide_lo = max(1, int(round(target_area * 0.875)))
    wide_hi = int(round(target_area * 1.25))
    return tight_lo, tight_hi, wide_lo, wide_hi


class CrawlerBridge:
    """اتصال مستقیم دستیار هوش مصنوعی سقف به دیتابیس کرولر (AccessibleListing)."""

    # -----------------------------------------------------------------------
    # نقطه ورود اصلی — فراخوانی شده از gateway / tool_call
    # -----------------------------------------------------------------------
    @classmethod
    def search_live_listings(
        cls,
        deal_type: str,
        districts: Optional[List[str]] = None,
        min_area: int = 0,
        max_area: int = 0,
        rooms: Optional[int] = None,
        max_price: int = 0,
        max_deposit: int = 0,
        max_rent: int = 0,
        window_hours: int = 168,  # آرشیو کامل ۷ روز اخیر (۱۶۸ ساعت)
        target_total: int = 30,
        refresh_live: bool = True,
    ) -> Dict[str, Any]:
        """
        جستجوی زنده و اتصال فوری به کرولر دیوار و آرشیو ۷ روز اخیر:
        ۱. اجرای بلادرنگ استخراج آنلاین (On-Demand Live Scraping) به محض استعلام کاربر
        ۲. پوشش کامل آرشیو یک هفته اخیر (۷ روز گذشته) از هر دو منبع Property و AccessibleListing
        ۳. تفکیک قطعی نوع معامله (خرید/فروش در برابر رهن/اجاره) بدون کوچکترین تداخل
        ۴. تفکیک ساختار به دو بخش: ۱۵ تا ۲۰ آگهی دقیق + ۵ تا ۱۰ پیشنهاد هوشمند (مجموعاً ۲۰ تا ۳۰ آگهی)
        """
        clean_deal = 'rent' if deal_type in ('rent', 'رهن', 'اجاره') else 'sale'

        # ۱. اجرای فوری و در لحظه استخراج زنده از دیوار (On-Demand / Real-time Scraping)
        # Only the authenticated crawler can perform a live refresh.
        live_refresh = cls._refresh_from_authenticated_crawler(
            deal_type=clean_deal,
            districts=districts,
            min_area=min_area,
            max_area=max_area,
            rooms=rooms,
            max_price=max_price,
            max_deposit=max_deposit,
            max_rent=max_rent,
        ) if refresh_live else {"status": "skipped", "reason": "explicitly_disabled"}

        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)
        fresh_cutoff = now - timedelta(minutes=30)

        # محاسبه بازه‌های متراژ پویا
        target_area = min_area or max_area or 0
        tight_lo, tight_hi, wide_lo, wide_hi = _compute_area_ranges(min_area=min_area, max_area=max_area)

        exact_items: List[Dict[str, Any]] = []
        suggest_items: List[Dict[str, Any]] = []
        seen_source_keys = set()

        # ۲.۱ واکشی از جدول AccessibleListing
        base_acc_q = cls._base_owner_query(clean_deal, cutoff)
        base_acc_q = cls._apply_financial_filters(base_acc_q, clean_deal, max_price, max_deposit, max_rent)
        base_acc_q = cls._apply_district_filter(base_acc_q, districts)

        acc_exact_q = base_acc_q
        if tight_lo > 0:
            acc_exact_q = acc_exact_q.filter(AccessibleListing.area >= tight_lo, AccessibleListing.area <= tight_hi)
        if rooms and rooms > 0:
            acc_exact_q = acc_exact_q.filter(AccessibleListing.rooms == rooms)

        raw_acc_exact = acc_exact_q.order_by(AccessibleListing.published_at.desc().nullslast(), AccessibleListing.first_seen_at.desc()).limit(30).all()
        for l in raw_acc_exact:
            if cls._is_clean_personal_listing(l):
                s_key = (l.source_id or l.source_url or str(l.id))
                if s_key not in seen_source_keys:
                    seen_source_keys.add(s_key)
                    exact_items.append(cls._format_listing(l, now, fresh_cutoff, is_suggestion=False, target_area=target_area))
                    if len(exact_items) >= 20:
                        break

        acc_sug_q = base_acc_q
        if wide_lo > 0:
            acc_sug_q = acc_sug_q.filter(AccessibleListing.area >= wide_lo, AccessibleListing.area <= wide_hi)
        if rooms and rooms > 0:
            acc_sug_q = acc_sug_q.filter(AccessibleListing.rooms == rooms)

        raw_acc_sug = acc_sug_q.order_by(AccessibleListing.published_at.desc().nullslast(), AccessibleListing.first_seen_at.desc()).limit(20).all()
        for l in raw_acc_sug:
            if cls._is_clean_personal_listing(l):
                s_key = (l.source_id or l.source_url or str(l.id))
                if s_key not in seen_source_keys:
                    seen_source_keys.add(s_key)
                    suggest_items.append(cls._format_listing(l, now, fresh_cutoff, is_suggestion=True, target_area=target_area))
                    if len(suggest_items) >= 10:
                        break

        # AccessibleListing is the authoritative source for publication time.
        # CRM created_at is not evidence of recent publication.

        # مرتب‌سازی زمانی دقیق: اولویت ۱ (لحظاتی پیش تا ۳۰ دقیقه)، سپس اولویت ۲ (ساعات اخیر تا ۷ روز گذشته)
        exact_items.sort(key=lambda x: (x.get('priority', 2), -(x.get('_pub_timestamp') or 0)))
        suggest_items.sort(key=lambda x: (x.get('priority', 2), -(x.get('_pub_timestamp') or 0)))

        final_exact = exact_items[:20]
        final_suggest = suggest_items[:10]

        return {
            'exact': final_exact,
            'suggested': final_suggest,
            'meta': {
                'total_exact': len(final_exact),
                'total_suggested': len(final_suggest),
                'total_listings': len(final_exact) + len(final_suggest),
                'window_hours': window_hours,
                'cutoff': cutoff.isoformat(),
                'deal_type': clean_deal,
                'transaction_type': 'rent' if clean_deal == 'rent' else 'buy',
                'districts': districts or [],
                'target_area': target_area,
                'tight_range': [tight_lo, tight_hi] if tight_lo > 0 else None,
                'wide_range': [wide_lo, wide_hi] if wide_lo > 0 else None,
                'live_refresh': live_refresh,
                'is_live': False,  # Archive results are never collectively labelled live.
                'data_source': 'persisted_archive',
            }
        }

    @classmethod
    def _refresh_from_authenticated_crawler(cls, **criteria: Any) -> Dict[str, Any]:
        """Run the real crawler before querying results; never include secrets in errors."""
        try:
            from flask import current_app, has_app_context
            if has_app_context() and current_app.config.get("TESTING"):
                return {"status": "skipped", "reason": "testing"}

            from services.search_run_service import SearchRunService
            normalized = {
                "city": "tehran",
                "deal_type": criteria.get("deal_type"),
                "property_type": "apartment",
                "districts": criteria.get("districts") or [],
                "min_area": criteria.get("min_area") or None,
                "max_area": criteria.get("max_area") or None,
                "rooms": criteria.get("rooms") or None,
                "max_price": criteria.get("max_price") or None,
                "max_deposit": criteria.get("max_deposit") or None,
                "max_rent": criteria.get("max_rent") or None,
                "window_hours": 24,
            }
            run = SearchRunService.create_run(normalized, query_text="جست‌وجوی زنده دستیار")
            budget = max(10.0, min(120.0, float(os.getenv("DIVAR_LIVE_SEARCH_TIMEOUT", "45"))))
            run = SearchRunService.execute(run.run_id, max_runtime_seconds=budget)
            report = dict(run.report or {})
            source_status = run.source_status or "unknown"
            if source_status == "authenticated_session_unavailable":
                return {"status": "failed", "reason": source_status, "run_id": run.run_id}
            pages = int(report.get("pages_traversed") or 0)
            if pages <= 0 and source_status not in {"completed", "time_budget_reached"}:
                return {"status": "failed", "reason": source_status, "run_id": run.run_id}
            status = "completed" if source_status == "completed" else "partial"
            return {
                "status": status,
                "reason": source_status,
                "run_id": run.run_id,
                "pages_traversed": pages,
                "coverage_status": run.coverage_status,
            }
        except Exception as exc:
            logger.warning("[CrawlerBridge] live refresh failed: %s", type(exc).__name__)
            return {"status": "failed", "reason": type(exc).__name__}

    # -----------------------------------------------------------------------
    # بررسی ۱۰۰٪ حذف واسطه‌ها با حفظ مالکین واقعی (خلط نشدن سلب مسئولیت)
    # -----------------------------------------------------------------------
    @classmethod
    def _is_clean_personal_listing(cls, listing: AccessibleListing) -> bool:
        """بررسی دقیق حذف واسطه‌ها با لحاظ معافیت سلب‌مسئولیت مالکین شخصی (مانند: مشاورین تماس نگیرند)"""
        desc = (listing.description or '').lower()
        if not desc:
            return False  # Missing details cannot pass the intermediary gate.

        from crawler.owner_filter import OwnerFilter
        return OwnerFilter.evaluate(platform="divar", title=listing.title or "", description=listing.description or "").is_personal

    # -----------------------------------------------------------------------
    # کوئری‌ پایه مالک‌محور با فیلتر ۲۴ ساعت و حذف واسطه
    # -----------------------------------------------------------------------
    @classmethod
    def _base_owner_query(cls, deal_type: str, cutoff: datetime):
        """ساخت کوئری پایه: فقط مالکین شخصی، بازه ۲۴ ساعت، حذف قطعی واسطه‌ها."""
        import re
        effective_owner = or_(
            AccessibleListing.manual_publisher_category == LIKELY_OWNER,
            and_(
                AccessibleListing.manual_publisher_category.is_(None),
                AccessibleListing.publisher_category == LIKELY_OWNER,
            ),
        )

        earliest_val = func.coalesce(AccessibleListing.publication_earliest_at, AccessibleListing.published_at)
        latest_val = func.coalesce(AccessibleListing.publication_latest_at, AccessibleListing.published_at)
        q = AccessibleListing.query.filter(
            effective_owner,
            earliest_val >= cutoff,
            latest_val <= datetime.utcnow(),
        )

        if deal_type in ('sale', 'buy'):
            q = q.filter(
                (AccessibleListing.deal_type.in_(['sale', 'buy'])) | (AccessibleListing.transaction_type == 'buy'),
                (AccessibleListing.deposit == 0) | (AccessibleListing.deposit.is_(None)),
                (AccessibleListing.monthly_rent == 0) | (AccessibleListing.monthly_rent.is_(None))
            )
        elif deal_type in ('rent', 'رهن', 'اجاره'):
            q = q.filter(
                (AccessibleListing.deal_type == 'rent') | (AccessibleListing.transaction_type == 'rent'),
                (AccessibleListing.total_price == 0) | (AccessibleListing.total_price.is_(None)),
                (AccessibleListing.deposit > 0) | (AccessibleListing.monthly_rent > 0)
            )

        # Apply the shared word-boundary owner guard after retrieval. SQL
        # substring filtering wrongly rejects words such as آشپزخانه/صاحبخانه.

        return q

    # -----------------------------------------------------------------------
    # فیلترهای مالی
    # -----------------------------------------------------------------------
    @classmethod
    def _apply_financial_filters(cls, q, deal_type: str, max_price: int, max_deposit: int, max_rent: int):
        if deal_type == 'sale' and max_price > 0:
            q = q.filter(AccessibleListing.total_price <= int(max_price * 1.15))
        elif deal_type == 'rent':
            if max_deposit > 0:
                q = q.filter(AccessibleListing.deposit <= int(max_deposit * 1.2))
            if max_rent > 0:
                q = q.filter(AccessibleListing.monthly_rent <= int(max_rent * 1.2))
        return q

    # -----------------------------------------------------------------------
    # فیلتر محله‌ها
    # -----------------------------------------------------------------------
    @classmethod
    def _apply_district_filter(cls, q, districts: Optional[List[str]]):
        if not districts:
            return q
        district_filters = []
        for d in districts:
            clean = d.replace('منطقه', '').strip()
            district_filters.extend([
                AccessibleListing.district.ilike(f'%{d}%'),
                AccessibleListing.district.ilike(f'%{clean}%'),
                AccessibleListing.title.ilike(f'%{d}%'),
            ])
        return q.filter(or_(*district_filters))

    # -----------------------------------------------------------------------
    # فرمت یک آگهی برای نمایش در چت دستیار
    # -----------------------------------------------------------------------
    @classmethod
    def _format_listing(
        cls,
        listing: AccessibleListing,
        now: datetime,
        fresh_cutoff: datetime,
        is_suggestion: bool = False,
        target_area: int = 0,
    ) -> Dict[str, Any]:
        """تبدیل رکورد AccessibleListing به ساختار غنی و ساختاریافته دستیار."""
        pub_time = listing.published_at
        pub_ts = pub_time.timestamp() if pub_time else 0.0

        # رتبه‌بندی زمانی و اولویت‌دهی
        if pub_time:
            delta = now - pub_time
            seconds = max(0.0, delta.total_seconds())
            minutes = int(seconds / 60)
            if seconds <= 1800:  # ۲ تا ۳۰ دقیقه گذشته (و لحظاتی پیش)
                priority = 1
                is_fresh = True
                if minutes < 2:
                    time_label = '🔴 لحظاتی پیش'
                else:
                    time_label = f'🟠 {minutes} دقیقه پیش'
            elif seconds <= 86400:  # تا ۲۴ ساعت گذشته
                priority = 2
                is_fresh = False
                if minutes < 60:
                    time_label = f'🟡 {minutes} دقیقه پیش'
                else:
                    hours = minutes // 60
                    time_label = f'🟢 {hours} ساعت پیش'
            else:
                priority = 3
                is_fresh = False
                time_label = listing.publication_source_text or pub_time.strftime('%Y/%m/%d %H:%M')
        else:
            priority = 2
            is_fresh = False
            time_label = listing.publication_source_text or 'نامشخص'

        # قیمت
        if listing.deal_type == 'sale':
            if listing.total_price:
                price_str = f"قیمت: {listing.total_price / 1_000_000_000:.1f} میلیارد تومان"
            else:
                price_str = "قیمت: توافقی"
        else:
            dep_str = f"{int(listing.deposit / 1_000_000):,} م" if listing.deposit else "توافقی"
            rent_str = f"{int(listing.monthly_rent / 1_000_000):,} م" if listing.monthly_rent else "توافقی"
            if listing.monthly_rent == 0 and listing.deposit and listing.deposit > 0:
                price_str = f"رهن کامل: {dep_str} تومان"
            else:
                price_str = f"ودیعه: {dep_str} | اجاره: {rent_str}"

        # استخراج شماره تماس مستقیم مالک
        extracted_phone = extract_phone_number(listing.description or '') or extract_phone_number(listing.title or '')
        if not extracted_phone and listing.source_id:
            try:
                from database.models import Property
                prop = Property.query.filter_by(source_id=listing.source_id).first()
                if prop and prop.owner and prop.owner.phone_number:
                    extracted_phone = prop.owner.phone_number
            except Exception:
                pass

        owner_phone = extracted_phone or 'موجود در لینک آگهی'

        # تصویر بهینه‌شده
        images = listing.images or []
        thumb = images[0] if images else '/static/images/placeholder.png'

        # دلیل پیشنهاد هوشمند برای بخش دوم
        suggestion_reason = ''
        if is_suggestion and target_area > 0:
            area_val = listing.area or 0
            if area_val < target_area:
                suggestion_reason = f'متراژ نزدیک ({int(area_val)} متر) با احتمال نقشه عالی و هزینه مناسب‌تر'
            elif area_val > target_area:
                suggestion_reason = f'متراژ بزرگ‌تر ({int(area_val)} متر) با نورگیری و فضای وسیع‌تر'
            else:
                suggestion_reason = 'متناسب با شرایط درخواستی در همان منطقه با امتیاز بالا'

        # تگ مستقیم <a> با عنوان «لینک آگهی» (طبق منشور پروژه بند ۴.۱)
        ad_link_html = f'<a href="{listing.source_url}" target="_blank" rel="noopener noreferrer">لینک آگهی</a>'

        return {
            'id': listing.id,
            'source_id': listing.source_id,
            'source_url': listing.source_url,
            'link_tag': ad_link_html,
            'ad_link_html': ad_link_html,
            'owner_phone': owner_phone,
            'contact_phone': owner_phone,
            'title': listing.title,
            'district': listing.district or 'نامشخص',
            'area': listing.area,
            'rooms': listing.rooms,
            'deal_type': listing.deal_type,
            'price_str': price_str,
            'total_price': listing.total_price,
            'deposit': listing.deposit,
            'monthly_rent': listing.monthly_rent,
            'image_url': thumb,
            'images': images[:3],
            'time_label': time_label,
            'is_fresh': is_fresh,
            'priority': priority,
            '_pub_timestamp': pub_ts,
            'publisher_reason': listing.publisher_reason or 'مالک مستقیم',
            'publisher_confidence': listing.publisher_confidence,
            'is_suggestion': is_suggestion,
            'suggestion_reason': suggestion_reason,
            'published_at': pub_time.isoformat() if pub_time else None,
            'published_at_exact': pub_time.strftime('%Y-%m-%d %H:%M:%S') if pub_time else None,
            'publication_accuracy': listing.publication_accuracy,
            'detail_url': f'/crawler/listings/{listing.id}' if listing.id else listing.source_url,
        }

    @classmethod
    def _format_property(
        cls,
        prop: Any,
        now: datetime,
        fresh_cutoff: datetime,
        is_suggestion: bool = False,
        target_area: int = 0,
    ) -> Dict[str, Any]:
        """تبدیل رکورد جدول جامع Property سقف به ساختار استاندارد دستیار هوشمند."""
        created_time = prop.created_at
        pub_ts = created_time.timestamp() if created_time else 0.0

        if created_time:
            delta = now - created_time
            seconds = max(0.0, delta.total_seconds())
            minutes = int(seconds / 60)
            if seconds <= 1800:
                priority = 1
                is_fresh = True
                time_label = '🔴 لحظاتی پیش' if minutes < 2 else f'🟠 {minutes} دقیقه پیش'
            elif seconds <= 86400:
                priority = 2
                is_fresh = False
                hours = minutes // 60
                time_label = f'🟡 {minutes} دقیقه پیش' if minutes < 60 else f'🟢 {hours} ساعت پیش'
            else:
                priority = 3
                is_fresh = False
                days = int(seconds / 86400)
                time_label = f'{days} روز پیش'
        else:
            priority = 2
            is_fresh = False
            time_label = prop.time_ago or 'به تازگی'

        if prop.deal_type in ('sale', 'buy'):
            price_str = f"قیمت: {prop.total_price / 1_000_000_000:.1f} میلیارد تومان" if prop.total_price else "قیمت: توافقی"
        else:
            dep_str = f"{int(prop.deposit / 1_000_000):,} م" if prop.deposit else "توافقی"
            rent_str = f"{int(prop.monthly_rent / 1_000_000):,} م" if prop.monthly_rent else "توافقی"
            price_str = f"رهن کامل: {dep_str} تومان" if prop.monthly_rent == 0 and prop.deposit else f"ودیعه: {dep_str} | اجاره: {rent_str}"

        owner_phone = prop.owner.phone_number if (prop.owner and prop.owner.phone_number) else (extract_phone_number(prop.description or '') or 'ثبت در سیستم سقف')

        images = prop.images or []
        thumb = images[0] if images else '/static/images/placeholder.png'

        suggestion_reason = ''
        if is_suggestion and target_area > 0:
            area_val = prop.area or 0
            if area_val < target_area:
                suggestion_reason = f'متراژ نزدیک ({int(area_val)} متر) با احتمال نقشه عالی و قیمت منصفانه'
            elif area_val > target_area:
                suggestion_reason = f'متراژ بزرگ‌تر ({int(area_val)} متر) با نورگیر عالی و فضای بیشتر'
            else:
                suggestion_reason = 'متناسب با شرایط درخواستی در همان منطقه با امتیاز بالا'

        source_url = prop.source_url or f'/properties/{prop.id}'
        ad_link_html = f'<a href="{source_url}" target="_blank" rel="noopener noreferrer">لینک آگهی</a>'

        return {
            'id': prop.id,
            'source_id': prop.source_id,
            'source_url': source_url,
            'link_tag': ad_link_html,
            'ad_link_html': ad_link_html,
            'owner_phone': owner_phone,
            'contact_phone': owner_phone,
            'title': prop.title,
            'district': prop.district or 'تهران',
            'area': prop.area,
            'rooms': prop.rooms,
            'deal_type': prop.deal_type,
            'transaction_type': prop.transaction_type or ('buy' if prop.deal_type in ('sale', 'buy') else 'rent'),
            'price_str': price_str,
            'total_price': prop.total_price,
            'deposit': prop.deposit,
            'monthly_rent': prop.monthly_rent,
            'image_url': thumb,
            'images': images[:3],
            'time_label': time_label,
            'is_fresh': is_fresh,
            'priority': priority,
            '_pub_timestamp': pub_ts,
            'publisher_reason': 'مالک مستقیم',
            'publisher_confidence': 1.0,
            'is_suggestion': is_suggestion,
            'suggestion_reason': suggestion_reason,
            'published_at': created_time.isoformat() if created_time else None,
            'published_at_exact': created_time.strftime('%Y-%m-%d %H:%M:%S') if created_time else None,
            'detail_url': f'/properties/{prop.id}',
        }

    # -----------------------------------------------------------------------
    # ساخت پاسخ فرمت‌شده نهایی دستیار برای چت (دو بخش مشخص + مارک‌داون)
    # -----------------------------------------------------------------------
    @classmethod
    def format_assistant_response(
        cls,
        result: Dict[str, Any],
        user_query: str = '',
        deal_type: str = 'rent',
    ) -> Dict[str, Any]:
        """
        تبدیل خروجی search_live_listings به ساختار نهایی دستیار:
        - دو بخش مجزا: بخش اول (موارد دقیق درخواستی) + بخش دوم (پیشنهادات هوشمند)
        - فیلدهای کامل: شماره مالک، زمان انتشار، تگ <a> لینک آگهی، آدرس عکس
        """
        exact = result.get('exact', [])
        suggested = result.get('suggested', [])
        meta = result.get('meta', {})
        total = len(exact) + len(suggested)
        deal_fa = 'رهن و اجاره' if deal_type == 'rent' else 'خرید و فروش'
        districts = meta.get('districts', [])
        dist_label = '، '.join(districts) if districts else 'مناطق منتخب'

        # ساخت متن صوتی کوتاه
        if total > 0:
            fresh_count = sum(1 for i in exact if i.get('is_fresh') or i.get('priority') == 1)
            voice_parts = [
                f"{total} آگهی با شواهد مالک شخصی {deal_fa} در آرشیو محدوده {dist_label} موجود است."
            ]
            if fresh_count > 0:
                voice_parts.append(f"از این تعداد، {fresh_count} فایل در ۳۰ دقیقه اخیر ثبت شده‌اند. 🔥")
            if suggested:
                voice_parts.append(f"همچنین {len(suggested)} پیشنهاد هوشمند مکمل با متراژ نزدیک آماده شد.")
            voice_reply = ' '.join(voice_parts)
        else:
            voice_reply = (
                f"فایل شخصی مستقیم با این مشخصات در محدوده {dist_label} در ۷ روز اخیر یافت نشد؛ "
                f"کراولر آنلاین هم‌اکنون استعلام شد. می‌توانید متراژ یا بودجه را منعطف‌تر بفرمایید تا نزدیک‌ترین فایل‌های مالک را تقدیم کنم."
            )

        # ساخت متن چت مارک‌داون ساختاریافته با تگ لینک آگهی و مشخصات مالک
        refresh_status = (meta.get('live_refresh') or {}).get('status')
        refresh_note = "نتایج از آرشیو ذخیره‌شده هستند."
        if refresh_status == 'failed':
            refresh_note += " تازه‌سازی زنده ناموفق بود؛ نبود نتیجه به معنی نبود آگهی نیست."
        elif refresh_status == 'partial':
            refresh_note += " تازه‌سازی زنده محدود انجام شد؛ پوشش هنوز کامل نیست."
        voice_reply += " " + refresh_note
        chat_lines = [f"### آگهی‌های آرشیو با شواهد مالک شخصی ({dist_label})", refresh_note]
        chat_lines.append(f"*{deal_fa} | بازه {meta.get('window_hours', 168)} ساعت | مجموع: {total} آگهی*\n")

        if exact:
            chat_lines.append(f"#### 📌 بخش اول: موارد دقیق درخواستی ({len(exact)} آگهی)")
            for idx, item in enumerate(exact, 1):
                area_str = f"{int(item['area'])} متر" if item.get('area') else ''
                rooms_str = f" | {item['rooms']} خواب" if item.get('rooms') else ''
                phone_str = f" | تماس: {item['owner_phone']}" if item.get('owner_phone') else ''
                chat_lines.append(
                    f"{idx}. **{item['title']}** ({area_str}{rooms_str}) - {item['price_str']} - "
                    f"{item['time_label']}{phone_str} - {item['link_tag']}"
                )
            chat_lines.append("")

        if suggested:
            chat_lines.append(f"#### 💡 بخش دوم: پیشنهادات هوشمند مکمل ({len(suggested)} آگهی)")
            for idx, item in enumerate(suggested, 1):
                area_str = f"{int(item['area'])} متر" if item.get('area') else ''
                rooms_str = f" | {item['rooms']} خواب" if item.get('rooms') else ''
                reason_str = f" *({item['suggestion_reason']})*" if item.get('suggestion_reason') else ''
                phone_str = f" | تماس: {item['owner_phone']}" if item.get('owner_phone') else ''
                chat_lines.append(
                    f"{idx}. **{item['title']}** ({area_str}{rooms_str}){reason_str} - "
                    f"{item['price_str']} - {item['time_label']}{phone_str} - {item['link_tag']}"
                )
            chat_lines.append("")

        chat_markdown = '\n'.join(chat_lines)

        return {
            'success': True,
            'action': 'crawler_results',
            'voice_reply': voice_reply,
            'speech_text': voice_reply,
            'chat_markdown': chat_markdown,
            'sections': {
                'exact': {
                    'title': '📌 موارد دقیق درخواستی',
                    'count': len(exact),
                    'items': exact,
                },
                'suggested': {
                    'title': '💡 پیشنهادات هوشمند',
                    'count': len(suggested),
                    'items': suggested,
                },
            },
            'items': exact + suggested,
            'meta': meta,
        }

    # -----------------------------------------------------------------------
    # نقطه ورود یکپارچه: استخراج نیت + جستجو + فرمت (برای gateway)
    # -----------------------------------------------------------------------
    @classmethod
    def execute_from_user_text(cls, user_text: str) -> Dict[str, Any]:
        """
        نقطه ورود یکپارچه: از متن خام کاربر تا خروجی نهایی فرمت‌شده.
        ۱. استخراج نیت و پارامترها از NLP
        ۲. محاسبه بازه‌ها
        ۳. جستجو در AccessibleListing
        ۴. فرمت پاسخ نهایی
        """
        criteria = PropertyLeadNLPExtractor.extract_criteria(user_text)

        deal_type = criteria.get('deal_type', 'rent')
        if deal_type not in ('sale', 'rent'):
            deal_type = 'rent'

        districts = criteria.get('districts', [])
        min_area = criteria.get('min_area', 0)
        max_area = criteria.get('max_area', 0)
        rooms = criteria.get('rooms')
        max_price = criteria.get('max_budget', 0)
        max_deposit = criteria.get('max_deposit', 0)
        max_rent = criteria.get('max_rent', 0)

        result = cls.search_live_listings(
            deal_type=deal_type,
            districts=districts if districts else None,
            min_area=min_area,
            max_area=max_area,
            rooms=rooms,
            max_price=max_price,
            max_deposit=max_deposit,
            max_rent=max_rent,
        )

        response = cls.format_assistant_response(result, user_query=user_text, deal_type=deal_type)
        response['criteria'] = {
            'deal_type': deal_type,
            'deal_type_fa': criteria.get('deal_type_fa', ''),
            'districts': districts,
            'min_area': min_area,
            'max_area': max_area,
            'rooms': rooms,
            'max_price': max_price,
            'max_deposit': max_deposit,
            'max_rent': max_rent,
        }
        return response

    # -----------------------------------------------------------------------
    # اجرای آفلاین SearchRun اگر AccessibleListing ناکافی باشد
    # -----------------------------------------------------------------------
    @classmethod
    def trigger_background_search_run(cls, criteria_dict: Dict[str, Any], app=None) -> Optional[str]:
        """
        آغاز یک SearchRun آفلاین در پس‌زمینه اگر خروجی فوری ناکافی باشد.
        خروجی: run_id یا None.
        """
        try:
            from services.search_run_service import SearchRunService
            from routes.crawler_api import _normalize_accessible_criteria
            normalized = _normalize_accessible_criteria(criteria_dict)
            if normalized.get('deal_type') not in ('sale', 'rent'):
                return None
            run = SearchRunService.create_run(normalized, query_text='استخراج پس‌زمینه دستیار هوشمند')
            if app:
                SearchRunService.execute_async(app, run.run_id, max_runtime_seconds=120)
            return run.run_id
        except Exception as e:
            logger.error(f"[CrawlerBridge] خطای آغاز SearchRun پس‌زمینه: {e}")
            return None
