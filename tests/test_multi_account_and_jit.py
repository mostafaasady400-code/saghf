"""
تست‌های ماتریس استخر چنداکانتی چرخشی (Multi-Account Session Matrix)
و موتور استخراج آنی برحسب تقاضا (Just-In-Time / On-Demand Extraction)
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from database.db import db
from database.models import Property, Owner
from crawler.divar_quota_tracker import DivarQuotaTracker
from crawler.divar_account_manager import DivarAccountManager
from crawler.divar_session_pool import DivarSessionPool


@pytest.fixture
def app_and_client(tmp_path, monkeypatch):
    """ایجاد محیط تستی ایزوله با دیتابیس موقت و ذخیره‌سازی مجزا"""
    test_accounts_file = str(tmp_path / "test_divar_accounts.json")
    test_quota_file = str(tmp_path / "test_divar_quota.json")

    # شروع با استخر خالی تستی
    with open(test_accounts_file, 'w', encoding='utf-8') as f:
        json.dump([], f)

    monkeypatch.setattr("crawler.divar_account_manager.ACCOUNTS_FILE_PATH", test_accounts_file)
    monkeypatch.setattr("crawler.divar_quota_tracker.QUOTA_FILE_PATH", test_quota_file)

    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        # جلوگیری از تغییر فایل توکن واقعی کاربر در طول تست
        with patch('crawler.divar_session_manager.DivarSessionManager.save_token'):
            with patch('crawler.divar_session_manager.DivarSessionManager.save_cookies_dict'):
                with patch('crawler.divar_account_manager.DivarAccountManager._detect_legacy_account', return_value=None):
                    with app.test_client() as client:
                        yield app, client


def test_multi_account_registration_and_pool_summary(app_and_client):
    """بررسی ثبت چند سیم‌کارت در استخر و افزایش متناسب سهمیه تجمیعی"""
    app, client = app_and_client

    # ثبت سیم‌کارت اول
    res1 = DivarAccountManager.register_account(
        phone="09121111111",
        token="token_sim_1",
        refresh_token="rt_sim_1",
        label="سیم‌کارت اول"
    )
    assert res1 is True

    # ثبت سیم‌کارت دوم
    res2 = DivarAccountManager.register_account(
        phone="09122222222",
        token="token_sim_2",
        refresh_token="rt_sim_2",
        label="سیم‌کارت دوم"
    )
    assert res2 is True

    accounts = DivarAccountManager.list_accounts()
    assert len(accounts) == 2

    summary = DivarAccountManager.get_pool_summary()
    assert summary['total_accounts'] == 2
    assert summary['active_accounts'] == 2
    assert summary['max_daily_capacity'] == 50  # ۲۵ * ۲
    assert summary['total_remaining'] == 50
    assert summary['total_used_today'] == 0


def test_multi_account_round_robin_and_exhaustion(app_and_client):
    """بررسی چرخش نوبتی (Round-Robin) و سوئیچ به اکانت بعدی در صورت اتمام سهمیه اکانت اول"""
    app, client = app_and_client

    DivarAccountManager.register_account(
        phone="09110000001",
        token="tok_1",
        label="خط ۱"
    )
    DivarAccountManager.register_account(
        phone="09110000002",
        token="tok_2",
        label="خط ۲"
    )

    # انتخاب اولیه
    first_pick = DivarAccountManager.select_best_account()
    assert first_pick is not None
    assert first_pick['phone'] in ["09110000001", "09110000002"]

    # اتمام سهمیه سیم‌کارت ۱ (مصرف ۲۵ تلاش)
    for i in range(25):
        DivarAccountManager.record_account_usage("09110000001", f"ad_token_{i}")

    # اکنون خط ۱ باید سهمیه ۰ داشته باشد و خط ۲ باید انتخاب شود
    accs = DivarAccountManager.list_accounts()
    acc1 = next(a for a in accs if a['phone'] == "09110000001")
    assert acc1['remaining_quota'] == 0
    assert acc1['can_extract'] is False

    next_pick = DivarAccountManager.select_best_account()
    assert next_pick is not None
    assert next_pick['phone'] == "09110000002"

    summary = DivarAccountManager.get_pool_summary()
    assert summary['total_remaining'] == 25  # فقط سهمیه خط ۲ باقی مانده
    assert summary['total_used_today'] == 25


def test_multi_account_removal(app_and_client):
    """بررسی حذف امن یک سیم‌کارت از استخر"""
    app, client = app_and_client

    DivarAccountManager.register_account(phone="09130000001", token="t1")
    DivarAccountManager.register_account(phone="09130000002", token="t2")
    assert len(DivarAccountManager.list_accounts()) == 2

    removed = DivarAccountManager.remove_account("09130000001")
    assert removed is True

    remaining = DivarAccountManager.list_accounts()
    assert len(remaining) == 1
    assert remaining[0]['phone'] == "09130000002"


def test_jit_endpoint_existing_phone_no_quota_used(app_and_client):
    """در صورت وجود شماره مالک از قبل، استخراج JIT بدون کسر سهمیه فوراً شماره را برمی‌گرداند"""
    app, client = app_and_client

    with app.app_context():
        owner = Owner(full_name="مالک تست", phone_number="09129998877")
        db.session.add(owner)
        db.session.flush()

        prop = Property(
            title="آپارتمان ۸۰ متری سعادت‌آباد",
            source="divar",
            source_url="https://divar.ir/v/wXTest01",
            deal_type="sale",
            district="سعادت‌آباد",
            area=80.0,
            owner_id=owner.id,
            is_personal_owner=True
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    resp = client.post(
        '/crawler/divar-session/extract-phone-jit',
        json={'property_id': prop_id},
        content_type='application/json'
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    assert data['phone'] == "09129998877"
    assert data.get('already_extracted') is True


def test_jit_endpoint_successful_extraction_and_db_link(app_and_client):
    """استخراج موفق شماره با JIT و اتصال خودکار به جدول Owner و دیتابیس سقف"""
    app, client = app_and_client

    with app.app_context():
        prop = Property(
            title="آپارتمان ۷۵ متری پونک بدون شماره",
            source="divar",
            source_url="https://divar.ir/v/wXTest02",
            deal_type="sale",
            district="پونک",
            area=75.0,
            is_personal_owner=True
        )
        db.session.add(prop)
        db.session.commit()
        prop_id = prop.id

    mock_pool_res = {
        'success': True,
        'phone': '09351234567',
        'token': 'wXTest02',
        'channel_used': 'نشست ذخیره‌شده محلی',
        'account_used': '09179001377',
        'remaining_quota': 24
    }

    with patch('crawler.divar_session_pool.DivarSessionPool.extract_owner_phone', return_value=mock_pool_res):
        resp = client.post(
            '/crawler/divar-session/extract-phone-jit',
            json={'property_id': prop_id},
            content_type='application/json'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['phone'] == '09351234567'
        assert data['channel'] == 'نشست ذخیره‌شده محلی'

        # اعتبارسنجی ثبت در دیتابیس
        with app.app_context():
            updated_prop = Property.query.get(prop_id)
            assert updated_prop.owner is not None
            assert updated_prop.owner.phone_number == '09351234567'


def test_jit_endpoint_chat_only_handling(app_and_client):
    """مدیریت پاسخ چت‌محور (Chat-Only) بدون سوختن سهمیه روزانه"""
    app, client = app_and_client

    mock_pool_res = {
        'success': False,
        'token': 'wXChat01',
        'is_chat_only': True,
        'remaining_quota': 25,
        'message': 'این آگهی شماره تماس عمومی ندارد'
    }

    with patch('crawler.divar_session_pool.DivarSessionPool.extract_owner_phone', return_value=mock_pool_res):
        resp = client.post(
            '/crawler/divar-session/extract-phone-jit',
            json={'token': 'wXChat01'},
            content_type='application/json'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is False
        assert data['is_chat_only'] is True


def test_jit_endpoint_quota_exceeded_returns_429(app_and_client):
    """برگشت کد ۴۲۹ در صورت تکمیل ظرفیت امن روزانه"""
    app, client = app_and_client

    mock_pool_res = {
        'success': False,
        'quota_exceeded': True,
        'message': 'سهمیه امن روزانه استخراج شماره برای امروز مصرف شده است'
    }

    with patch('crawler.divar_session_pool.DivarSessionPool.extract_owner_phone', return_value=mock_pool_res):
        resp = client.post(
            '/crawler/divar-session/extract-phone-jit',
            json={'token': 'wXQuota01'},
            content_type='application/json'
        )
        assert resp.status_code == 429
        data = resp.get_json()
        assert data['quota_exceeded'] is True


def test_accounts_api_endpoints(app_and_client):
    """بررسی اندپوینت‌های وب API استخر چنداکانتی"""
    app, client = app_and_client

    # ۱. استعلام لیست استخر
    resp = client.get('/crawler/divar-session/accounts')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'total_accounts' in data
    assert 'total_remaining' in data

    # ۲. درخواست کد پیامک با شماره نامعتبر
    resp_req = client.post(
        '/crawler/divar-session/accounts/request-code',
        json={'phone': '1234'},
        content_type='application/json'
    )
    assert resp_req.status_code == 200
    assert resp_req.get_json()['success'] is False

    # ۳. حذف اکانت از طریق API
    resp_rem = client.post(
        '/crawler/divar-session/accounts/remove',
        json={'phone': '09120000000'},
        content_type='application/json'
    )
    assert resp_rem.status_code == 200
    assert 'pool' in resp_rem.get_json()
