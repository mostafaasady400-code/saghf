import threading
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from .hybrid_divar import HybridDivarCrawler
from .hybrid_sheypoor import HybridSheypoorCrawler
from .dedup import dedup_engine
from .fallback_solver import fallback_solver
from .schemas import NormalizedPropertySchema
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

    def start_crawl_task(self, sources: Optional[List[str]] = None, categories: Optional[List[str]] = None, limit_per_cat: int = 10):
        if self.is_running:
            return False, "فرآیند کراولینگ در حال حاضر در حال اجرا است."

        if not sources:
            sources = ['divar', 'sheypoor']
        if not categories:
            categories = ['buy-apartment', 'rent-apartment']

        worker_thread = threading.Thread(
            target=self._run_hybrid_worker,
            args=(sources, categories, limit_per_cat),
            daemon=True
        )
        worker_thread.start()
        return True, "عملیات کراولینگ هیبریدی (TLS Impersonation + Pydantic) آغاز شد."

    def _run_hybrid_worker(self, sources: List[str], categories: List[str], limit_per_cat: int):
        self.is_running = True
        self.stats['status'] = 'running'
        self.stats['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.add_log("🚀 آغاز موتور کراولینگ هیبریدی (لایه اول: Fast-Path با امضای TLS کروم)...", 'info')

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

            for source in sources:
                self.add_log(f"🔍 اتصال امن به پلتفرم {source.upper()} با شبیه‌سازی فریم‌های HTTP/2...", 'info')
                for cat in categories:
                    self.add_log(f"در حال استخراج دسته‌بندی {cat} از {source} با سطل توکن شبه‌انسانی...", 'info')
                    try:
                        if source == 'divar':
                            validated_items: List[NormalizedPropertySchema] = self.divar_crawler.fetch_listings(category_key=cat, limit=limit_per_cat)
                        else:
                            validated_items: List[NormalizedPropertySchema] = self.sheypoor_crawler.fetch_listings(category_key=cat, limit=limit_per_cat)

                        self.add_log(f"تعداد {len(validated_items)} رکورد با اعتبارسنجی Pydantic دریافت شد. در حال اعتبارسنجی پایگاه داده...", 'info')

                        for schema_item in validated_items:
                            sid = schema_item.source_id
                            existing = Property.query.filter_by(source_id=sid).first()
                            if existing:
                                skipped_count += 1
                                dedup_engine.mark_seen(sid)
                                continue

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
                                build_year=schema_item.build_year or 1401,
                                has_elevator=schema_item.has_elevator,
                                has_parking=schema_item.has_parking,
                                has_warehouse=schema_item.has_warehouse,
                                has_balcony=schema_item.has_balcony,
                                description=schema_item.description,
                                status=schema_item.status,
                                score=schema_item.score,
                                owner_id=owner.id if owner else None
                            )
                            prop.features = schema_item.features
                            prop.images = schema_item.images

                            db.session.add(prop)
                            dedup_engine.mark_seen(sid)
                            saved_count += 1

                        db.session.commit()
                        time.sleep(0.5)
                    except Exception as err:
                        db.session.rollback()
                        self.add_log(f"خطا در پایپ‌لاین {cat}: {str(err)}", 'error')

        with self.lock:
            self.stats['new_saved'] += saved_count
            self.stats['duplicates_skipped'] += skipped_count
            self.stats['total_crawled'] += (saved_count + skipped_count)
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
