"""
تست‌های اعتبارسنجی استخر نشست‌ها (DivarSessionPool) و پایش سهمیه روزانه (DivarQuotaTracker)
"""
import pytest
from unittest.mock import patch, MagicMock

from crawler.divar_quota_tracker import DivarQuotaTracker
from crawler.divar_session_pool import DivarSessionPool
from services.divar_contact_service import DivarContactService
from database.models import Property, Owner


@pytest.fixture
def app_context():
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        yield app


@pytest.fixture(autouse=True)
def isolate_quota_file(tmp_path, monkeypatch):
    test_file = str(tmp_path / "test_divar_quota.json")
    monkeypatch.setattr("crawler.divar_quota_tracker.QUOTA_FILE_PATH", test_file)


def test_quota_tracker_initial_state():
    """بررسی سهمیه اولیه روزانه"""
    stats = DivarQuotaTracker.get_today_stats('test_session')
    assert stats['can_extract'] is True
    assert stats['remaining'] == stats['limit']
    assert stats['used_count'] == 0


def test_quota_tracker_consumes_on_normal_attempt():
    """مصرف سهمیه در صورت تلاش واقعی استخراج"""
    stats1 = DivarQuotaTracker.get_today_stats('test_session_2')
    initial_rem = stats1['remaining']

    stats2 = DivarQuotaTracker.record_attempt('test_session_2', token='tok12345', success=True)
    assert stats2['used_count'] == 1
    assert stats2['success_count'] == 1
    assert stats2['remaining'] == initial_rem - 1


def test_quota_tracker_skips_chat_only_without_consuming():
    """عدم مصرف سهمیه برای آگهی‌های چت‌محور (بدون شماره)"""
    stats1 = DivarQuotaTracker.get_today_stats('test_session_3')
    initial_rem = stats1['remaining']
    initial_used = stats1['used_count']

    stats2 = DivarQuotaTracker.record_attempt('test_session_3', token='tokChatOnly', is_chat_only=True)
    assert stats2['used_count'] == initial_used  # سهمیه مصرف نشد
    assert stats2['remaining'] == initial_rem    # سهمیه دست نخورد
    assert stats2['chat_only_skipped'] >= 1


def test_quota_tracker_skips_agency_without_consuming():
    """عدم مصرف سهمیه برای آگهی‌های مشاور/آژانس"""
    stats1 = DivarQuotaTracker.get_today_stats('test_session_4')
    initial_rem = stats1['remaining']
    initial_used = stats1['used_count']

    stats2 = DivarQuotaTracker.record_attempt('test_session_4', token='tokAgency', is_agency=True)
    assert stats2['used_count'] == initial_used  # سهمیه مصرف نشد
    assert stats2['remaining'] == initial_rem    # سهمیه دست نخورد
    assert stats2['agency_skipped'] >= 1


def test_quota_tracker_limits_when_exhausted():
    """توقف در صورت اتمام سهمیه"""
    DivarQuotaTracker.set_limit(2, session_id='test_session_limited')
    assert DivarQuotaTracker.can_extract('test_session_limited') is True

    DivarQuotaTracker.record_attempt('test_session_limited', token='tok1', success=True)
    DivarQuotaTracker.record_attempt('test_session_limited', token='tok2', success=True)

    stats = DivarQuotaTracker.get_today_stats('test_session_limited')
    assert stats['remaining'] == 0
    assert stats['can_extract'] is False
    assert DivarQuotaTracker.can_extract('test_session_limited') is False


def test_session_pool_channels_structure():
    """بررسی ساختار کانال‌های فعال در استخر نشست‌ها"""
    channels = DivarSessionPool.get_available_channels()
    assert isinstance(channels, list)
    assert len(channels) >= 3
    channel_ids = [c['id'] for c in channels]
    assert 'chrome_cdp' in channel_ids
    assert 'local_session' in channel_ids
    assert 'openapi' in channel_ids


def test_session_pool_chat_only_does_not_consume_quota():
    """اگر آگهی فاقد شماره باشد، استخر نشست سهمیه کسر نمی‌کند"""
    with patch('crawler.divar_session_manager.DivarSessionManager.fetch_contact_phone', return_value=None):
        result = DivarSessionPool.extract_owner_phone('gaTest123')
        assert result['success'] is False
        assert result.get('is_chat_only') is True
        assert 'سهمیه روزانه شما مصرف نشد' in result.get('message', '')


def test_session_pool_successful_extraction():
    """استخراج موفق شماره از استخر نشست‌ها با ثبت در سهمیه"""
    with patch('crawler.divar_session_manager.DivarSessionManager.fetch_contact_phone', return_value='09129876543'):
        result = DivarSessionPool.extract_owner_phone('gaReal123')
        assert result['success'] is True
        assert result['phone'] == '09129876543'
        assert 'remaining_quota' in result


def test_contact_service_rejects_agency_without_quota_consumption(app_context):
    """رد زودهنگام فایل آژانس در DivarContactService بدون اتلاف سهمیه"""
    fake_agency_prop = MagicMock(spec=Property)
    fake_agency_prop.id = 9999
    fake_agency_prop.owner_type = 'agency'
    fake_agency_prop.is_personal_owner = False
    fake_agency_prop.owner = None

    res = DivarContactService.fetch_for_property(fake_agency_prop)
    assert res['success'] is False
    assert res.get('rejected_as_agency') is True
    assert 'آژانس' in res.get('message', '')
