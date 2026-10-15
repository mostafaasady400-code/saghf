"""
REGIONAL INCREMENTAL ENGINE (موتور استخراج هوشمند و تایم‌بندی‌شده مناطق ۲ و ۵ تهران)
=====================================================================================
- تمرکز ۱۰۰٪ و بدون استثنا فقط روی منطقه ۲ و ۵ تهران.
- فیلترینگ سخت‌گیرانه مالک واقعی (بدون واسطه، بدون عکس تزیینی، دارای اظهار صریح مالکیت).
- تایم‌بندی دقیق با چک‌پوینت (معیار قرار دادن آخرین استخراج و پایش آنلاین بلادرنگ).
- بک‌فیل عمیق ۷ روزه (۱۶۸ ساعت گذشته) تمام آگهی‌های مالکین مناطق ۲ و ۵ در پایگاه داده.
- استخراج شماره با TextPhoneMiner (صفر سهمیه) و استخر نشست‌های دیوار (DivarSessionPool).
- ثبت لینک‌های مستقیم و واقعی دیوار: https://divar.ir/v/{token}
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from crawler.network.impersonator import TLSImpersonatorClient
from crawler.network.rate_limiter import TokenBucketRateLimiter
from crawler.publication_time import parse_publication_time
from crawler.strict_owner_guard import strict_decision, install_strict_owner_guard
from crawler.text_phone_miner import TextPhoneMiner
from crawler.divar_session_pool import DivarSessionPool
from crawler.contact_extractor import ContactExtractor
from data.tehran_districts import (
    is_in_region_2_or_5,
    get_region_for_district,
    DISTRICTS_2_AND_5_SLUGS,
    REGION_2_DISTRICT_NAMES,
    REGION_5_DISTRICT_NAMES
)

logger = logging.getLogger(__name__)

CHECKPOINT_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "instance",
    "regions_2_5_checkpoint.json"
)

# اسلاگ‌های اصلی و حیاتی مناطق ۲ و ۵ برای پیمایش پرحجم دیوار
TARGET_SLUGS_REGION_2 = [
    'saadat-abad',
    'shahrak-e-gharb',
    'gisha',
    'marzdaran',
    'sattarkhan',
    'tarasht',
    'shahrara',
    'tohid',
    'daryan-no',
    'farahzad'
]

TARGET_SLUGS_REGION_5 = [
    'punak',
    'central-jannat-abad',
    'south-jannat-abad',
    'north-jannat-abad',
    'ferdows',
    'abazar',
    'ekbatan',
    'shahran',
    'bagh-feyz',
    'shahin',
    'sazman-barnameh',
    'shahr-e-ziba',
    'koohsar',
    'kan',
    'mehran',
    'eram',
    'apadana',
    'almahdi'
]

ALL_REGIONAL_SLUGS = list(dict.fromkeys(TARGET_SLUGS_REGION_5 + TARGET_SLUGS_REGION_2))


def _console(msg: Any) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        pass


class RegionalIncrementalEngine:
    """موتور پایش تایم‌بندی‌شده، بک‌فیل هفت‌روزه و شنود آنلاین مالکین مناطق ۲ و ۵ تهران"""

    BASE_URL = "https://divar.ir/s/tehran"

    def __init__(self):
        install_strict_owner_guard()
        self.rate_limiter = TokenBucketRateLimiter(capacity=5, fill_rate=2.5)
        self.client = TLSImpersonatorClient(impersonate="chrome120")
        self._ensure_checkpoint_file()

    # -------------------------------------------------------------------------
    # ۱. مدیریت چک‌پوینت و تایم‌بندی استخراج
    # -------------------------------------------------------------------------

    def _ensure_checkpoint_file(self) -> None:
        os.makedirs(os.path.dirname(CHECKPOINT_FILE_PATH), exist_ok=True)
        if not os.path.exists(CHECKPOINT_FILE_PATH):
            now_iso = datetime.now(timezone.utc).isoformat()
            default_data = {
                "last_checkpoint_timestamp": None,
                "last_post_token": None,
                "last_sync_time": now_iso,
                "backfill_7_days_completed": False,
                "backfill_last_completed_at": None,
                "total_owners_extracted": 0,
                "region_2_count": 0,
                "region_5_count": 0,
                "notes": "Incremental checkpoint for Tehran regions 2 & 5 only"
            }
            with open(CHECKPOINT_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(default_data, f, ensure_ascii=False, indent=2)

    def load_checkpoint(self) -> Dict[str, Any]:
        self._ensure_checkpoint_file()
        try:
            with open(CHECKPOINT_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error reading checkpoint: %s", e)
            return {}

    def save_checkpoint(self, data: Dict[str, Any]) -> bool:
        try:
            self._ensure_checkpoint_file()
            with open(CHECKPOINT_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Error saving checkpoint: %s", e)
            return False

    def update_checkpoint(
        self,
        new_timestamp: Optional[datetime] = None,
        token: Optional[str] = None,
        inc_r2: int = 0,
        inc_r5: int = 0
    ) -> None:
        """به‌روزرسانی ایمن و افزایشی آخرین زمان و توکن استخراج"""
        data = self.load_checkpoint()
        if new_timestamp:
            new_iso = new_timestamp.astimezone(timezone.utc).isoformat()
            curr_iso = data.get("last_checkpoint_timestamp")
            if not curr_iso or new_iso > curr_iso:
                data["last_checkpoint_timestamp"] = new_iso
                if token:
                    data["last_post_token"] = token

        data["last_sync_time"] = datetime.now(timezone.utc).isoformat()
        data["region_2_count"] = data.get("region_2_count", 0) + inc_r2
        data["region_5_count"] = data.get("region_5_count", 0) + inc_r5
        data["total_owners_extracted"] = data.get("total_owners_extracted", 0) + inc_r2 + inc_r5
        self.save_checkpoint(data)

    # -------------------------------------------------------------------------
    # ۲. اعتبارسنجی ۱۰۰٪ منطقه ۲ و ۵ و پاک‌سازی پایگاه‌داده
    # -------------------------------------------------------------------------

    @classmethod
    def is_valid_region_2_or_5(cls, district: Optional[str], text: Optional[str] = "") -> bool:
        """انطباق قطعی جغرافیایی با منطقه ۲ یا ۵ تهران"""
        return is_in_region_2_or_5(district, text)

    @classmethod
    def purge_any_non_region_2_5(cls) -> Dict[str, int]:
        """
        پاک‌سازی ۱۰۰٪ قطعی پایگاه‌داده از هرگونه آگهی خارج از مناطق ۲ و ۵
        طبق دستور صریح کاربر: بقیه مناطق از دیتابیس حذف بشوند
        """
        from app import app
        from database.db import db
        from database.models import Property, PropertyListing, Owner

        deleted_props = 0
        deleted_listings = 0
        deleted_owners = 0

        with app.app_context():
            # ۱. پالایش املاک
            props = Property.query.all()
            for p in props:
                full_text = f"{p.title or ''} {p.description or ''}"
                if not is_in_region_2_or_5(p.district, full_text):
                    db.session.delete(p)
                    deleted_props += 1

            # ۲. پالایش آگهی‌ها
            listings = PropertyListing.query.all()
            for l in listings:
                full_text = f"{l.title or ''} {l.description or ''}"
                if not is_in_region_2_or_5(l.district, full_text):
                    db.session.delete(l)
                    deleted_listings += 1

            db.session.flush()

            # ۳. پالایش مالکین بدون ملک در مناطق ۲ و ۵
            owners = Owner.query.all()
            for o in owners:
                active_props = Property.query.filter_by(owner_id=o.id).count()
                if active_props == 0:
                    db.session.delete(o)
                    deleted_owners += 1

            db.session.commit()

        if deleted_props > 0 or deleted_listings > 0:
            _console(f"[RegionalIncrementalEngine] 🧹 پاک‌سازی دیتابیس: {deleted_props} ملک و {deleted_listings} آگهی غیر از مناطق ۲ و ۵ حذف شدند.")

        return {
            "deleted_properties": deleted_props,
            "deleted_listings": deleted_listings,
            "deleted_owners": deleted_owners
        }

    # -------------------------------------------------------------------------
    # ۳. دریافت و پارس زنده صفحات دیوار با پشتیبانی از last-post-date
    # -------------------------------------------------------------------------

    def fetch_page_state(
        self,
        category: str = 'buy-apartment',
        slug: str = 'punak',
        last_post_date: Optional[str] = None,
        page: int = 1
    ) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
        """
        واکشی یک صفحه از دیوار با TLS Impersonator و استخراج متوازن JSON __PRELOADED_STATE__
        خروجی: (لیست کاندیدها، next_last_post_date، تعداد کل ویجت‌ها)
        """
        self.rate_limiter.acquire(1)
        url = f"{self.BASE_URL}/{category}/{slug}"
        params = []
        if last_post_date:
            params.append(f"last-post-date={last_post_date}")
        if page > 1:
            params.append(f"page={page}")
        if params:
            url += f"?{'&'.join(params)}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'fa,en;q=0.9',
            'Referer': f"{self.BASE_URL}/{category}"
        }

        try:
            resp = self.client.get(url, headers=headers, timeout=12)
            if not resp or resp.status_code != 200:
                return [], None, 0

            html_text = resp.text
            marker = "window.__PRELOADED_STATE__"
            start_idx = html_text.find(marker)
            if start_idx < 0:
                return [], None, 0

            eq_idx = html_text.find("=", start_idx + len(marker))
            if eq_idx < 0:
                return [], None, 0

            json_start = eq_idx + 1
            while json_start < len(html_text) and html_text[json_start].isspace():
                json_start += 1

            if json_start >= len(html_text) or html_text[json_start] != '{':
                return [], None, 0

            # پارسر براکت متوازن
            depth = 0
            in_string = False
            escaped = False
            end_pos = -1
            for ci in range(json_start, len(html_text)):
                ch = html_text[ci]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == '\\':
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        end_pos = ci
                        break

            if end_pos < 0:
                return [], None, 0

            state_data = json.loads(html_text[json_start:end_pos + 1])
            nb = state_data.get('nb', {})
            widgets = nb.get('listWidgets', [])
            pag_data = nb.get('pagination', {})
            next_lpd = None
            if isinstance(pag_data, dict):
                next_lpd = pag_data.get('data', {}).get('last_post_date') or pag_data.get('last_post_date')
            if not next_lpd:
                next_lpd = nb.get('last_post_date')

            candidates = []
            for w in widgets:
                dto = w.get('data', {}).get('dto', {})
                if dto.get('widget_type') != 'POST_ROW':
                    continue
                d = dto.get('data', {})
                token = d.get('token') or d.get('action', {}).get('payload', {}).get('token')
                title = d.get('title', '')
                if not token or not title:
                    continue

                district = d.get('action', {}).get('payload', {}).get('web_info', {}).get('district_persian', '')
                bottom_desc = d.get('bottom_description_text', '')
                middle_desc = d.get('middle_description_text', '')
                if not district and bottom_desc:
                    district = bottom_desc.replace('در ', '').strip()

                candidates.append({
                    'token': token,
                    'title': title,
                    'district': district,
                    'middle_desc': middle_desc,
                    'bottom_desc': bottom_desc,
                    'widget_data': d,
                    'image_url': d.get('image_url') or (d.get('image', {}).get('url') if isinstance(d.get('image'), dict) else None)
                })

            return candidates, next_lpd, len(widgets)

        except Exception as ex:
            logger.error("Error fetching page state for %s/%s: %s", category, slug, ex)
            return [], None, 0

    # -------------------------------------------------------------------------
    # ۴. استخراج عمیق جزئیات و استخراج واقعی شماره مالک
    # -------------------------------------------------------------------------

    def fetch_full_post_details(self, token: str) -> Dict[str, Any]:
        """دریافت بلادرنگ جزئیات کامل آگهی از API رسمی دیوار"""
        url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'fa-IR,fa;q=0.9',
        }
        res_data = {
            'description': '',
            'images': [],
            'area': 0,
            'rooms': 1,
            'deposit': 0,
            'monthly_rent': 0,
            'total_price': 0,
            'build_year': 1400,
            'floor': 1,
            'total_floors': None,
            'has_parking': False,
            'has_elevator': False,
            'has_warehouse': False,
            'has_balcony': False,
            'is_business': False,
            'raw_json': {}
        }

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                res_data['raw_json'] = data
                webengage = data.get('webengage', {})
                if isinstance(webengage, dict):
                    biz = str(webengage.get('business_type', '')).lower()
                    if biz and biz != 'personal':
                        res_data['is_business'] = True
                    if webengage.get('price'):
                        res_data['total_price'] = int(webengage['price'])
                    if webengage.get('credit'):
                        res_data['deposit'] = int(webengage['credit'])
                    if webengage.get('rent'):
                        res_data['monthly_rent'] = int(webengage['rent'])

                images = []
                for s in data.get('sections', []):
                    for w in s.get('widgets', []):
                        wt = w.get('widget_type')
                        wd = w.get('data', {})

                        if wt == 'DESCRIPTION_ROW':
                            res_data['description'] = wd.get('text', '')

                        elif 'IMAGE' in wt:
                            for it in wd.get('items', []):
                                u = it.get('image', {}).get('url') if isinstance(it, dict) else it
                                if u and isinstance(u, str):
                                    hi_res = u.replace('/webp_thumbnail/', '/webp_post/').replace('/thumbnail/', '/post/')
                                    if hi_res not in images:
                                        images.append(hi_res)

                        elif wt in ['GROUP_INFO_ROW', 'UNEXPANDABLE_ROW'] and wd.get('items'):
                            for it in wd.get('items', []):
                                t = it.get('title', '')
                                v = ContactExtractor.normalize_persian_digits(it.get('value', ''))
                                if 'متراژ' in t:
                                    m = re.search(r'\d+', v)
                                    if m:
                                        res_data['area'] = int(m.group(0))
                                elif 'اتاق' in t:
                                    m = re.search(r'\d+', v)
                                    if m:
                                        res_data['rooms'] = int(m.group(0))
                                elif 'ساخت' in t:
                                    m = re.search(r'\d+', v)
                                    if m:
                                        res_data['build_year'] = int(m.group(0))

                        elif wt == 'GROUP_FEATURE_ROW':
                            for fit in wd.get('items', []):
                                ft = fit.get('title', '')
                                if 'آسانسور' in ft and 'ندارد' not in ft:
                                    res_data['has_elevator'] = True
                                elif 'پارکینگ' in ft and 'ندارد' not in ft:
                                    res_data['has_parking'] = True
                                elif 'انباری' in ft and 'ندارد' not in ft:
                                    res_data['has_warehouse'] = True

                res_data['images'] = images
        except Exception:
            pass

        return res_data

    def extract_owner_phone(self, token: str, title: str, description: str) -> Optional[str]:
        """
        استخراج شماره واقعی مالک با زنجیره دولایه‌ای:
        ۱. استخراج فوق‌سریع بدون سهمیه با TextPhoneMiner از متن آگهی
        ۲. استخراج رسمی از استخر نشست‌های احراز هویت دیوار (سیم‌کارت‌های فعال سیستم)
        """
        # گام ۱: ماینینگ درون‌برنامه‌ای از متن (صفر مصرف سهمیه)
        mined = TextPhoneMiner.mine_phone(description, title)
        if mined and mined.get("phone"):
            ph = mined["phone"]
            val = ContactExtractor.validate_and_normalize(ph)
            if val and val.get("is_valid") and not val.get("is_suspicious"):
                _console(f"[RegionalIncrementalEngine] 🎯 شماره مالک با TextPhoneMiner از متن استخراج شد: {ph}")
                return ph

        # گام ۲: فراخوانی استخر نشست‌های احراز هویت دیوار (سیم‌کارت اول یا دوم)
        pool_res = DivarSessionPool.extract_owner_phone(token)
        if pool_res.get("success") and pool_res.get("phone"):
            ph = pool_res["phone"]
            _console(f"[RegionalIncrementalEngine] 🎯 شماره مالک از طریق {pool_res.get('channel_used')} استخراج شد: {ph}")
            return ph

        return None

    # -------------------------------------------------------------------------
    # ۵. ذخیره‌سازی قطعی در پایگاه داده (Properties, Listings, Owners)
    # -------------------------------------------------------------------------

    def save_owner_property(
        self,
        token: str,
        title: str,
        category: str,
        district: str,
        details: Dict[str, Any],
        phone: Optional[str] = None
    ) -> bool:
        """ذخیره ملک تأییدشده مالک در پایگاه‌داده با لینک مستقیم معتبر"""
        from app import app
        from database.db import db
        from database.models import Property, PropertyListing, Owner

        source_id = f"divar_{token}"
        source_url = f"https://divar.ir/v/{token}"
        region = get_region_for_district(district) or ('2' if district in REGION_2_DISTRICT_NAMES else '5')
        deal_type = 'rent' if 'rent' in category else 'sale'

        with app.app_context():
            # بررسی تکراری
            existing = Property.query.filter_by(source_id=source_id).first()
            if existing:
                return False

            owner_id = None
            if phone:
                owner = Owner.query.filter_by(phone_number=phone).first()
                if not owner:
                    owner = Owner(
                        full_name=f"مالک مستقیم ({district})",
                        phone_number=phone,
                        urgency='high',
                        flexibility='معمولی',
                        notes=f"استخراج منطقه {region} تهران ({district})"
                    )
                    db.session.add(owner)
                    db.session.flush()
                owner_id = owner.id

            prop = Property(
                title=title,
                description=details.get('description') or title,
                property_type='apartment',
                deal_type=deal_type,
                total_price=details.get('total_price', 0),
                deposit=details.get('deposit', 0),
                monthly_rent=details.get('monthly_rent', 0),
                area=details.get('area') or 80,
                rooms=details.get('rooms') or 1,
                floor=details.get('floor') or 1,
                total_floors=details.get('total_floors'),
                build_year=details.get('build_year') or 1400,
                city='تهران',
                district=district,
                address=f"تهران، منطقه {region}، {district}",
                has_parking=details.get('has_parking', False),
                has_elevator=details.get('has_elevator', False),
                has_warehouse=details.get('has_warehouse', False),
                has_balcony=details.get('has_balcony', False),
                source='divar',
                source_id=source_id,
                source_url=source_url,
                owner_id=owner_id,
                is_personal_owner=True,
                status='available',
                score=99
            )
            prop.images = details.get('images', [])
            db.session.add(prop)
            db.session.flush()

            # ایجاد رکورد PropertyListing
            listing = PropertyListing(
                ad_code=str(token)[-8:],
                source='divar',
                source_url=source_url,
                title=title,
                description=prop.description,
                city='تهران',
                region=region,
                district=district,
                deal_type=deal_type,
                deposit=prop.deposit,
                monthly_rent=prop.monthly_rent,
                total_price=prop.total_price,
                area=prop.area,
                rooms=prop.rooms,
                is_personal_owner=True
            )
            listing.images = prop.images
            db.session.add(listing)

            db.session.commit()

            _console(f"[RegionalIncrementalEngine] 💾 ملک جدید مالک با موفقیت ثبت شد: منطقه {region} | {district} | {title[:40]} ({source_url})")
            return True

    # -------------------------------------------------------------------------
    # ۶. اجرای بک‌فیل ۷ روزه عمیق (Deep 7-Day Backfill)
    # -------------------------------------------------------------------------

    def run_7_day_backfill(self, max_pages_per_slug: int = 5) -> Dict[str, Any]:
        """
        استخراج عمیق هفت‌روزه (تا ۷ روز قبل) تمام آگهی‌های مالکین مناطق ۲ و ۵
        """
        _console("\n" + "=" * 70)
        _console("🚀 آغاز فرآیند بک‌فیل عمیق ۷ روزه مالکین مناطق ۲ و ۵ تهران")
        _console("=" * 70)

        # Backfill is additive. Cleanup requires a separate explicit action.

        now = datetime.now(timezone.utc)
        cutoff_7_days = now - timedelta(days=7)
        _console(f"[7-Day Backfill] بازه مجاز: از {cutoff_7_days.strftime('%Y-%m-%d %H:%M')} تا الان")

        categories = ['buy-apartment', 'rent-apartment']
        total_discovered = 0
        total_saved = 0
        r2_saved = 0
        r5_saved = 0
        latest_seen_time = None
        latest_seen_token = None

        for cat in categories:
            for slug in ALL_REGIONAL_SLUGS:
                _console(f"\n[7-Day Backfill] 🔍 پیمایش دسته‌بندی {cat} در محله {slug}...")
                current_lpd = None
                for page in range(1, max_pages_per_slug + 1):
                    candidates, next_lpd, total_widgets = self.fetch_page_state(
                        category=cat,
                        slug=slug,
                        last_post_date=current_lpd,
                        page=page
                    )
                    if not candidates:
                        break

                    reached_cutoff = False
                    for cand in candidates:
                        total_discovered += 1
                        token = cand['token']
                        title = cand['title']
                        district = cand['district'] or slug
                        bottom = cand['bottom_desc']
                        middle = cand['middle_desc']
                        widget_data = cand['widget_data']

                        # ۱. بررسی انطباق با منطقه ۲ یا ۵
                        if not self.is_valid_region_2_or_5(district, f"{title} {bottom} {middle}"):
                            continue

                        # ۲. بررسی زمان انتشار (حداکثر ۷ روز گذشته)
                        pub_window = parse_publication_time(bottom, now)
                        if pub_window.earliest_at and pub_window.earliest_at < cutoff_7_days:
                            reached_cutoff = True
                            continue

                        # ثبت جدیدترین زمان دیده شده برای چک‌پوینت
                        if pub_window.estimated_at:
                            if not latest_seen_time or pub_window.estimated_at > latest_seen_time:
                                latest_seen_time = pub_window.estimated_at
                                latest_seen_token = token

                        # ۳. فیلتر ۱۰۰٪ سخت‌گیرانه مالک واقعی (حذف مشاور، عکس تزیینی و...)
                        decision = strict_decision(title, middle, widget_data, raw_text=bottom)
                        if not decision.allowed:
                            continue

                        # ۴. دریافت جزئیات عمیق و استخراج شماره مالک
                        details = self.fetch_full_post_details(token)
                        if details.get('is_business'):
                            continue

                        # بررسی مجدد شرح کامل
                        full_desc = details.get('description') or middle
                        full_decision = strict_decision(title, full_desc, details.get('raw_json'), raw_text=bottom)
                        if not full_decision.allowed:
                            continue

                        # ۵. استخراج شماره مالک
                        phone = self.extract_owner_phone(token, title, full_desc)

                        # ۶. ذخیره در پایگاه‌داده
                        is_r2 = district in REGION_2_DISTRICT_NAMES
                        reg = '2' if is_r2 else '5'
                        saved = self.save_owner_property(token, title, cat, district, details, phone=phone)
                        if saved:
                            total_saved += 1
                            if reg == '2':
                                r2_saved += 1
                            else:
                                r5_saved += 1

                    if reached_cutoff or not next_lpd:
                        break
                    current_lpd = next_lpd

        # به‌روزرسانی چک‌پوینت
        chk = self.load_checkpoint()
        chk["backfill_7_days_completed"] = True
        chk["backfill_last_completed_at"] = datetime.now(timezone.utc).isoformat()
        if latest_seen_time:
            chk["last_checkpoint_timestamp"] = latest_seen_time.isoformat()
            if latest_seen_token:
                chk["last_post_token"] = latest_seen_token
        chk["region_2_count"] = chk.get("region_2_count", 0) + r2_saved
        chk["region_5_count"] = chk.get("region_5_count", 0) + r5_saved
        chk["total_owners_extracted"] = chk.get("total_owners_extracted", 0) + total_saved
        self.save_checkpoint(chk)

        _console("\n" + "=" * 70)
        _console(f"✅ پایان بک‌فیل ۷ روزه: {total_saved} فایل جدید مالک ثبت شد (منطقه ۲: {r2_saved} | منطقه ۵: {r5_saved})")
        _console("=" * 70)

        return {
            "success": True,
            "total_discovered": total_discovered,
            "total_saved": total_saved,
            "region_2_saved": r2_saved,
            "region_5_saved": r5_saved,
            "checkpoint": self.load_checkpoint()
        }

    # -------------------------------------------------------------------------
    # ۷. پایش آنلاین افزایشی نوبتی (Incremental Online Polling)
    # -------------------------------------------------------------------------

    def poll_incremental_new_ads(self, limit_per_slug: int = 10) -> Dict[str, Any]:
        """
        پایش آنلاین افزایشی: استخراج هر انتشار آگهی جدید مالک بعد از چک‌پوینت
        هیچ مالکی از قلم نمی‌افتد
        """
        chk = self.load_checkpoint()
        last_cp_str = chk.get("last_checkpoint_timestamp")
        last_cp = None
        if last_cp_str:
            try:
                last_cp = datetime.fromisoformat(last_cp_str.replace("Z", "+00:00"))
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        categories = ['buy-apartment', 'rent-apartment']
        cycle_new_saved = 0
        r2_cycle = 0
        r5_cycle = 0
        newest_seen_time = None
        newest_seen_token = None

        for cat in categories:
            for slug in ALL_REGIONAL_SLUGS[:8]:  # کانون‌های اصلی در هر دور
                candidates, _, _ = self.fetch_page_state(category=cat, slug=slug, page=1)
                for cand in candidates[:limit_per_slug]:
                    token = cand['token']
                    title = cand['title']
                    district = cand['district'] or slug
                    bottom = cand['bottom_desc']
                    middle = cand['middle_desc']
                    widget_data = cand['widget_data']

                    if not self.is_valid_region_2_or_5(district, f"{title} {bottom} {middle}"):
                        continue

                    pub_window = parse_publication_time(bottom, now)
                    pub_time = pub_window.estimated_at or now

                    # اگر آگهی قدیمی‌تر از چک‌پوینت باشد، از قلم افتاده نیست و قبلاً پردازش شده
                    if last_cp and pub_window.latest_at and pub_window.latest_at.replace(tzinfo=timezone.utc) < last_cp:
                        continue

                    # فیلتر سخت‌گیرانه مالک
                    decision = strict_decision(title, middle, widget_data, raw_text=bottom)
                    if not decision.allowed:
                        continue

                    details = self.fetch_full_post_details(token)
                    if details.get('is_business'):
                        continue

                    full_desc = details.get('description') or middle
                    if not strict_decision(title, full_desc, details.get('raw_json'), raw_text=bottom).allowed:
                        continue

                    # استخراج شماره تماس
                    phone = self.extract_owner_phone(token, title, full_desc)

                    is_r2 = district in REGION_2_DISTRICT_NAMES
                    reg = '2' if is_r2 else '5'
                    saved = self.save_owner_property(token, title, cat, district, details, phone=phone)
                    if saved:
                        cycle_new_saved += 1
                        if reg == '2':
                            r2_cycle += 1
                        else:
                            r5_cycle += 1

                    if not newest_seen_time or pub_time > newest_seen_time:
                        newest_seen_time = pub_time
                        newest_seen_token = token

        # ارتقای چک‌پوینت در صورت کشف آگهی‌های جدید
        if newest_seen_time:
            self.update_checkpoint(newest_seen_time, newest_seen_token, inc_r2=r2_cycle, inc_r5=r5_cycle)
        else:
            self.update_checkpoint(inc_r2=r2_cycle, inc_r5=r5_cycle)

        return {
            "cycle_new_saved": cycle_new_saved,
            "region_2_cycle": r2_cycle,
            "region_5_cycle": r5_cycle,
            "checkpoint": self.load_checkpoint()
        }


# نمونه سراسری
regional_engine = RegionalIncrementalEngine()
