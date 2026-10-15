"""
آزمون‌های جامع اعتبارسنجی اتصال دستیار هوش مصنوعی به پایپلاین کرولر (CrawlerBridge & AI Gateway)
پوشش‌دهنده:
۱. محاسبه بازه پویا (بازه اصلی ۷۵-۹۰ و بازه پیشنهادی ۷۰-۱۰۰ برای متراژ ۸۰ متری)
۲. فیلتر سخت‌گیرانه حذف واسطه‌ها (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار)
۳. پالایش زمانی بازه ۲۴ ساعت و رتبه‌بندی اولویت ۱ (لحظه‌ای و تا ۳۰ دقیقه) و اولویت ۲ (تا ۲۴ ساعت)
۴. سهمیه‌بندی و ساختار خروجی دو بخشی (موارد دقیق + پیشنهادات هوشمند)
۵. تایید فیلدهای ضروری: شماره تماس مستقیم مالک، زمان دقیق انتشار، لینک و تگ <a> با عنوان «لینک آگهی»
۶. یکپارچگی ابزار search_live_listings در درگاه دستیار هوشمند (Gateway & Baseline)
"""

from datetime import datetime, timedelta
import pytest

from app import create_app
from database.db import db
from database.models import AccessibleListing, Property, Owner
from services.assistant.crawler_bridge import CrawlerBridge, _compute_area_ranges, AGENCY_FORBIDDEN_WORDS
from services.assistant.gateway import ResilientAIAssistantGateway
from services.assistant.memory_manager import AssistantMemoryManager


@pytest.fixture(scope='module')
def app_instance():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        yield app


def test_area_range_computation():
    """تست محاسبه بازه متراژ پویا برای ۸۰ متری: ۷۵-۹۰ اصلی و ۷۰-۱۰۰ مکمل"""
    tight_lo, tight_hi, wide_lo, wide_hi = _compute_area_ranges(min_area=80)
    assert tight_lo == 75, f"Expected tight_lo 75, got {tight_lo}"
    assert tight_hi == 90, f"Expected tight_hi 90, got {tight_hi}"
    assert wide_lo == 70, f"Expected wide_lo 70, got {wide_lo}"
    assert wide_hi == 100, f"Expected wide_hi 100, got {wide_hi}"


def test_agency_forbidden_words_present():
    """اطمینان از وجود تمام کلمات ممنوعه واسطه طبق الزام کاربر"""
    required_words = ['املاک', 'مسکن', 'خانه', 'مشاور', 'کارشناس', 'کمیسیون', 'همکار']
    for w in required_words:
        assert w in AGENCY_FORBIDDEN_WORDS, f"Forbidden word '{w}' missing from AGENCY_FORBIDDEN_WORDS"


