import threading
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from .hybrid_divar import HybridDivarCrawler
from .hybrid_sheypoor import HybridSheypoorCrawler
from .dedup import dedup_engine
from .fallback_solver import fallback_solver
from .schemas import NormalizedPropertySchema
from .owner_filter import OwnerFilter
from database.db import db
from database.models import Property, Owner

class CrawlerManager:
    """
    مدیر مرکزی معماری هیبریدی سقف (Hybrid Resilient Orchestrator)
    ترکیب کلاینت‌های ضد فینگرپرینتینگ، فیلتر حذف تکراری O(1)، کنترل ریت‌لیمیت
    و پایپ‌لاین اعتبارسنجی داده‌ها با Pydantic و ذخیره‌سازی در دیتابیس SQLite
    """
    def __init__(self, app=None):
        self.app = app
        self.divar_crawler = HybridDivarCrawler()
        self.sheypoor_crawler = HybridSheypoorCrawler()
        self.is_running = False
        self.lock = threading.Lock()
        self.logs: List[Dict[str, str]] = []
        self.stats = {
            'total_crawled': 0,
            'new_saved': 0,
            'duplicates_skipped': 0,
            'last_run': None,
            'status': 'idle', # idle, running, completed, error
            'tls_impersonate_mode': 'Chrome120+ (curl_cffi)',
            'dlq_count': 0
        }

    def init_app(self, app):
        self.app = app
        with self.app.app_context():
            dedup_engine.initialize_from_db(Property)

    def add_log(self, message: str, level: str = 'info'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = {
            'time': timestamp,
            'message': message,
            'level': level
        }
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > 120:
                self.logs.pop(0)
        print(f"[{timestamp}] [{level.upper()}] {message}")

    def start_crawl_task(
        self,
        sources: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        limit_per_cat: int = 35,
        city: str = 'tehran',
        district: Optional[str] = None,
        districts: Optional[List[str]] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        min_deposit: Optional[int] = None,
        max_deposit: Optional[int] = None,
        min_rent: Optional[int] = None,
        max_rent: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        min_year: Optional[int] = None,
        rooms: Optional[int] = None,
        has_parking: Optional[bool] = None,
        has_elevator: Optional[bool] = None,
        has_warehouse: Optional[bool] = None,
        has_balcony: Optional[bool] = None,
        property_type: Optional[str] = None,
        **kwargs
    ):
        if self.is_running:
            return False, "فرآیند کراولینگ در حال حاضر در حال اجرا است."

        if not sources:
            sources = ['divar', 'sheypoor']
        if not categories:
            categories = ['buy-apartment', 'rent-apartment']

        filters_dict = {
            'districts': districts or ([district] if district else []),
            'min_price': min_price,
            'max_price': max_price,
            'min_deposit': min_deposit,
            'max_deposit': max_deposit,
            'min_rent': min_rent,
            'max_rent': max_rent,
            'min_area': min_area,
            'max_area': max_area,
            'min_year': min_year,
            'max_year': kwargs.get('max_year'),
            'min_age': kwargs.get('min_age'),
            'max_age': kwargs.get('max_age'),
            'rooms': rooms,
            'has_parking': has_parking,
            'has_elevator': has_elevator,
            'has_warehouse': has_warehouse,
            'has_balcony': has_balcony,
            'property_type': property_type
        }
        filters_dict.update(kwargs)

        worker_thread = threading.Thread(
            target=self._run_hybrid_worker,
            args=(sources, categories, limit_per_cat, city, district, filters_dict),
            daemon=True
        )
        worker_thread.start()
        return True, "عملیات کراولینگ هیبریدی (TLS Impersonation + Pydantic) آغاز شد."

    def _run_hybrid_worker(self, sources: List[str], categories: List[str], limit_per_cat: int, city: str = 'tehran', district: Optional[str] = None, filters_dict: Optional[Dict[str, Any]] = None):
        self.is_running = True
        self.stats['status'] = 'running'
        self.stats['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filters_dict = filters_dict or {}
        req_districts = filters_dict.get('districts', [])
        dist_str = ', '.join(req_districts) if req_districts else (district or 'کل شهر')
        self.add_log(f"🚀 آغاز موتور کراولینگ هدفمند برای شهر {city} و محله‌های {dist_str}...", 'info')

        saved_count = 0
        skipped_count = 0

        if not self.app:
            self.add_log("خطا: کانتکست اپلیکیشن در دسترس نیست.", 'error')
            self.is_running = False
            self.stats['status'] = 'error'
            return

        with self.app.app_context():
            # اطمینان از کش بودن شناسه‌های دیتابیس
            dedup_engine.initialize_from_db(Property)
            self.divar_crawler.city = city
            self.sheypoor_crawler.city = city

            def on_item_crawled(schema_item: NormalizedPropertySchema):
                nonlocal saved_count, skipped_count
                sid = schema_item.source_id

                # ۱. بررسی اولیه پرچم مالک شخصی
                if not schema_item.is_personal_owner:
                    skipped_count += 1
                    self.add_log(f"آگهی رد شد (غیرشخصی/املاکی): {schema_item.title[:45]}...", 'warning')
                    return

                # ۲. ارزیابی امنیتی مجدد با فیلتر دومرحله‌ای جهت تضمین عدم ورود کوچکترین نشانه املاک/آژانس/مشاوره
                double_check = OwnerFilter.evaluate(
                    platform=schema_item.source,
                    title=schema_item.title,
                    description=schema_item.description or ''
                )
                if not double_check.is_personal:
                    skipped_count += 1
                    self.add_log(f"آگهی در بازبینی فیلتر دومرحله‌ای رد شد: {schema_item.title[:45]}... ({double_check.reason})", 'warning')
                    return

                # گیت نهایی حذف قطعی هرگونه آگهی حاوی کلمات املاک، مشاور، کارشناس و اسامی فیک
                combined_check = f"{schema_item.title} {schema_item.description or ''}"
                for forbidden in [
                    'املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوران', 'مشاورین', 'مشاوره', 'آژانس',
                    'دپارتمان', 'دپارتمان املاک', 'بنگاه', 'کارشناس', 'کارشناسان', 'کارشناس فروش', 'مشاور فروش', 'امین شما',
                    'مشاور شما', 'کارشناس منطقه', 'سرمایه گذاری', 'هلدینگ', 'کمیسیون', 'حق الزحمه', 'فایلینگ', 'موارد مشابه'
                ]:
                    if forbidden in combined_check:
                        skipped_count += 1
                        self.add_log(f"آگهی حاوی واژه املاکی '{forbidden}' در گیت نهایی رد شد: {schema_item.title[:45]}...", 'warning')
                        return

                # گیت نهایی حذف قطعی هرگونه آگهی همخونه و اسکان اشتراکی
                for shared_word in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS:
                    if shared_word in combined_check:
                        skipped_count += 1
                        self.add_log(f"آگهی همخونه/اشتراکی حاوی '{shared_word}' در گیت نهایی رد شد: {schema_item.title[:45]}...", 'warning')
                        return

                # تشخیص و اعطای اولویت حداکثری به آگهی‌های اعلام صریح مالک مستقیم
                is_direct_owner = OwnerFilter.is_direct_owner_declared(schema_item.title, schema_item.description or '')
                if is_direct_owner:
                    schema_item.score = 99
                    schema_item.is_personal_owner = True
                    schema_item.filter_log = "👑 مالک مستقیم و شخصی (اعلام صریح در متن)"
                    if "👑 مالک مستقیم" not in schema_item.features:
                        schema_item.features.insert(0, "👑 مالک مستقیم")

                existing = Property.query.filter_by(source_id=sid).first()
                if existing:
                    skipped_count += 1
                    dedup_engine.mark_seen(sid)
                    return

                # ثبت یا تطبیق مالک
                owner = None
                if schema_item.owner_info and schema_item.owner_info.phone:
                    phone = schema_item.owner_info.phone
                    owner = Owner.query.filter_by(phone_number=phone).first()
                    if not owner:
                        owner = Owner(
                            full_name=schema_item.owner_info.name,
                            phone_number=phone,
                            urgency=schema_item.owner_info.urgency,
                            flexibility=schema_item.owner_info.flexibility,
                            notes=schema_item.owner_info.notes
                        )
                        db.session.add(owner)
                        db.session.flush()

                prop = Property(
                    source=schema_item.source,
                    source_id=sid,
                    source_url=schema_item.source_url,
                    title=schema_item.title,
                    deal_type=schema_item.deal_type,
                    property_type=schema_item.property_type,
                    city=schema_item.city,
                    district=schema_item.district,
                    address=schema_item.address,
                    total_price=schema_item.total_price,
                    meter_price=schema_item.meter_price,
                    deposit=schema_item.deposit,
                    monthly_rent=schema_item.monthly_rent,
                    area=schema_item.area,
                    rooms=schema_item.rooms,
                    floor=schema_item.floor,
                    total_floors=schema_item.total_floors,
                    build_year=schema_item.build_year or 1401,
                    has_elevator=schema_item.has_elevator,
                    has_parking=schema_item.has_parking,
                    has_warehouse=schema_item.has_warehouse,
                    has_balcony=schema_item.has_balcony,
                    description=schema_item.description,
                    status=schema_item.status,
                    score=schema_item.score,
                    is_personal_owner=schema_item.is_personal_owner,
                    owner_type=schema_item.owner_type,
                    filter_log=schema_item.filter_log,
                    owner_id=owner.id if owner else None
                )
                prop.features = schema_item.features
                prop.images = schema_item.images

                db.session.add(prop)

                # ثبت همزمان در جدول PropertyListing جهت موتور تطبیق هوشمند
                try:
                    from database.models import PropertyListing
                    existing_pl = PropertyListing.query.filter_by(ad_code=str(sid)).first()
                    if not existing_pl:
                        pl = PropertyListing(
                            ad_code=str(sid),
                            source=schema_item.source,
                            source_url=schema_item.source_url,
                            title=schema_item.title,
                            description=schema_item.description,
                            city=schema_item.city,
                            region='5',
                            district=schema_item.district or 'منطقه ۵',
                            deal_type=schema_item.deal_type,
                            property_type=schema_item.property_type,
                            deposit=schema_item.deposit or 0,
                            monthly_rent=schema_item.monthly_rent or 0,
                            total_price=schema_item.total_price or 0,
                            area=schema_item.area or 0,
                            rooms=schema_item.rooms or 1,
                            floor=schema_item.floor or 1,
                            build_year=schema_item.build_year or 1400,
                            has_elevator=schema_item.has_elevator,
                            has_parking=schema_item.has_parking,
                            has_warehouse=schema_item.has_warehouse,
                            has_balcony=schema_item.has_balcony,
                            phone_number=owner.phone_number if owner else None,
                            is_personal_owner=True
                        )
                        pl.images = schema_item.images or []
                        db.session.add(pl)
                except Exception:
                    pass

                db.session.commit()
                dedup_engine.mark_seen(sid)
                saved_count += 1

                # Broadcast newly extracted property to Telegram channel/group
                try:
                    from telegram_bot.notifier import send_property_alert
                    send_property_alert(prop)
                except Exception:
                    pass

                with self.lock:
                    self.stats['new_saved'] += 1
                    self.stats['total_crawled'] += 1

                deal_lbl = 'فروش' if prop.deal_type == 'sale' else 'رهن/اجاره'
                phone_lbl = f"📞 {owner.phone_number}" if (owner and owner.phone_number and owner.phone_number.startswith('09')) else "📱 شماره در دیوار محفوظ است"
                self.add_log(f"⚡ [ثبت بلادرنگ] {deal_lbl}: {prop.title[:38]} ({prop.district}) | {phone_lbl}", 'success')

            # اولویت‌دهی محوری به دیوار به عنوان مرجع اصلی آگهی‌ها
            sources = sorted(sources, key=lambda s: 0 if s == 'divar' else 1)

            for source in sources:
                if source == 'divar':
                    self.add_log("⭐ تمرکز ویژه بر پلتفرم مرجع DIVAR (دیوار) به عنوان بانک اصلی آگهی‌ها...", 'info')
                else:
                    self.add_log(f"🔍 اتصال به پلتفرم مکمل {source.upper()}...", 'info')

                for cat in categories:
                    # تخصیص حجم بیشتر به دیوار به عنوان مرجع اصلی
                    cat_limit = int(limit_per_cat * 1.5) if source == 'divar' else limit_per_cat
                    self.add_log(f"در حال استخراج دسته‌بندی {cat} از {source} (سقف {cat_limit} فایل، پایش ۵ روز اخیر)...", 'info')
                    try:
                        if source == 'divar':
                            self.divar_crawler.fetch_listings(
                                category_key=cat,
                                limit=cat_limit,
                                query=district,
                                districts=filters_dict.get('districts'),
                                min_price=filters_dict.get('min_price'),
                                max_price=filters_dict.get('max_price'),
                                min_deposit=filters_dict.get('min_deposit'),
                                max_deposit=filters_dict.get('max_deposit'),
                                min_rent=filters_dict.get('min_rent'),
                                max_rent=filters_dict.get('max_rent'),
                                min_area=filters_dict.get('min_area'),
                                max_area=filters_dict.get('max_area'),
                                min_year=filters_dict.get('min_year'),
                                max_year=filters_dict.get('max_year'),
                                min_age=filters_dict.get('min_age'),
                                max_age=filters_dict.get('max_age'),
                                rooms=filters_dict.get('rooms'),
                                has_parking=filters_dict.get('has_parking'),
                                has_elevator=filters_dict.get('has_elevator'),
                                has_warehouse=filters_dict.get('has_warehouse'),
                                has_balcony=filters_dict.get('has_balcony'),
                                property_type=filters_dict.get('property_type'),
                                on_item_found=on_item_crawled
                            )
                        else:
                            self.sheypoor_crawler.fetch_listings(
                                category_key=cat,
                                limit=cat_limit,
                                query=district,
                                min_price=filters_dict.get('min_price'),
                                max_price=filters_dict.get('max_price'),
                                min_deposit=filters_dict.get('min_deposit'),
                                max_deposit=filters_dict.get('max_deposit'),
                                min_rent=filters_dict.get('min_rent'),
                                max_rent=filters_dict.get('max_rent'),
                                min_area=filters_dict.get('min_area'),
                                max_area=filters_dict.get('max_area'),
                                min_year=filters_dict.get('min_year'),
                                max_year=filters_dict.get('max_year'),
                                min_age=filters_dict.get('min_age'),
                                max_age=filters_dict.get('max_age'),
                                rooms=filters_dict.get('rooms'),
                                has_parking=filters_dict.get('has_parking'),
                                has_elevator=filters_dict.get('has_elevator'),
                                has_warehouse=filters_dict.get('has_warehouse'),
                                has_balcony=filters_dict.get('has_balcony'),
                                on_item_found=on_item_crawled
                            )
                        time.sleep(0.5)
                    except Exception as err:
                        db.session.rollback()
                        self.add_log(f"خطا در پایپ‌لاین {cat}: {str(err)}", 'error')

        with self.lock:
            self.stats['duplicates_skipped'] += skipped_count
            self.stats['total_crawled'] += skipped_count
            self.stats['dlq_count'] = len(fallback_solver.dlq)
            self.stats['status'] = 'completed'
            self.is_running = False

        self.add_log(f"✅ پایپ‌لاین هیبریدی با موفقیت خاتمه یافت. {saved_count} فایل تأیید و ذخیره شد، {skipped_count} فایل تکراری بلافاصله Skip شد.", 'success')

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                'is_running': self.is_running,
                'stats': dict(self.stats),
                'recent_logs': list(self.logs),
                'dedup_cache_size': dedup_engine.size()
            }

crawler_manager = CrawlerManager()
