"""
SAGHF REAL-TIME CONTINUOUS DIVAR MONITOR (پایش مداوم و زنده دیوار)
سرویس پس‌زمینه هوشمند برای استخراج لحظه‌ای آگهی‌های تازه منتشر شده مالک در منطقه ۵
- استخراج بدون نیاز به کلیک یا درخواست دستی
- فیلترینگ سخت‌گیرانه: حذف پنل املاک، مشاورین، هم‌خونه و اسکان اشتراکی
- اولویت حداکثری به آگهی‌های مالک مستقیم ("مالک هستم"، "مالکم"، "بی‌واسطه")
- ذخیره‌سازی داده‌های واقعی با لینک مستقیم معتبر دیوار
"""

import threading
import time
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional


def _console(message: Any) -> None:
    """Keep the monitor alive on Windows consoles without Persian/emoji support."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe_message = str(message).encode(encoding, errors="replace").decode(encoding)
        print(safe_message)

class DivarContinuousMonitor:
    def __init__(self):
        self.app = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self._stop_event = threading.Event()
        self.lock = threading.Lock()

        # تنظیمات و وضعیت
        self.target_district = "منطقه ۲ و ۵ تهران"
        self.interval_seconds = 150  # پایش زنده هر ۱۲۰ تا ۱۸۰ ثانیه (پیش‌فرض ۱۵۰ ثانیه)
        self.min_area: Optional[int] = None
        self.max_area: Optional[int] = None
        self.rooms: Optional[int] = None
        self.custom_districts: List[str] = []
        self.total_checked = 0
        self.new_owners_today = 0
        self.last_check_time = None
        self.last_run_timestamp = 0
        self.recent_items: List[Dict[str, Any]] = []
        self.error_count = 0
        self.last_error = None

    def init_app(self, app):
        self.app = app

    def start(self, app=None, target_district: str = "منطقه ۲ و ۵ تهران", interval_seconds: int = 150,
              districts: Optional[List[str]] = None, min_area: Optional[int] = None,
              max_area: Optional[int] = None, rooms: Optional[int] = None):
        if app:
            self.app = app
        if not self.app:
            _console("[ContinuousMonitor] ❌ خطا: Flask App مقداردهی نشده است.")
            return False

        with self.lock:
            if self.is_running:
                # به‌روزرسانی پارامترهای فعال در صورت فراخوانی مجدد
                self.target_district = target_district
                self.interval_seconds = max(60, min(300, interval_seconds))
                self.min_area = min_area
                self.max_area = max_area
                self.rooms = rooms
                if districts:
                    self.custom_districts = districts
                _console(f"[ContinuousMonitor] ℹ️ پارامترهای مانیتور پایش زنده به‌روزرسانی شد: {target_district} | متراژ={min_area}-{max_area} | خواب={rooms}")
                return True

            self.target_district = target_district
            self.interval_seconds = max(60, min(300, interval_seconds))
            self.min_area = min_area
            self.max_area = max_area
            self.rooms = rooms
            self.custom_districts = districts or []
            self._stop_event.clear()
            self.is_running = True

            self.thread = threading.Thread(
                target=self._run_monitor_loop,
                daemon=True,
                name="SaghfDivarContinuousMonitor"
            )
            self.thread.start()
            _console(f"[ContinuousMonitor] 🚀 پایش مداوم دیوار آغاز شد: هدف={self.target_district}، بازه={self.interval_seconds} ثانیه، خواب={rooms}، متراژ={min_area}-{max_area}")
            return True

    def stop(self):
        with self.lock:
            if not self.is_running:
                return True
            self.is_running = False
            self._stop_event.set()
            _console("[ContinuousMonitor] 🛑 دستور توقف پایش مداوم صادر شد.")
            return True

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            status_text = "فعال - در حال شنود و پایش زنده دیوار" if self.is_running else "متوقف شده"
            msg = f"🟢 پایش زنده و خودکار دیوار فعال است ({self.target_district}) | {self.new_owners_today} فایل جدید مالک استخراج شد" if self.is_running else "⚪ پایش زنده غیرفعال است"
            return {
                "is_running": self.is_running,
                "target_district": self.target_district,
                "interval_seconds": self.interval_seconds,
                "min_area": self.min_area,
                "max_area": self.max_area,
                "rooms": self.rooms,
                "custom_districts": self.custom_districts,
                "total_checked": self.total_checked,
                "new_owners_today": self.new_owners_today,
                "last_check_time": self.last_check_time or "در انتظار اولین پایش...",
                "status_text": status_text,
                "status_message": msg,
                "recent_items": list(self.recent_items[-8:]),
                "error_count": self.error_count
            }

    def _dispatch_owner_notification(self, prop, owner=None) -> None:
        """
        اطلاع‌رسانی هدفمند و مشروط (فقط در صورت انطباق با فیلتر کاربر متقاضی)
        عدم ارسال اسپم یا برودکست کور به کانال‌ها بدون درخواست کاربر
        """
        # طبق دستور صریح کاربر و اصول AGENTS.md:
        # بات‌ها مستقل توسعه می‌یابند و کراولر پیام همگانی و کورکورانه به بات‌ها ارسال نمی‌کند.
        # ارسال صرفاً برای کاربرانی مجاز است که فیلتر فعال ثبت کرده باشند و فایل با بودجه و نیاز آن‌ها مطابقت ۱۰۰٪ داشته باشد.
        try:
            from config import Config
            # بررسی فعال بودن نوتیفیکیشن‌های خودکار برودکست (به صورت پیش‌فرض غیرفعال جهت تمرکز بر وب‌سایت)
            if not getattr(Config, 'ENABLE_CRAWLER_BOT_BROADCAST', False):
                return

            from database.models import User, FilterProfile
            from services.matching_engine import MatchingEngine

            # بررسی انطباق با پروفایل‌های متقاضیان فعال
            active_profiles = FilterProfile.query.filter_by(is_auto_crawl_active=True).all()
            if not active_profiles:
                return

            for prof in active_profiles:
                # بررسی انطباق ملک با بودجه و فیلتر کاربر
                if prof.max_price and prop.total_price and prop.total_price > prof.max_price:
                    continue
                if prof.max_deposit and prop.deposit and prop.deposit > prof.max_deposit:
                    continue
                if prof.max_rent and prop.monthly_rent and prop.monthly_rent > prof.max_rent:
                    continue
                if prof.min_area and prop.area and prop.area < prof.min_area:
                    continue

                # ارسال اختصاصی صرفاً به متقاضی منطبق
                if prof.user_id:
                    user = User.query.get(prof.user_id)
                    if user and user.telegram_id:
                        try:
                            from telegram_bot.notifier import send_property_alert
                            send_property_alert(prop, target_chat_id=user.telegram_id)
                        except Exception:
                            pass
                    if user and user.bale_id:
                        try:
                            from bale_bot.notifier import send_property_bale_alert
                            send_property_bale_alert(prop, target_chat_id=user.bale_id)
                        except Exception:
                            pass
        except Exception:
            pass

    def _run_monitor_loop(self):
        """حلقه مداوم پایش در پس‌زمینه با تمرکز ۱۰۰٪ روی مناطق ۲ و ۵ تهران و پارامترهای هدفمند"""
        from crawler.hybrid_divar import HybridDivarCrawler
        from crawler.owner_filter import OwnerFilter, is_stale_ad
        from crawler.dedup import dedup_engine
        from database.db import db
        from database.models import Property, PropertyListing, Owner, FilterProfile, User
        from data.tehran_districts import (
            get_region_districts,
            is_in_region_2_or_5,
            is_in_target_districts,
            get_region_for_district
        )

        crawler = HybridDivarCrawler()

        # استخراج نام تمام محله‌های مناطق ۲ و ۵ تهران
        reg2_districts = [d['name'] for d in get_region_districts('2')]
        reg5_districts = [d['name'] for d in get_region_districts('5')]
        default_districts = list(set(reg2_districts + reg5_districts))

        while not self._stop_event.is_set():
            cycle_start = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            try:
                with self.app.app_context():
                    # اطمینان از مقداردهی اولیه موتور حذف تکراری
                    dedup_engine.initialize_from_db(Property)

                    cycle_new_saved = 0
                    categories_to_check = ['rent-apartment', 'buy-apartment']

                    items_to_notify = []

                    # واکشی داینامیک محله‌های فعال دفتر املاک
                    profile_districts = []
                    try:
                        active_profiles = FilterProfile.query.filter_by(is_auto_crawl_active=True).all()
                        for prof in active_profiles:
                            if prof.active_districts:
                                profile_districts.extend(prof.active_districts)
                    except Exception:
                        pass

                    if self.custom_districts:
                        active_districts = self.custom_districts
                        effective_target = self.target_district or "، ".join(self.custom_districts[:3])
                    elif profile_districts:
                        active_districts = list(dict.fromkeys(profile_districts))
                        effective_target = "پروفایل‌های دفتر: " + "، ".join(active_districts[:3])
                    else:
                        active_districts = default_districts
                        effective_target = self.target_district or "منطقه ۲ و ۵ تهران"

                    with self.lock:
                        self.target_district = effective_target

                    _console(f"[ContinuousMonitor] 🎯 چرخه پایش {now_str}: بازه={self.interval_seconds}s | هدف={effective_target} | محله‌ها={len(active_districts)}")

                    for cat in categories_to_check:
                        if self._stop_event.is_set():
                            break

                        # استخراج با فیلترهای هدفمند (متراژ، خواب، محله)
                        results = crawler.fetch_listings(
                            category_key=cat,
                            limit=20,
                            districts=active_districts,
                            min_area=self.min_area,
                            max_area=self.max_area,
                            rooms=self.rooms
                        )

                        self.total_checked += len(results)

                        for item in results:
                            # استخراج امن مقادیر مالی و شماره تماس
                            item_price = getattr(item, 'total_price', getattr(item, 'price', 0)) or 0
                            item_rent = getattr(item, 'monthly_rent', getattr(item, 'rent_amount', 0)) or 0
                            item_deposit = getattr(item, 'deposit', getattr(item, 'deposit_amount', 0)) or 0
                            
                            item_phone = None
                            item_name = "مالک شخصی"
                            if getattr(item, 'owner_info', None):
                                item_phone = item.owner_info.phone
                                item_name = item.owner_info.name or "مالک شخصی"
                            elif hasattr(item, 'contact_phone'):
                                item_phone = item.contact_phone
                                item_name = getattr(item, 'contact_name', "مالک شخصی")

                            # گیت بازرسی ۰: بررسی مستقیم در دیتابیس برای جلوگیری از ثبت تکراری
                            if item.source_id and Property.query.filter_by(source_id=item.source_id).first():
                                continue

                            # گیت بازرسی ۰.۵: انطباق دقیق متراژ و تعداد خواب درخواستی
                            if self.min_area and item.area and item.area < self.min_area:
                                continue
                            if self.max_area and item.area and item.area > self.max_area:
                                continue
                            if self.rooms and item.rooms and item.rooms != self.rooms:
                                continue

                            # گیت بازرسی ۱: بررسی تکراری در موتور بهینه‌شده
                            if dedup_engine.is_duplicate(
                                title=item.title,
                                description=item.description,
                                source=item.source,
                                source_id=item.source_id,
                                area=item.area,
                                price=item_price,
                                rent=item_rent,
                                deposit=item_deposit,
                                phone=item_phone
                            ):
                                continue

                            # گیت بازرسی ۱.۵: انطباق قطعی جغرافیایی با منطقه ۲ یا ۵ تهران
                            if not is_in_region_2_or_5(item.district, f"{item.title} {item.description}"):
                                continue

                            # گیت بازرسی ۲: فیلتر سخت‌گیرانه مالک و حذف قطعی هم‌خونه، املاکی و عکس‌های تزیینی
                            filter_res = OwnerFilter.evaluate(
                                platform='divar',
                                title=item.title,
                                description=item.description,
                                raw_text=f"{item.title} {item.description}"
                            )

                            if not filter_res.is_personal:
                                continue

                            from crawler.strict_owner_guard import strict_decision
                            guard_dec = strict_decision(item.title, item.description)
                            if not guard_dec.allowed:
                                continue

                            # بررسی تازگی آگهی و حذف قطعی موارد تاریخ‌گذشته
                            if is_stale_ad(f"{item.title} {item.description}"):
                                continue

                            # بررسی اعلان صریح مالکیت
                            is_direct_owner = OwnerFilter.is_direct_owner_declared(item.title, item.description)
                            item_score = 99 if is_direct_owner else max(item.score, 90)
                            owner_badge = "👑 مالک مستقیم (شخصی)" if is_direct_owner else "مالک شخصی"

                            # تعیین داینامیک منطقه شهرداری و محله جهت حفظ اصالت داده (منحصر به ۲ و ۵)
                            item_region = get_region_for_district(item.district) or ('2' if item.district in reg2_districts else '5')
                            resolved_district = item.district or (active_districts[0] if active_districts else 'تهران')
                            resolved_address = item.address or f"تهران، منطقه {item_region}، {resolved_district}"

                            # استخراج شماره تماس با زنجیره بدون سهمیه TextPhoneMiner و سپس استخر نشست‌های دیوار
                            if not item_phone or item_phone == 'نامشخص':
                                from crawler.text_phone_miner import TextPhoneMiner
                                mined = TextPhoneMiner.mine_phone(item.description, item.title)
                                if mined and mined.get('phone'):
                                    item_phone = mined['phone']
                                else:
                                    from crawler.divar_session_pool import DivarSessionPool
                                    token_clean = str(item.source_id).replace('divar_', '').strip()
                                    pool_res = DivarSessionPool.extract_owner_phone(token_clean)
                                    if pool_res.get('success') and pool_res.get('phone'):
                                        item_phone = pool_res['phone']

                            # ایجاد مالک در دیتابیس در صورت نیاز
                            owner_id = None
                            created_or_found_owner = None
                            if item_phone and item_phone != 'نامشخص':
                                existing_owner = Owner.query.filter_by(phone_number=item_phone).first()
                                if not existing_owner:
                                    new_owner = Owner(
                                        full_name=item_name or f"مالک مستقیم ({resolved_district})",
                                        phone_number=item_phone,
                                        urgency='high',
                                        flexibility='معمولی',
                                        notes=f"استخراج زنده دیوار: منطقه {item_region} ({resolved_district})"
                                    )
                                    db.session.add(new_owner)
                                    db.session.flush()
                                    owner_id = new_owner.id
                                    created_or_found_owner = new_owner
                                else:
                                    owner_id = existing_owner.id
                                    created_or_found_owner = existing_owner

                            # ذخیره ملک واقعی با لینک مستقیم معتبر دیوار
                            prop = Property(
                                title=item.title,
                                description=item.description,
                                property_type=item.property_type or 'apartment',
                                deal_type=item.deal_type,
                                total_price=item_price,
                                deposit=item_deposit,
                                monthly_rent=item_rent,
                                area=item.area or 0,
                                rooms=item.rooms or 1,
                                floor=item.floor or 1,
                                total_floors=item.total_floors,
                                build_year=item.build_year or 1400,
                                city='تهران',
                                district=resolved_district,
                                address=resolved_address,
                                has_parking=item.has_parking,
                                has_elevator=item.has_elevator,
                                has_warehouse=item.has_warehouse,
                                has_balcony=item.has_balcony,
                                source=item.source or 'divar',
                                source_id=item.source_id,
                                source_url=item.source_url,  # لینک مستقیم به دیوار
                                owner_id=owner_id,
                                is_personal_owner=True,
                                status='available',
                                score=item_score
                            )
                            prop.images = item.images if isinstance(item.images, list) else []
                            db.session.add(prop)
                            db.session.flush()

                            # ثبت در PropertyListing
                            ad_code = str(item.source_id).replace('divar_', '')[-8:]
                            listing = PropertyListing(
                                ad_code=ad_code,
                                source=item.source or 'divar',
                                source_url=item.source_url,
                                title=item.title,
                                description=item.description,
                                city='تهران',
                                region=item_region,
                                district=resolved_district,
                                deal_type=item.deal_type,
                                deposit=prop.deposit,
                                monthly_rent=prop.monthly_rent,
                                total_price=prop.total_price,
                                area=prop.area,
                                rooms=prop.rooms,
                                is_personal_owner=True
                            )
                            listing.images = prop.images
                            db.session.add(listing)

                            # ثبت در کش حذف تکراری
                            dedup_engine.add_item(
                                title=item.title,
                                description=item.description,
                                source=item.source,
                                source_id=item.source_id,
                                area=item.area,
                                price=item_price,
                                rent=item_rent,
                                deposit=item_deposit,
                                phone=item_phone
                            )

                            cycle_new_saved += 1
                            self.new_owners_today += 1
                            items_to_notify.append((prop, created_or_found_owner))

                            # ذخیره در تاریخچه موارد اخیر
                            with self.lock:
                                self.recent_items.append({
                                    "id": prop.id,
                                    "title": prop.title,
                                    "district": prop.district,
                                    "deal_type": "رهن و اجاره" if prop.deal_type == 'rent' else "فروش",
                                    "area": prop.area,
                                    "url": prop.source_url,
                                    "time": now_str,
                                    "badge": owner_badge
                                })
                                if len(self.recent_items) > 30:
                                    self.recent_items.pop(0)

                            _console(f"[ContinuousMonitor] 🎯 آگهی جدید استخراج و ثبت شد: [{owner_badge}] {prop.title[:45]}... ({prop.source_url})")

                    db.session.commit()

                    if cycle_new_saved > 0:
                        try:
                            from crawler.regional_incremental_engine import regional_engine
                            regional_engine.update_checkpoint(inc_r2=cycle_new_saved)
                        except Exception:
                            pass

                    # ارسال نوتیفیکیشن فوری به دفتر املاک برای هر آگهی کشف‌شده
                    for p, o in items_to_notify:
                        try:
                            self._dispatch_owner_notification(p, o)
                        except Exception as n_err:
                            _console(f"[ContinuousMonitor] ⚠️ خطا در فراخوانی اطلاع‌رسانی: {n_err}")

                    with self.lock:
                        self.last_check_time = now_str
                        self.last_run_timestamp = time.time()

                    if cycle_new_saved > 0:
                        _console(f"[ContinuousMonitor] ✅ پایان چرخه {now_str}: تعداد {cycle_new_saved} فایل جدید مالک در {effective_target} ثبت شد.")

            except Exception as ex:
                self.error_count += 1
                self.last_error = str(ex)
                _console(f"[ContinuousMonitor] ⚠️ خطا در چرخه پایش دیوار: {ex}")
                try:
                    with self.app.app_context():
                        db.session.rollback()
                except Exception:
                    pass

            # محاسبه مدت خواب تا چرخه بعدی
            elapsed = time.time() - cycle_start
            sleep_time = max(10, self.interval_seconds - elapsed)
            if self._stop_event.wait(timeout=sleep_time):
                break

        _console("[ContinuousMonitor] ⏹️ حلقه پایش مداوم متوقف شد.")


# نمونه سراسری (Singleton)
divar_monitor = DivarContinuousMonitor()
