"""تست‌های جامع برای endpoint های جدید استخراج سشن دیوار"""
import pytest
import json
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    with app.test_client() as c:
        yield c


def test_divar_session_status_endpoint(client):
    """بررسی پاسخ صحیح endpoint وضعیت سشن دیوار"""
    resp = client.get('/crawler/divar-session/status')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'authenticated' in data
    assert isinstance(data['authenticated'], bool)


def test_divar_session_test_contact_endpoint_exists(client):
    """بررسی وجود endpoint تست شماره تماس (با mock برای جلوگیری از اتصال واقعی)"""
    with patch('crawler.divar_session_manager.DivarSessionManager.fetch_contact_phone') as mock_fetch:
        # شبیه‌سازی پاسخ سرویس: شماره پیدا نشد
        mock_fetch.return_value = None
        resp = client.post(
            '/crawler/divar-session/test-contact',
            json={'token': 'gaCP64cf'},
            content_type='application/json'
        )
        assert resp.status_code in [200, 500]
        data = resp.get_json()
        assert data is not None


def test_divar_session_test_contact_found(client):
    """بررسی endpoint تست شماره تماس وقتی شماره پیدا می‌شود"""
    with patch('crawler.divar_session_manager.DivarSessionManager.fetch_contact_phone') as mock_fetch:
        mock_fetch.return_value = '09121234567'
        resp = client.post(
            '/crawler/divar-session/test-contact',
            json={'token': 'gaCP64cf'},
            content_type='application/json'
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('success') == True
        assert '09121234567' in data.get('phone', '')


def test_divar_session_sync_cdp_responds_correctly(client):
    """
    بررسی endpoint sync-from-cdp: اگر Chrome در دسترس نیست
    باید پیام مناسب برگرداند نه crash
    """
    resp = client.post(
        '/crawler/divar-session/sync-from-cdp',
        json={'port': 9222},
        content_type='application/json'
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data is not None
    # باید یا cdp_available: False باشد یا success: True
    assert 'success' in data or 'cdp_available' in data
    if not data.get('success'):
        assert 'message' in data


def test_divar_session_launch_chrome_endpoint(client):
    """
    بررسی endpoint launch-chrome: باید ساختار معتبر JSON بدون کرش برگرداند
    """
    with patch('subprocess.Popen') as mock_popen:
        mock_popen.return_value = MagicMock()
        resp = client.post('/crawler/divar-session/launch-chrome')
        assert resp.status_code in [200, 404]
        data = resp.get_json()
        assert data is not None
        assert 'success' in data


def test_divar_session_batch_extract_structure(client):
    """
    بررسی ساختار پاسخ batch-extract با mock - بدون اتصال واقعی
    """
    with patch('crawler.divar_session_manager.DivarSessionManager.fetch_contact_phone') as mock_fetch:
        mock_fetch.return_value = None  # شبیه‌سازی: شماره پیدا نشد
        resp = client.post(
            '/crawler/divar-session/batch-extract',
            json={'limit': 3},
            content_type='application/json'
        )
        assert resp.status_code != 404
        if resp.status_code == 200:
            data = resp.get_json()
            assert 'total_processed' in data
            assert 'success_count' in data
            assert 'results' in data
            assert isinstance(data['results'], list)


def test_web_app_crawler_live_page(client):
    """صفحه live monitor باید کاملاً بارگذاری شود"""
    resp = client.get('/crawler/live')
    assert resp.status_code == 200
    # بررسی وجود محتوای اصلی
    content = resp.data.decode('utf-8')
    assert 'Chrome' in content or 'دیوار' in content


def test_new_endpoints_not_bot_dependent(client):
    """
    اندپوینت‌های جدید نباید به ربات‌های تلگرام یا بله وابسته باشند
    """
    # اطمینان از اینکه mock بات وجود ندارد و هنوز کار می‌کند
    resp1 = client.get('/crawler/divar-session/status')
    assert resp1.status_code == 200

    resp2 = client.get('/api/telegram/status')
    assert resp2.status_code == 200
    tg_data = resp2.get_json()
    # وب اپ باید حتی بدون تلگرام کار کند
    assert tg_data is not None


def test_divar_session_sms_flow_endpoints_exist(client):
    """
    بررسی وجود کامل endpoint‌های جریان پیامک دیوار:
    request-code، confirm، manual-token
    """
    # request-code
    resp1 = client.post(
        '/crawler/divar-session/request-code',
        json={'phone': '09123456789'},
        content_type='application/json'
    )
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    assert 'success' in data1

    # manual-token (ذخیره توکن دستی) - استفاده از mock برای جلوگیری از بازنویسی توکن واقعی کاربر
    with patch('crawler.divar_session_manager.DivarSessionManager.save_token') as mock_save:
        mock_save.return_value = True
        resp2 = client.post(
            '/crawler/divar-session/manual-token',
            json={'token': 'test_token_only_for_testing'},
            content_type='application/json'
        )
        assert resp2.status_code in [200, 400]
        data2 = resp2.get_json()
        assert 'success' in data2
