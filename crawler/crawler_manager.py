import threading
import time
from datetime import datetime
from .divar_crawler import DivarCrawler
from .sheypoor_crawler import SheypoorCrawler
from database.db import db
from database.models import Property, Owner

class CrawlerManager:
    """
    مدیر مرکزی کراولینگ پس‌زمینه دیوار و شیپور با قابلیت استریم لاگ‌های لحظه‌ای
    و ذخیره‌سازی هوشمند فایل‌ها بدون تکراری بودن در دیتابیس SQLite
    """
    def __init__(self, app=None):
        self.app = app
        self.divar_crawler = DivarCrawler()
        self.sheypoor_crawler = SheypoorCrawler()
        self.is_running = False
        self.lock = threading.Lock()
        self.logs = []
        self.stats = {
            'total_crawled': 0,
            'new_saved': 0,
            'duplicates_skipped': 0,
            'last_run': None,
            'status': 'idle' # idle, running, completed, error
        }

    def init_app(self, app):
        self.app = app

    def add_log(self, message, level='info'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = {
            'time': timestamp,
            'message': message,
            'level': level
        }
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > 100:
                self.logs.pop(0)
        print(f"[{timestamp}] [{level.upper()}] {message}")

    def start_crawl_task(self, sources=None, categories=None, limit_per_cat=10):
        """
        اجرای کراولر در یک Thread پس‌زمینه مستقل برای عدم مسدودسازی درخواست‌های وب
        """
        if self.is_running:
            return False, "فرآیند کراولینگ در حال حاضر در حال اجرا است."

        if not sources:
            sources = ['divar', 'sheypoor']
        if not categories:
            categories = ['buy-apartment', 'rent-apartment']

        worker_thread = threading.Thread(
            target=self._run_crawl_worker,
            args=(sources, categories, limit_per_cat),
            daemon=True
        )
        worker_thread.start()
        return True, "عملیات کراولینگ در پس‌زمینه با موفقیت آغاز شد."

    def _run_crawl_worker(self, sources, categories, limit_per_cat):
        self.is_running = True
        self.stats['status'] = 'running'
        self.stats['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.add_log("🚀 آغاز فرآیند کراولینگ هوشمند پلتفرم‌های دیوار و شیپور...", 'info')

        saved_count = 0
        skipped_count = 0

        if not self.app:
            self.add_log("خطا: کانتکست اپلیکیشن در دسترس نیست.", 'error')
            self.is_running = False
            self.stats['status'] = 'error'
            return

        with self.app.app_context():
            for source in sources:
                self.add_log(f"🔍 شروع دریافت داده‌ها از پلتفرم {source.upper()}...", 'info')
                for cat in categories:
                    self.add_log(f"در حال پویش دسته‌بندی {cat} در منبع {source}...", 'info')
                    try:
                        if source == 'divar':
                            items = self.divar_crawler.fetch_listings(category_key=cat, limit=limit_per_cat)
                        else:
                            items = self.sheypoor_crawler.fetch_listings(category_key=cat, limit=limit_per_cat)

                        self.add_log(f"تعداد {len(items)} فایل ملکی از {source} دریافت شد. در حال اعتبارسنجی و ثبت دیتابیس...", 'info')

                        for item in items:
                            source_id = item.get('source_id')
                            existing = Property.query.filter_by(source_id=source_id).first()
                            if existing:
                                skipped_count += 1
                                continue

                            # Create owner record
                            owner_data = item.get('owner_info', {})
                            owner = None
                            if owner_data and owner_data.get('phone'):
                                owner = Owner.query.filter_by(phone_number=owner_data['phone']).first()
                                if not owner:
                                    owner = Owner(
                                        full_name=owner_data.get('name', 'مالک آگهی'),
                                        phone_number=owner_data['phone'],
                                        urgency=owner_data.get('urgency', 'medium'),
                                        notes=f"ثبت خودکار از کراولر {source} برای فایل {item['title']}"
                                    )
                                    db.session.add(owner)
                                    db.session.flush()

                            prop = Property(
                                source=item.get('source', 'divar'),
                                source_id=source_id,
                                source_url=item.get('source_url'),
                                title=item['title'],
                                deal_type=item['deal_type'],
                                property_type=item.get('property_type', 'apartment'),
                                city=item.get('city', 'تهران'),
                                district=item['district'],
                                address=item.get('address'),
                                total_price=item.get('total_price', 0),
                                meter_price=item.get('meter_price', 0),
                                deposit=item.get('deposit', 0),
                                monthly_rent=item.get('monthly_rent', 0),
                                area=item['area'],
                                rooms=item.get('rooms', 2),
                                floor=item.get('floor', 1),
                                build_year=item.get('build_year', 1400),
                                has_elevator=item.get('has_elevator', False),
                                has_parking=item.get('has_parking', False),
                                has_warehouse=item.get('has_warehouse', False),
                                has_balcony=item.get('has_balcony', False),
                                description=item.get('description'),
                                status='raw_crawled',
                                score=item.get('score', 75),
                                owner_id=owner.id if owner else None
                            )
                            prop.features = item.get('features', [])
                            prop.images = item.get('images', [])

                            db.session.add(prop)
                            saved_count += 1

                        db.session.commit()
                        time.sleep(1) # respectful pause
                    except Exception as err:
                        db.session.rollback()
                        self.add_log(f"خطا در پردازش دسته‌بندی {cat}: {str(err)}", 'error')

        self.stats['new_saved'] += saved_count
        self.stats['duplicates_skipped'] += skipped_count
        self.stats['total_crawled'] += (saved_count + skipped_count)
        self.stats['status'] = 'completed'
        self.is_running = False
        self.add_log(f"✅ کراولینگ با موفقیت خاتمه یافت. {saved_count} فایل جدید ثبت شد، {skipped_count} فایل تکراری صرف‌نظر گردید.", 'success')

    def get_status(self):
        with self.lock:
            return {
                'is_running': self.is_running,
                'stats': dict(self.stats),
                'recent_logs': list(self.logs)
            }

crawler_manager = CrawlerManager()
