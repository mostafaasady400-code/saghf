import pytest
import sqlite3
from crawler.ad_frequency_guard import AdFrequencyGuard, DB_PATH

@pytest.fixture(autouse=True)
def cleanup_test_data():
    def _clean():
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM phone_ad_records WHERE phone_number LIKE '0919999%'")
            cur.execute("DELETE FROM broker_phone_blacklist WHERE phone_number LIKE '0919999%'")
            conn.commit()
            conn.close()
        except Exception:
            pass
    _clean()
    yield
    _clean()

def test_initial_ad_is_personal():
    test_phone = "09199990001"
    res1 = AdFrequencyGuard.record_ad(test_phone, "token_ad_01", "آپارتمان ۷۰ متری پونک", "پونک")
    assert res1['valid'] is True
    assert res1['is_broker'] is False
    assert res1['ad_count'] == 1

def test_second_ad_is_still_personal():
    test_phone = "09199990002"
    r1 = AdFrequencyGuard.record_ad(test_phone, "token_ad_01", "آپارتمان ۷۰ متری", "پونک")
    r2 = AdFrequencyGuard.record_ad(test_phone, "token_ad_02", "آپارتمان ۸۰ متری", "پونک")
    assert r2['valid'] is True
    assert r2['is_broker'] is False
    assert r2['ad_count'] == 2

def test_third_ad_triggers_broker_flag():
    test_phone = "09199990003"
    AdFrequencyGuard.record_ad(test_phone, "token_ad_01", "ملک ۱", "منطقه ۲")
    AdFrequencyGuard.record_ad(test_phone, "token_ad_02", "ملک ۲", "منطقه ۵")
    res3 = AdFrequencyGuard.record_ad(test_phone, "token_ad_03", "واحد ۹۰ متری سعادت آباد", "سعادت‌آباد")
    assert res3['valid'] is True
    assert res3['is_broker'] is True
    assert res3['ad_count'] == 3
    assert AdFrequencyGuard.is_blacklisted(test_phone) is True

def test_duplicate_token_does_not_increment():
    test_phone = "09199990004"
    r1 = AdFrequencyGuard.record_ad(test_phone, "duplicate_tok_1", "ملک ۱")
    r2 = AdFrequencyGuard.record_ad(test_phone, "duplicate_tok_1", "ملک ۱ مجدد")
    assert r1['ad_count'] == 1
    assert r2['ad_count'] == 1
    assert r2['is_broker'] is False

def test_sync_from_existing_properties():
    res = AdFrequencyGuard.sync_from_existing_properties()
    assert 'total_properties_scanned' in res
    assert res['total_properties_scanned'] > 0
