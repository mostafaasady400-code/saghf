"""
سرویس استخراج دو مرحله‌ای و پیش‌رونده املاک سقف (Progressive Extraction Engine)

معماری عملیاتی:
۱. فاز اول (پاسخ آنی و آماده از دیتابیس):
   - واکشی فوری کلیه آگهی‌های ثبت‌شده از این لحظه تا یک هفته گذشته (۱۶۸ ساعت اخیر)
   - تجمیع همزمان دو پایگاه داده معتبر سقف (AccessibleListing و Property)
   - فیلتر ۱۰۰٪ سخت‌گیرانه مالکین شخصی واقعی (رد قطعی مشاورین، عبارات بنگاهی، فایل‌های شخصی جعلی همکاران)
   - تفکیک ساختار به دو بخش: موارد منطبق دقیق (تا ۲۰ فایل) + پیشنهادات هوشمند (۵ تا ۱۰ فایل)
   - رتبه‌بندی زمانی دقیق: اولویت ۱ (لحظاتی پیش و زیر ۳۰ دقیقه)، اولویت ۲ (ساعات گذشته زیر ۲۴ ساعت)، اولویت ۳ (روزهای گذشته تا ۷ روز)
   - درج تمام فیلدهای الزامی: شماره تماس مستقیم مالک، زمان دقیق انتشار، لینک مستقیم و تگ <a> با عنوان «لینک آگهی»

۲. فاز دوم (استخراج لحظه‌ای و زنده در پس‌زمینه):
   - آغاز فوری و بلادرنگ استخراج هدفمند دیوار در پس‌زمینه بدون مسدودسازی (Async Background Crawler)
   - صدور شناسه رهگیری (live_run_id) و پایش لحظه‌ای آگهی‌های جدید
   - افزودن فایل‌های شکارشده جدید به لیست به‌صورت زنده (Real-time Live Prepend)
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_, func

from database.db import db
from database.models import (
    AccessibleListing,
    Property,
    SearchRun,
    SearchRunItem,
)
from crawler.owner_filter import OwnerFilter, extract_phone_number
from crawler.publisher_classifier import LIKELY_OWNER, EXPLICIT_AGENCY, LIKELY_INTERMEDIARY
from services.assistant.crawler_bridge import _compute_area_ranges, AGENCY_FORBIDDEN_WORDS

logger = logging.getLogger(__name__)


class ProgressiveExtractor:
    """موتور استخراج هوشمند و دو فازه سامانه سقف"""

    DEFAULT_WINDOW_HOURS = 168  # یک هفته کامل (۷ روز)

    @classmethod
    def extract_progressive(
        cls,
        deal_type: str,
        districts: Optional[List[str]] = None,
        min_area: int = 0,
        max_area: int = 0,
        rooms: Optional[int] = None,
        min_price: int = 0,
        max_price: int = 0,
        min_deposit: int = 0,
        max_deposit: int = 0,
        min_rent: int = 0,
        max_rent: int = 0,
        window_hours: int = 168,
        trigger_live_crawl: bool = True,
        app: Any = None,
    ) -> Dict[str, Any]:
        """
        اجرای استخراج پیش‌رونده:
        ۱. بازگرداندن آنی آگهی‌های ۱ هفته اخیر از دیتابیس با فیلتر قطعی مالک
        ۲. آغاز استخراج زنده در پس‌زمینه برای شکار فایل‌های جدید مطابق با درخواست
        """
        clean_deal = 'rent' if deal_type in ('rent', 'رهن', 'اجاره') else 'sale'

        # ── ۱. فاز اول: واکشی فوری و بدون معطلی از دیتابیس (۱ هفته اخیر) ──
        db_results = cls.get_instant_database_listings(
            deal_type=clean_deal,
            districts=districts,
            min_area=min_area,
            max_area=max_area,
            rooms=rooms,
            min_price=min_price,
            max_price=max_price,
            min_deposit=min_deposit,
            max_deposit=max_deposit,
            min_rent=min_rent,
            max_rent=max_rent,
            window_hours=window_hours,
        )

        # ── ۲. فاز دوم: راه‌اندازی استخراج لحظه‌ای دیوار در پس‌زمینه ──
        live_info = {"status": "skipped", "reason": "not_requested"}
        if trigger_live_crawl:
            live_info = cls.start_live_targeted_crawl(
                deal_type=clean_deal,
                districts=districts,
                min_area=min_area,
                max_area=max_area,
                rooms=rooms,
                min_price=min_price,
                max_price=max_price,
                min_deposit=min_deposit,
                max_deposit=max_deposit,
                min_rent=min_rent,
                max_rent=max_rent,
                app=app,
            )

        exact = db_results.get('exact', [])
        suggested = db_results.get('suggested', [])

        return {
            'success': True,
            'phase': 'progressive_ready',
            'status': 'ready_streaming' if live_info.get('status') == 'running' else 'ready',
            'exact': exact,
            'suggested': suggested,
            'meta': {
                'total_exact': len(exact),
                'total_suggested': len(suggested),
                'total_listings': len(exact) + len(suggested),
                'window_hours': window_hours,
                'data_source': 'database_7days_progressive',
                'deal_type': clean_deal,
                'districts': districts or [],
                'target_area': min_area or max_area or 0,
                'live_crawl': live_info,
                'live_run_id': live_info.get('run_id'),
                'is_live_active': live_info.get('status') == 'running',
            }
        }

    @classmethod
    def get_instant_database_listings(
        cls,
        deal_type: str,
        districts: Optional[List[str]] = None,
        min_area: int = 0,
        max_area: int = 0,
        rooms: Optional[int] = None,
        min_price: int = 0,
        max_price: int = 0,
        min_deposit: int = 0,
        max_deposit: int = 0,
        min_rent: int = 0,
        max_rent: int = 0,
        window_hours: int = 168,
    ) -> Dict[str, Any]:
        """
        واکشی فوری تمام آگهی‌های از این لحظه تا یک هفته گذشته (۱۶۸ ساعت)
        با فیلتر ۱۰۰٪ مالکین واقعی از هر دو جدول AccessibleListing و Property
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)
        fresh_cutoff = now - timedelta(minutes=30)
        target_area = min_area or max_area or 0
        tight_lo, tight_hi, wide_lo, wide_hi = _compute_area_ranges(min_area=min_area, max_area=max_area)

        exact_items: List[Dict[str, Any]] = []
        suggest_items: List[Dict[str, Any]] = []
        seen_source_keys = set()

        # ── منبع ۱: AccessibleListing ──
        acc_q = cls._query_accessible_listings(
            deal_type=deal_type,
            cutoff=cutoff,
            districts=districts,
            max_price=max_price,
            max_deposit=max_deposit,
            max_rent=max_rent,
        )

        # واکشی آگهی‌های منطبق دقیق
        acc_exact_q = acc_q
        if tight_lo > 0:
            acc_exact_q = acc_exact_q.filter(AccessibleListing.area >= tight_lo, AccessibleListing.area <= tight_hi)
        if rooms and rooms > 0:
            acc_exact_q = acc_exact_q.filter(AccessibleListing.rooms == rooms)

        for l in acc_exact_q.order_by(AccessibleListing.published_at.desc().nullslast(), AccessibleListing.first_seen_at.desc()).limit(40).all():
            if cls._is_clean_personal_listing(l.title, l.description):
                s_key = (l.source_id or l.source_url or str(l.id))
                if s_key not in seen_source_keys:
                    seen_source_keys.add(s_key)
                    exact_items.append(cls._format_accessible_item(l, now, fresh_cutoff, is_suggestion=False, target_area=target_area))
                    if len(exact_items) >= 20:
                        break

        # واکشی آگهی‌های پیشنهادی هوشمند مکمل
        acc_sug_q = acc_q
        if wide_lo > 0:
            acc_sug_q = acc_sug_q.filter(AccessibleListing.area >= wide_lo, AccessibleListing.area <= wide_hi)
        if rooms and rooms > 0:
            acc_sug_q = acc_sug_q.filter(AccessibleListing.rooms == rooms)

        for l in acc_sug_q.order_by(AccessibleListing.published_at.desc().nullslast(), AccessibleListing.first_seen_at.desc()).limit(25).all():
            if cls._is_clean_personal_listing(l.title, l.description):
                s_key = (l.source_id or l.source_url or str(l.id))
                if s_key not in seen_source_keys:
                    seen_source_keys.add(s_key)
                    suggest_items.append(cls._format_accessible_item(l, now, fresh_cutoff, is_suggestion=True, target_area=target_area))
                    if len(suggest_items) >= 10:
                        break

        # ── منبع ۲: جدول جامع Property (فایل‌های تاییدشده مالکین مستقیم سقف) ──
        prop_q = cls._query_properties(
            deal_type=deal_type,
            cutoff=cutoff,
            districts=districts,
            max_price=max_price,
            max_deposit=max_deposit,
            max_rent=max_rent,
        )

        if len(exact_items) < 20:
            prop_exact_q = prop_q
            if tight_lo > 0:
                prop_exact_q = prop_exact_q.filter(Property.area >= tight_lo, Property.area <= tight_hi)
            if rooms and rooms > 0:
                prop_exact_q = prop_exact_q.filter(Property.rooms == rooms)

            for p in prop_exact_q.order_by(Property.created_at.desc()).limit(30).all():
                if cls._is_clean_personal_listing(p.title, p.description):
                    s_key = (p.source_id or p.source_url or f"prop_{p.id}")
                    if s_key not in seen_source_keys:
                        seen_source_keys.add(s_key)
                        exact_items.append(cls._format_property_item(p, now, fresh_cutoff, is_suggestion=False, target_area=target_area))
                        if len(exact_items) >= 20:
                            break

        if len(suggest_items) < 10:
            prop_sug_q = prop_q
            if wide_lo > 0:
                prop_sug_q = prop_sug_q.filter(Property.area >= wide_lo, Property.area <= wide_hi)
            if rooms and rooms > 0:
                prop_sug_q = prop_sug_q.filter(Property.rooms == rooms)

            for p in prop_sug_q.order_by(Property.created_at.desc()).limit(20).all():
                if cls._is_clean_personal_listing(p.title, p.description):
                    s_key = (p.source_id or p.source_url or f"prop_{p.id}")
                    if s_key not in seen_source_keys:
                        seen_source_keys.add(s_key)
                        suggest_items.append(cls._format_property_item(p, now, fresh_cutoff, is_suggestion=True, target_area=target_area))
                        if len(suggest_items) >= 10:
                            break

        # مرتب‌سازی زمانی دقیق:
        # اولویت ۱: فایل‌های لحظه‌ای (زیر ۳۰ دقیقه) در صدر
        # اولویت ۲: ساعات گذشته تا ۲۴ ساعت
        # اولویت ۳: روزهای گذشته تا ۷ روز
        exact_items.sort(key=lambda x: (x.get('priority', 2), -(x.get('_pub_timestamp') or 0)))
        suggest_items.sort(key=lambda x: (x.get('priority', 2), -(x.get('_pub_timestamp') or 0)))

        return {
            'exact': exact_items[:20],
            'suggested': suggest_items[:10],
            'meta': {
                'window_hours': window_hours,
                'cutoff': cutoff.isoformat(),
            }
        }

    @classmethod
    def start_live_targeted_crawl(
        cls,
        deal_type: str,
        districts: Optional[List[str]] = None,
        min_area: int = 0,
        max_area: int = 0,
        rooms: Optional[int] = None,
        min_price: int = 0,
        max_price: int = 0,
        min_deposit: int = 0,
        max_deposit: int = 0,
        min_rent: int = 0,
        max_rent: int = 0,
        app: Any = None,
    ) -> Dict[str, Any]:
        """
        آغاز استخراج زنده در پس‌زمینه منطبق بر شروط کاربر با موتور SearchRunService.
        این فرآیند به صورت کاملاً غیرهمگام (Async) اجرا می‌شود و هیچ تاخیری به کاربر تحمیل نمی‌کند.
        """
        try:
            from flask import current_app, has_app_context
            target_app = app or (current_app._get_current_object() if has_app_context() else None)

            if target_app and target_app.config.get("TESTING"):
                return {"status": "skipped", "reason": "testing"}

            from services.search_run_service import SearchRunService
            normalized = {
                "city": "tehran",
                "deal_type": deal_type,
                "property_type": "apartment",
                "districts": districts or [],
                "min_area": min_area or None,
                "max_area": max_area or None,
                "rooms": rooms or None,
                "min_price": min_price or None,
                "max_price": max_price or None,
                "min_deposit": min_deposit or None,
                "max_deposit": max_deposit or None,
                "min_rent": min_rent or None,
                "max_rent": max_rent or None,
                "window_hours": 168,
            }

            run = SearchRunService.create_run(normalized, query_text="استخراج زنده و پیش‌رونده دیوار")
            budget = max(15.0, min(180.0, float(os.getenv("DIVAR_LIVE_SEARCH_TIMEOUT", "60"))))

            if target_app:
                SearchRunService.execute_async(target_app, run.run_id, max_runtime_seconds=budget)
            else:
                # اگر کانتکست اپ نبود، در یک ترد مستقل اجرا کن
                threading.Thread(
                    target=SearchRunService.execute,
                    args=(run.run_id,),
                    kwargs={"max_runtime_seconds": budget},
                    daemon=True
                ).start()

            return {
                "status": "running",
                "run_id": run.run_id,
                "message": "استخراج زنده دیوار در پس‌زمینه با موفقیت آغاز شد.",
                "status_url": f"/crawler/search-runs/{run.run_id}",
            }
        except Exception as exc:
            logger.warning("[ProgressiveExtractor] خطا در راه‌اندازی استخراج پس‌زمینه: %s", exc)
            return {"status": "failed", "reason": str(exc)}

    @classmethod
    def poll_new_live_items(cls, run_id: str, since_id: int = 0) -> Dict[str, Any]:
        """
        واکشی آگهی‌های تازه شکارشده توسط کراولر زنده پس از شناسه since_id
        جهت افزودن لحظه‌ای و داینامیک به صفحه کاربر
        """
        run = SearchRun.query.filter_by(run_id=run_id).first()
        if not run:
            return {'success': False, 'message': 'ران استخراج یافت نشد', 'items': []}

        # پیوندهای ران فعلی
        links = SearchRunItem.query.filter(
            SearchRunItem.run_id == run_id,
            SearchRunItem.id > since_id
        ).order_by(SearchRunItem.id.asc()).all()

        new_items = []
        now = datetime.utcnow()
        fresh_cutoff = now - timedelta(minutes=30)

        for link in links:
            listing = AccessibleListing.query.get(link.listing_id)
            if listing and cls._is_clean_personal_listing(listing.title, listing.description):
                new_items.append(cls._format_accessible_item(listing, now, fresh_cutoff, is_live_streamed=True))

        return {
            'success': True,
            'run_id': run_id,
            'run_status': run.status,
            'coverage_status': run.coverage_status,
            'source_status': run.source_status,
            'items': new_items,
            'count': len(new_items),
            'latest_id': links[-1].id if links else since_id,
            'is_running': run.status in ('running', 'pending'),
        }

    # ── فیلترهای کمکی و اعتبارسنجی مالک ──

    @classmethod
    def _is_clean_personal_listing(cls, title: Optional[str], description: Optional[str]) -> bool:
        """بررسی دقیق و ۱۰۰٪ حذف واسطه‌ها و حفظ مالکین شخصی واقعی"""
        combined = f"{title or ''} {description or ''}".strip()
        if not combined:
            return False

        # ارزیابی با موتور استاندارد OwnerFilter
        evaluation = OwnerFilter.evaluate(platform="divar", title=title or "", description=description or "")
        return evaluation.is_personal

    @classmethod
    def _query_accessible_listings(
        cls,
        deal_type: str,
        cutoff: datetime,
        districts: Optional[List[str]] = None,
        max_price: int = 0,
        max_deposit: int = 0,
        max_rent: int = 0,
    ):
        """کوئری پایه از AccessibleListing برای مالکین در بازه زمانی تعیین‌شده"""
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
            if max_price > 0:
                q = q.filter(AccessibleListing.total_price <= int(max_price * 1.15))
        elif deal_type in ('rent', 'رهن', 'اجاره'):
            q = q.filter(
                (AccessibleListing.deal_type == 'rent') | (AccessibleListing.transaction_type == 'rent'),
                (AccessibleListing.total_price == 0) | (AccessibleListing.total_price.is_(None)),
                (AccessibleListing.deposit > 0) | (AccessibleListing.monthly_rent > 0)
            )
            if max_deposit > 0:
                q = q.filter(AccessibleListing.deposit <= int(max_deposit * 1.2))
            if max_rent > 0:
                q = q.filter(AccessibleListing.monthly_rent <= int(max_rent * 1.2))

        if districts:
            dist_or = []
            for d in districts:
                clean = d.replace('منطقه', '').strip()
                dist_or.extend([
                    AccessibleListing.district.ilike(f'%{d}%'),
                    AccessibleListing.district.ilike(f'%{clean}%'),
                    AccessibleListing.title.ilike(f'%{d}%'),
                ])
            q = q.filter(or_(*dist_or))

        return q

    @classmethod
    def _query_properties(
        cls,
        deal_type: str,
        cutoff: datetime,
        districts: Optional[List[str]] = None,
        max_price: int = 0,
        max_deposit: int = 0,
        max_rent: int = 0,
    ):
        """کوئری پایه از جدول جامع Property سقف"""
        q = Property.query.filter(
            Property.is_personal_owner == True,
            Property.created_at >= cutoff,
            Property.status.notin_(['archived', 'sold', 'needs_followup']),
        )

        if deal_type in ('sale', 'buy'):
            q = q.filter(Property.deal_type.in_(['sale', 'buy']))
            if max_price > 0:
                q = q.filter(Property.total_price <= int(max_price * 1.15))
        elif deal_type in ('rent', 'رهن', 'اجاره'):
            q = q.filter(Property.deal_type == 'rent')
            if max_deposit > 0:
                q = q.filter(Property.deposit <= int(max_deposit * 1.2))
            if max_rent > 0:
                q = q.filter(Property.monthly_rent <= int(max_rent * 1.2))

        if districts:
            dist_or = []
            for d in districts:
                clean = d.replace('منطقه', '').strip()
                dist_or.extend([
                    Property.district.ilike(f'%{d}%'),
                    Property.district.ilike(f'%{clean}%'),
                    Property.title.ilike(f'%{d}%'),
                    Property.address.ilike(f'%{d}%'),
                ])
            q = q.filter(or_(*dist_or))

        return q

    # ── فرمت‌بندی خروجی استاندارد ──

    @classmethod
    def _format_accessible_item(
        cls,
        listing: AccessibleListing,
        now: datetime,
        fresh_cutoff: datetime,
        is_suggestion: bool = False,
        target_area: int = 0,
        is_live_streamed: bool = False,
    ) -> Dict[str, Any]:
        """تبدیل AccessibleListing به آبجکت ساختاریافته"""
        pub_time = listing.published_at or listing.first_seen_at
        pub_ts = pub_time.timestamp() if pub_time else 0.0

        if pub_time:
            delta = now - pub_time
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
            time_label = 'به تازگی'

        if is_live_streamed:
            time_label = '⚡ شکار لحظه‌ای (هم‌اکنون)'
            priority = 1
            is_fresh = True

        if listing.deal_type == 'sale':
            price_str = f"قیمت: {listing.total_price / 1_000_000_000:.1f} میلیارد تومان" if listing.total_price else "قیمت: توافقی"
        else:
            dep_str = f"{int(listing.deposit / 1_000_000):,} م" if listing.deposit else "توافقی"
            rent_str = f"{int(listing.monthly_rent / 1_000_000):,} م" if listing.monthly_rent else "توافقی"
            price_str = f"رهن کامل: {dep_str} تومان" if listing.monthly_rent == 0 and listing.deposit else f"ودیعه: {dep_str} | اجاره: {rent_str}"

        # استخراج شماره مالک
        phone = extract_phone_number(listing.description or '') or extract_phone_number(listing.title or '')
        if not phone and listing.source_id:
            try:
                p = Property.query.filter_by(source_id=listing.source_id).first()
                if p and p.owner and p.owner.phone_number:
                    phone = p.owner.phone_number
            except Exception:
                pass

        owner_phone = phone or 'موجود در لینک آگهی'
        images = listing.images or []
        thumb = images[0] if images else '/static/images/placeholder.png'

        suggestion_reason = ''
        if is_suggestion and target_area > 0:
            area_val = listing.area or 0
            if area_val < target_area:
                suggestion_reason = f'متراژ نزدیک ({int(area_val)} متر) با احتمال نقشه عالی و قیمت منصفانه‌تر'
            elif area_val > target_area:
                suggestion_reason = f'متراژ وسیع‌تر ({int(area_val)} متر) با نورگیری عالی در همان محدوده'
            else:
                suggestion_reason = 'متناسب با شرایط درخواستی با کیفیت و اصالت مالک'

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
            'district': listing.district or 'تهران',
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
            'is_suggestion': is_suggestion,
            'suggestion_reason': suggestion_reason,
            'published_at': pub_time.isoformat() if pub_time else None,
            'published_at_exact': pub_time.strftime('%Y-%m-%d %H:%M:%S') if pub_time else None,
            'is_live_streamed': is_live_streamed,
        }

    @classmethod
    def _format_property_item(
        cls,
        prop: Property,
        now: datetime,
        fresh_cutoff: datetime,
        is_suggestion: bool = False,
        target_area: int = 0,
    ) -> Dict[str, Any]:
        """تبدیل رکورد Property به ساختار یکپارچه"""
        created = prop.created_at
        pub_ts = created.timestamp() if created else 0.0

        if created:
            delta = now - created
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
                suggestion_reason = f'متراژ نزدیک ({int(area_val)} متر) با احتمال نقشه عالی و قیمت منصفانه‌تر'
            elif area_val > target_area:
                suggestion_reason = f'متراژ وسیع‌تر ({int(area_val)} متر) با نورگیری عالی در همان محدوده'
            else:
                suggestion_reason = 'متناسب با شرایط درخواستی با کیفیت و اصالت مالک'

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
            'is_suggestion': is_suggestion,
            'suggestion_reason': suggestion_reason,
            'published_at': created.isoformat() if created else None,
            'published_at_exact': created.strftime('%Y-%m-%d %H:%M:%S') if created else None,
            'is_live_streamed': False,
        }
