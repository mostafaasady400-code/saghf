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
from datetime import datetime
from typing import Dict, Any, List, Optional

class DivarContinuousMonitor:
    def __init__(self):
        self.app = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self._stop_event = threading.Event()
        self.lock = threading.Lock()

        # تنظیمات و وضعیت
        self.target_district = "منطقه ۵"
        self.interval_seconds = 75  # پایش هر ۷۵ ثانیه
        self.total_checked = 0
        self.new_owners_today = 0
        self.last_check_time = None
        self.last_run_timestamp = 0
        self.recent_items: List[Dict[str, Any]] = []
        self.error_count = 0
        self.last_error = None

    def init_app(self, app):
        self.app = app

    def start(self, app=None, target_district: str = "منطقه ۵", interval_seconds: int = 75):
        if app:
            self.app = app
        if not self.app:
            print("[ContinuousMonitor] ❌ خطا: Flask App مقداردهی نشده است.")
            return False

        with self.lock:
            if self.is_running:
                print("[ContinuousMonitor] ℹ️ مانیتور پایش زنده از قبل در حال اجرا است.")
                return True

            self.target_district = target_district
            self.interval_seconds = max(30, interval_seconds)
            self._stop_event.clear()
            self.is_running = True

            self.thread = threading.Thread(
                target=self._run_monitor_loop,
                daemon=True,
                name="SaghfDivarContinuousMonitor"
            )
            self.thread.start()
            print(f"[ContinuousMonitor] 🚀 پایش مداوم دیوار آغاز شد: هدف={self.target_district}، بازه={self.interval_seconds} ثانیه")
            return True

    def stop(self):
        with self.lock:
            if not self.is_running:
                return True
            self.is_running = False
            self._stop_event.set()
            print("[ContinuousMonitor] 🛑 دستور توقف پایش مداوم صادر شد.")
            return True

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            status_text = "فعال - در حال شنود و پایش زنده دیوار" if self.is_running else "متوقف شده"
            msg = f"🟢 پایش زنده و خودکار دیوار فعال است ({self.target_district}) | {self.new_owners_today} فایل جدید مالک استخراج شد" if self.is_running else "⚪ پایش زنده غیرفعال است"
            return {
                "is_running": self.is_running,
                "target_district": self.target_district,
                "interval_seconds": self.interval_seconds,
                "total_checked": self.total_checked,
                "new_owners_today": self.new_owners_today,
                "last_check_time": self.last_check_time or "در انتظار اولین پایش...",
                "status_text": status_text,
                "status_message": msg,
                "recent_items": list(self.recent_items[-8:]),
                "error_count": self.error_count
            }

    def _run_monitor_loop(self):
        """حلقه مداوم پایش در پس‌زمینه"""
        from crawler.hybrid_divar import HybridDivarCrawler
        from crawler.owner_filter import OwnerFilter
        from crawler.dedup import dedup_engine
        from database.db import db
        from database.models import Property, PropertyListing, Owner
        from data.tehran_districts import get_region_districts

        crawler = HybridDivarCrawler()

        # استخراج نام تمام محله‌های منطقه ۵
        reg5_districts = [d['name'] for d in get_region_districts('5')]
        if not reg5_districts:
            reg5_districts = ['پونک', 'جنت آباد', 'صادقیه', 'شهران', 'بلوار فردوس', 'باغ فیض', 'اکباتان']

        print(f"[ContinuousMonitor] 🎯 محله‌های هدف منطقه ۵: {', '.join(reg5_districts[:5])} و...")

        while not self._stop_event.is_set():
            cycle_start = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            try:
                with self.app.app_context():
                    # اطمینان از مقداردهی اولیه موتور حذف تکراری
                    dedup_engine.initialize_from_db(Property)

                    cycle_new_saved = 0
                    categories_to_check = ['rent-apartment', 'buy-apartment']

                    for cat in categories_to_check:
                        if self._stop_event.is_set():
                            break

                        # استخراج صفحه اول (جدیدترین آگهی‌های همین لحظه)
                        results = crawler.fetch_listings(
                            category_key=cat,
                            limit=20,
                            districts=reg5_districts
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

                            # گیت بازرسی ۱: بررسی تکراری
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

                            # گیت بازرسی ۲: فیلتر سخت‌گیرانه مالک و حذف قطعی هم‌خونه و املاکی
                            filter_res = OwnerFilter.evaluate(
                                platform='divar',
                                title=item.title,
                                description=item.description,
                                raw_text=f"{item.title} {item.description}"
                            )

                            if not filter_res.is_personal:
                                continue

                            # بررسی اعلان صریح مالکیت
                            is_direct_owner = OwnerFilter.is_direct_owner_declared(item.title, item.description)
                            item_score = 99 if is_direct_owner else max(item.score, 88)
                            owner_badge = "👑 مالک مستقیم (شخصی)" if is_direct_owner else "مالک شخصی"

                            # ایجاد مالک در دیتابیس در صورت نیاز
                            owner_id = None
                            if item_phone and item_phone != 'نامشخص':
                                existing_owner = Owner.query.filter_by(phone=item_phone).first()
                                if not existing_owner:
                                    new_owner = Owner(
                                        name=item_name or "مالک شخصی",
                                        phone=item_phone,
                                        is_verified=True,
                                        notes=f"استخراج زنده دیوار: {item.district or 'منطقه ۵'}"
                                    )
                                    db.session.add(new_owner)
                                    db.session.flush()
                                    owner_id = new_owner.id
                                else:
                                    owner_id = existing_owner.id

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
                                district=item.district or 'پونک (منطقه ۵)',
                                address=item.address or f"تهران، منطقه ۵، {item.district or 'پونک'}",
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
                                region='5',
                                district=item.district or 'پونک',
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

                            print(f"[ContinuousMonitor] 🎯 آگهی جدید استخراج و ثبت شد: [{owner_badge}] {prop.title[:45]}... ({prop.source_url})")

                    db.session.commit()

                    with self.lock:
                        self.last_check_time = now_str
                        self.last_run_timestamp = time.time()

                    if cycle_new_saved > 0:
                        print(f"[ContinuousMonitor] ✅ پایان چرخه {now_str}: تعداد {cycle_new_saved} فایل جدید مالک در منطقه ۵ ثبت شد.")

            except Exception as ex:
                self.error_count += 1
                self.last_error = str(ex)
                print(f"[ContinuousMonitor] ⚠️ خطا در چرخه پایش دیوار: {ex}")
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

        print("[ContinuousMonitor] ⏹️ حلقه پایش مداوم متوقف شد.")


# نمونه سراسری (Singleton)
divar_monitor = DivarContinuousMonitor()