def test_crawler_bridge_filtering_and_priority(app_instance):
    """
    تست فیلتر سخت‌گیرانه مالک شخصی، حذف واسطه‌ها، حذف فایل‌های قدیمی‌تر از ۲۴ ساعت
    و رتبه‌بندی اولویت ۱ (<۳۰ دقیقه) و اولویت ۲ (<۲۴ ساعت)
    """
    now = datetime.utcnow()

    # پاکسازی داده‌های تستی قبلی در صورت وجود
    AccessibleListing.query.filter(AccessibleListing.source_id.like("test_bridge_%")).delete(synchronize_session=False)
    db.session.commit()

    # ۱. آگهی مالک شخصی تازه (۱۰ دقیقه پیش) - اولویت ۱ - متراژ ۸۰ (دقیق)
    l_fresh_owner = AccessibleListing(
        source='divar',
        source_id='test_bridge_fresh_owner_1',
        source_url='https://divar.ir/v/test_bridge_fresh_owner_1',
        title='آپارتمان ۸۰ متری نورگیر تک‌واحدی',
        description='مالک هستم بدون واسطه، تماس 09121112233',
        deal_type='rent',
        district='پونک',
        area=80,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(minutes=10),
        first_seen_at=now - timedelta(minutes=10),
    )

    # ۲. آگهی مالک شخصی دیروز (۳ ساعت پیش) - اولویت ۲ - متراژ ۸۵ (دقیق)
    l_older_owner = AccessibleListing(
        source='divar',
        source_id='test_bridge_older_owner_2',
        source_url='https://divar.ir/v/test_bridge_older_owner_2',
        title='آپارتمان ۸۵ متری خوش‌نقشه شخصی',
        description='مالک هستم، اجاره به خانواده موجه 09123334455',
        deal_type='rent',
        district='پونک',
        area=85,
        rooms=2,
        deposit=600_000_000,
        monthly_rent=18_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(hours=3),
        first_seen_at=now - timedelta(hours=3),
    )

    # ۳. آگهی پیشنهادی مکمل با متراژ ۹۵ (بازه ۷۰-۱۰۰) - اولویت ۱ (۱۵ دقیقه پیش)
    l_suggested_owner = AccessibleListing(
        source='divar',
        source_id='test_bridge_suggested_owner_3',
        source_url='https://divar.ir/v/test_bridge_suggested_owner_3',
        title='آپارتمان ۹۵ متری سالن پرده‌خور فول امکانات',
        description='مالک هستم 09127778899',
        deal_type='rent',
        district='پونک',
        area=95,
        rooms=2,
        deposit=700_000_000,
        monthly_rent=20_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(minutes=15),
        first_seen_at=now - timedelta(minutes=15),
    )

    # ۴. آگهی واسطه/املاک که باید قطعا رد شود (دارای کلمه مشاور و املاک)
    l_agency = AccessibleListing(
        source='divar',
        source_id='test_bridge_agency_4',
        source_url='https://divar.ir/v/test_bridge_agency_4',
        title='آپارتمان ۸۰ متری املاک سقف مشاور بهرامی',
        description='کمیسیون یک سر، همکار املاکی تماس نگیرد',
        deal_type='rent',
        district='پونک',
        area=80,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='explicit_agency',
        published_at=now - timedelta(minutes=5),
        first_seen_at=now - timedelta(minutes=5),
    )

    # ۵. آگهی قدیمی‌تر از ۲۴ ساعت که باید قطعا حذف شود (۲۸ ساعت پیش)
    l_expired = AccessibleListing(
        source='divar',
        source_id='test_bridge_expired_5',
        source_url='https://divar.ir/v/test_bridge_expired_5',
        title='آپارتمان ۸۰ متری قدیمی منقضی',
        description='مالک هستم 09120000000',
        deal_type='rent',
        district='پونک',
        area=80,
        rooms=2,
        deposit=500_000_000,
        monthly_rent=15_000_000,
        publisher_category='likely_owner',
        published_at=now - timedelta(hours=28),
        first_seen_at=now - timedelta(hours=28),
    )

    db.session.add_all([l_fresh_owner, l_older_owner, l_suggested_owner, l_agency, l_expired])
    db.session.commit()

    try:
        # فراخوانی متد اصلی پل ارتباطی دستیار به کرولر
        res = CrawlerBridge.search_live_listings(
            deal_type='rent',
            districts=['پونک'],
            min_area=80,
            max_area=80,
            window_hours=24
        )

        exact = res['exact']
        suggested = res['suggested']

        # بررسی رد شدن قطعی واسطه و آگهی منقضی (>۲۴ ساعت)
        all_ids = [item['source_id'] for item in exact + suggested]
        assert 'test_bridge_agency_4' not in all_ids, "Agency listing was not filtered out!"
        assert 'test_bridge_expired_5' not in all_ids, "Expired listing (>24h) was not filtered out!"

        # بررسی تفکیک دوبخشی (دقیق و پیشنهادی)
        exact_ids = [item['source_id'] for item in exact]
        assert 'test_bridge_fresh_owner_1' in exact_ids, "Fresh owner listing missing from exact matches"
        assert 'test_bridge_older_owner_2' in exact_ids, "Older owner listing missing from exact matches"

        suggested_ids = [item['source_id'] for item in suggested]
        assert 'test_bridge_suggested_owner_3' in suggested_ids, "Suggested listing missing from smart suggestions"

        # بررسی رتبه‌بندی زمانی: فایل ۱۰ دقیقه پیش باید اولویت ۱ باشد
        fresh_item = next(i for i in exact if i['source_id'] == 'test_bridge_fresh_owner_1')
        assert fresh_item['priority'] == 1
        assert fresh_item['is_fresh'] is True

        # فایل ۳ ساعت پیش باید اولویت ۲ باشد
        older_item = next(i for i in exact if i['source_id'] == 'test_bridge_older_owner_2')
        assert older_item['priority'] == 2
        assert older_item['is_fresh'] is False

        # فایل اولویت ۱ باید قبل از اولویت ۲ مرتب شده باشد
        assert exact.index(fresh_item) < exact.index(older_item)

        # بررسی فیلدهای ضروری: شماره تماس، تگ <a> لینک آگهی و زمان انتشار
        assert fresh_item['owner_phone'] == '09121112233', f"Phone extraction failed: {fresh_item['owner_phone']}"
        assert 'لینک آگهی' in fresh_item['ad_link_html']
        assert '<a href="https://divar.ir/v/test_bridge_fresh_owner_1"' in fresh_item['ad_link_html']
        assert fresh_item['published_at_exact'] is not None

        # بررسی فرمت‌کننده خروجی نهایی چت
        formatted = CrawlerBridge.format_assistant_response(res, user_query="آپارتمان ۸۰ متری در پونک", deal_type='rent')
        assert formatted['success'] is True
        assert formatted['action'] == 'crawler_results'
        assert 'sections' in formatted
        assert 'exact' in formatted['sections']
        assert 'suggested' in formatted['sections']
        assert 'chat_markdown' in formatted
        assert 'بخش اول: موارد دقیق درخواستی' in formatted['chat_markdown']
        assert 'بخش دوم: پیشنهادات هوشمند' in formatted['chat_markdown']
        assert 'لینک آگهی' in formatted['chat_markdown']

    finally:
        # پاکسازی رکوردها
        AccessibleListing.query.filter(AccessibleListing.source_id.like("test_bridge_%")).delete(synchronize_session=False)
        db.session.commit()


def test_gateway_integration_with_crawler_bridge(app_instance):
    """
    تست اتصال مستقیم درگاه دستیار به کرولر با ورودی متن کاربر «آپارتمان ۸۰ متری»
    و اطمینان از استخراج و اجرای خودکار بدون توقف
    """
    session = AssistantMemoryManager.get_or_create('test_user_session_crawler_bridge')
    session.criteria.districts = ['پونک']

    # بررسی ثبت ابزار جدید search_live_listings در شمای جیمینای
    schema = ResilientAIAssistantGateway._build_gemini_tools_schema()
    tools = schema[0]['function_declarations']
    tool_names = [t['name'] for t in tools]
    assert 'search_live_listings' in tool_names, "search_live_listings tool is not declared in Gemini schema"

    # اجرای پروسه با فرمان متراژ ۸۰ متری
    turn_res = ResilientAIAssistantGateway.process_turn(
        command="آپارتمان ۸۰ متری در پونک رهن و اجاره می‌خواهم",
        session_id=session.session_id
    )

    assert turn_res['success'] is True
    assert turn_res['action'] in ['crawler_results', 'properties_found']
    assert 'sections' in turn_res or 'items' in turn_res
