import json
import pytest
from datetime import datetime, timezone
from app import app
from database.db import db
from database.models import Property, PropertyListing, Owner
from crawler.regional_incremental_engine import RegionalIncrementalEngine, regional_engine
from crawler.strict_owner_guard import strict_decision


def test_regional_exclusivity():
    """تست انطباق ۱۰۰٪ منطقه ۲ و ۵ و رد قاطع مناطق دیگر"""
    # مناطق ۲ و ۵ باید True باشند
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('سعادت آباد') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('پونک') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('شهرک غرب') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('گیشا') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('مرزداران') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('جنت آباد جنوبی') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('فردوس') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('شهران') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('اکباتان') is True
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('کن') is True

    # مناطق دیگر تهران باید قطعاً False باشند
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('ونک') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('تجریش') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('پاسداران') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('نیاوران') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('تهرانپارس') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('اسکندری') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('فردوسی') is False
    assert RegionalIncrementalEngine.is_valid_region_2_or_5('نارمک') is False


def test_checkpoint_store():
    """تست ثبت و به‌روزرسانی هوشمند چک‌پوینت"""
    chk = regional_engine.load_checkpoint()
    assert isinstance(chk, dict)
    assert 'last_sync_time' in chk

    now = datetime.now(timezone.utc)
    regional_engine.update_checkpoint(new_timestamp=now, token="test_token_123", inc_r2=1, inc_r5=2)

    updated = regional_engine.load_checkpoint()
    assert updated.get("last_post_token") == "test_token_123"
    assert updated.get("total_owners_extracted") >= 3


def test_strict_owner_guard_enforcement():
    """تست فیلترینگ سخت‌گیرانه مالک: رد املاکی و تزیینی و قبول فقط مالک مستقیم"""
    # رد با عکس تزیینی
    res_fake_img = strict_decision("آپارتمان ۸۰ متری", "مالک هستم عکس ها تزیینی است")
    assert res_fake_img.allowed is False

    # رد با عبارت مشاور املاک
    res_broker = strict_decision("آپارتمان ۱۰۰ متری", "مشاور شما در املاک ستاره")
    assert res_broker.allowed is False

    # رد با فایل شخصی املاک
    res_broker_file = strict_decision("آپارتمان ۱۰۰ متری", "فایل کاملا شخصی کلید در اختیار همکار تماس نگیرد")
    assert res_broker_file.allowed is False

    # قبول در صورت اظهار صریح مالکیت بدون الفاظ املاکی
    res_real_owner = strict_decision("آپارتمان ۸۵ متری خوش‌نقشه", "مالک هستم، تخلیه، آماده سکونت. مشاور املاک تماس نگیرد")
    assert res_real_owner.allowed is True


def test_regional_api_endpoints():
    """تست اندپوینت‌های چک‌پوینت، پاک‌سازی و پایش منطقه ۲ و ۵"""
    with app.test_client() as client:
        # ۱. استعلام وضعیت چک‌پوینت
        resp_status = client.get('/crawler/regional-checkpoint/status')
        assert resp_status.status_code == 200
        data_status = resp_status.get_json()
        assert data_status.get('success') is True
        assert 'checkpoint' in data_status

        # ۲. تست پالایش قطعی پایگاه داده
        resp_purge = client.post('/crawler/purge-non-2-5')
        assert resp_purge.status_code == 200
        data_purge = resp_purge.get_json()
        assert data_purge.get('success') is True

        # ۳. تست وضعیت پایش زنده
        resp_rt = client.get('/crawler/realtime-monitor/status')
        assert resp_rt.status_code == 200
