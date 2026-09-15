import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from crawler.crawler_manager import CrawlerManager
from database.models import Property, Owner

def run_divar_crawl():
    app = create_app()
    cm = CrawlerManager(app)
    cm.init_app(app)
    
    print("=" * 65)
    print("🚀 آغاز استخراج عمیق، واقعی و فیلترشده از مرجع اصلی (دیوار)...")
    print("=" * 65)
    
    # استخراج اختصاصی از دیوار برای فروش و رهن/اجاره آپارتمان
    # limit_per_cat = 12 (1.5x depth = 18 per category)
    success, msg = cm.start_crawl_task(
        sources=['divar'],
        categories=['buy-apartment', 'rent-apartment'],
        limit_per_cat=12,
        city='tehran'
    )
    print(f"وضعیت استارت: {success} | {msg}")
    
    import time
    while cm.is_running:
        time.sleep(2)
        print(f"⏳ در حال استخراج... کل: {cm.stats['total_crawled']} | ذخیره جدید: {cm.stats['new_saved']}")
        
    print("=" * 65)
    print(f"✓ پایان استخراج. کل موارد ثبت‌شده: {cm.stats['new_saved']}")
    print("=" * 65)

    with app.app_context():
        sale_count = Property.query.filter_by(deal_type='sale').count()
        rent_count = Property.query.filter_by(deal_type='rent').count()
        print(f"📊 آمار دیتابیس -> فروش: {sale_count} | رهن و اجاره: {rent_count}")
        
        # نمایش نمونه‌های ذخیره شده
        sample_props = Property.query.limit(3).all()
        for p in sample_props:
            print(f"\n[نمونه {p.id}] {p.title}")
            print(f"  منطقه: {p.district} | معامله: {p.deal_type} | متراژ: {p.area} | خواب: {p.rooms}")
            print(f"  طبقه: {p.floor} از {p.total_floors} | سال ساخت: {p.build_year}")
            print(f"  آسانسور: {p.has_elevator} | پارکینگ: {p.has_parking} | انباری: {p.has_warehouse} | بالکن: {p.has_balcony}")
            print(f"  عکس‌های واقعی: {len(p.images)} عدد")
            if p.images:
                print(f"    عکس اول: {p.images[0]}")
            print(f"  مالک: {p.owner.full_name if p.owner else 'ندارد'} | تلفن: {p.owner.phone_number if p.owner else 'ندارد'}")
            print(f"  لینک آگهی: {p.source_url}")

if __name__ == '__main__':
    run_divar_crawl()
