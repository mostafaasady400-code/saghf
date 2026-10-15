"""
آزمون‌های جامع استخراج دو مرحله‌ای و پیش‌رونده (Progressive Extraction Tests)
۱. اعتبارسنجی واکشی فوری دیتابیس ۱ هفته اخیر (۱۶۸ ساعت)
۲. تایید فیلتر ۱۰۰٪ مالکین واقعی و حذف واسطه‌ها و فایل‌های شخصی جعلی
۳. اعتبارسنجی تفکیک دو بخشی (موارد دقیق درخواستی + پیشنهادات هوشمند)
۴. اعتبارسنجی آغاز استخراج زنده دیوار در پس‌زمینه بدون مسدود کردن کاربر
۵. اعتبارسنجی اندپوینت‌های API و پل دستیار هوشمند
"""

import pytest
from datetime import datetime, timedelta
from app import create_app
from database.db import db
from database.models import AccessibleListing, Property, SearchRun, SearchRunItem
from services.progressive_extractor import ProgressiveExtractor
from services.assistant.crawler_bridge import CrawlerBridge


@pytest.fixture
def app_context():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        yield app


def test_instant_database_7days_owner_filtering(app_context):
    """تست واکشی فوری دیتابیس ۷ روز اخیر با فیلتر ۱۰۰٪ مالک شخصی"""
    now = datetime.utcnow()

    # پاکسازی رکوردهای تستی قبلی
    AccessibleListing.query.filter(AccessibleListing.source_id.like("test_prog_%")).delete(synchronize_session=False)
    Property.query.filter(Property.source_id.like("test_prog_prop_%")).delete(synchronize_session=False)
    db.session.commit()

    # ۱. مالک شخصی تاییدشده ۲ روز پیش (داخل بازه ۷ روز) - اجاره پونک ۸۵ متر
    l_valid = AccessibleListing(
        source='divar',
        source_id='test_prog_owner_1',
        source_url='https://divar.ir/v/test_prog_owner_1',
        title='آپارتمان ۸۵ متری خوش‌نقشه شخصی پونک',
        description='مالک هستم، بدون واسطه، تماس 09121113355',
        deal_type='rent',
        district='پونک',
        area=85,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=2),
    )

    # ۲. آگهی آژانس/املاک در بازه ۷ روز که باید ۱۰۰٪ رد شود
    l_agency = AccessibleListing(
        source='divar',
        source_id='test_prog_agency_2',
        source_url='https://divar.ir/v/test_prog_agency_2',
        title='آپارتمان ۸۵ متری املاک سقف مشاور کاظمی',
        description='کمیسیون توافقی، همکاران محترم تماس نگیرند',
        deal_type='rent',
        district='پونک',
        area=85,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='explicit_agency',
        published_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(days=1),
    )

    # ۳. آگهی منقضی قدیمی‌تر از ۷ روز (مثلاً ۱۰ روز پیش) که باید حذف شود
    l_expired = AccessibleListing(
        source='divar',
        source_id='test_prog_expired_3',
        source_url='https://divar.ir/v/test_prog_expired_3',
        title='آپارتمان ۸۰ متری منقضی ۱۰ روز پیش',
        description='مالک هستم 09120000000',
        deal_type='rent',
        district='پونک',
        area=80,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(days=10),
        first_seen_at=now - timedelta(days=10),
    )

    db.session.add_all([l_valid, l_agency, l_expired])
    db.session.commit()

    try:
        results = ProgressiveExtractor.get_instant_database_listings(
            deal_type='rent',
            districts=['پونک'],
            min_area=80,
            max_area=90,
            window_hours=168,
        )

        exact = results['exact']
        suggested = results['suggested']
        all_ids = [item['source_id'] for item in exact + suggested]

        # تایید حضور مالک معتبر در بازه ۷ روز
        assert 'test_prog_owner_1' in all_ids, "Valid owner listing within 7 days was not found!"

        # تایید رد قطعی واسطه/املاک
        assert 'test_prog_agency_2' not in all_ids, "Agency listing was not filtered out!"

        # تایید حذف آگهی قدیمی‌تر از ۷ روز
        assert 'test_prog_expired_3' not in all_ids, "Expired listing (>7d) was not excluded!"

        # بررسی فیلدهای استاندارد
        item = next(i for i in exact + suggested if i['source_id'] == 'test_prog_owner_1')
        assert item['owner_phone'] == '09121113355'
        assert 'لینک آگهی' in item['ad_link_html']
        assert '<a href="https://divar.ir/v/test_prog_owner_1"' in item['ad_link_html']
        assert item['published_at_exact'] is not None

    finally:
        AccessibleListing.query.filter(AccessibleListing.source_id.like("test_prog_%")).delete(synchronize_session=False)
        db.session.commit()


def test_progressive_extract_api_endpoint(app_context):
    """تست اندپوینت اختصاصی استخراج دو مرحله‌ای /crawler/api/progressive-extract"""
    client = app_context.test_client()

    payload = {
        'deal_type': 'rent',
        'districts': ['سعادت آباد', 'پونک'],
        'min_area': 70,
        'max_area': 100,
        'window_hours': 168,
    }

    res = client.post('/crawler/api/progressive-extract', json=payload)
    assert res.status_code == 200
    data = res.get_json()

    assert data['success'] is True
    assert data['phase'] == 'progressive_ready'
    assert 'exact' in data
    assert 'suggested' in data
    assert 'meta' in data
    assert data['meta']['window_hours'] == 168
    assert data['meta']['data_source'] == 'database_7days_progressive'


def test_crawler_start_returns_instant_ready(app_context):
    """تست بازگرداندن آنی دیتابیس در فرم استخراج /crawler/start"""
    client = app_context.test_client()

    payload = {
        'categories': ['rent-apartment'],
        'city': 'tehran',
        'district': 'پونک',
    }

    res = client.post('/crawler/start', json=payload)
    assert res.status_code == 202
    data = res.get_json()

    assert data['success'] is True
    assert 'instant_ready' in data
    assert 'instant_count' in data
    assert data['live_active'] is True
    assert 'runs' in data


def test_crawler_bridge_uses_7days_database_without_blocking(app_context):
    """تست اجرای غیرمسدودکننده و استفاده از آرشیو ۷ روز اخیر در پل دستیار هوشمند"""
    res = CrawlerBridge.search_live_listings(
        deal_type='rent',
        districts=['پونک'],
        min_area=75,
        max_area=95,
        window_hours=168,
        refresh_live=True
    )

    assert 'exact' in res
    assert 'suggested' in res
    assert 'meta' in res
    assert res['meta']['window_hours'] == 168
    assert res['meta']['data_source'] in ('persisted_archive', 'persisted_archive_7days')
    assert 'live_refresh' in res['meta']
