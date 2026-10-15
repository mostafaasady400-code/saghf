import time
from types import SimpleNamespace

import pytest

from crawler.divar_playwright_session import AuthenticatedDivarBrowser, DivarSessionConnectionError
from crawler.parsers.divar_native_detail import parse_native_detail
from crawler.parsers.divar_native_detail import parse_original_publication


def test_original_publication_never_uses_recent_ladder_or_update_time():
    text = "انتشار آگهی: ۲۲ شهریور ۱۴۰۵، ۱۶:۲۴\nآخرین نردبان: ۱۷ مهر ۱۴۰۵، ۲۰:۳۴\nآخرین به‌روزرسانی: ۱۷ مهر ۱۴۰۵، ۲۰:۳۴"
    result = parse_original_publication(text)
    assert result["earliest"] == "2026-09-13T12:54:00+00:00"
    assert result["latest"] == "2026-09-13T12:54:59.999999+00:00"
    assert parse_original_publication("آخرین نردبان: ۱۷ مهر ۱۴۰۵، ۲۰:۳۴") is None


def test_native_publication_is_not_taken_from_advertiser_description():
    text = "انتشار آگهی: ۱۷ مهر ۱۴۰۵، ۲۰:۳۴"
    description = {"widget_type": "DESCRIPTION_ROW", "data": {"text": text}}
    assert "original_publication" not in parse_native_detail({"sections": [{"widgets": [description]}]})
    metadata = {"widget_type": "EXPANDABLE_SECTION", "data": {"widget_list": [description]}}
    assert parse_native_detail({"sections": [{"widgets": [metadata]}]})["original_publication"]["earliest"] == "2026-10-09T17:04:00+00:00"


@pytest.mark.parametrize("text", ["انتشار آگهی: ۳۲ مهر ۱۴۰۵، ۲۰:۳۴", "انتشار آگهی: ۱ مهر ۱۴۰۵، ۲۵:۳۴", "انتشار آگهی: ۱ مهر ۱۳۹۹، ۲۰:۳۴", "انتشار آگهی: نامشخص"])
def test_invalid_original_publication_remains_unknown(text):
    assert parse_original_publication(text) is None


def test_native_metadata_has_no_invented_defaults():
    result = parse_native_detail({"sections": []})
    assert not any(key in result for key in ["area", "rooms", "total_price", "monthly_rent", "has_parking"])
    with pytest.raises(ValueError):
        parse_native_detail({})


def test_native_widgets_and_agency_evidence():
    widgets = [
        {"widget_type": "DESCRIPTION_ROW", "data": {"text": "شرح کامل و واقعی"}},
        {"widget_type": "GROUP_INFO_ROW", "data": {"items": [{"title": "متراژ", "value": "۸۰"}, {"title": "اتاق", "value": "۲"}]}},
        {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "ودیعه", "value": "۵۰۰٬۰۰۰٬۰۰۰ تومان"}},
        {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": "اجاره", "value": "توافقی"}},
        {"widget_type": "GROUP_FEATURE_ROW", "data": {"items": [{"title": "پارکینگ", "available": False}]}},
        {"widget_type": "IMAGE_CAROUSEL", "data": {"items": [{"image": {"url": "https://s100.divarcdn.com/a.jpg"}}, {"url": "https://divarcdn.com.evil.example/a.jpg"}]}},
        {"widget_type": "LAZY_SECTION", "data": {"request_data": {"post_business_type": "premium-panel"}}},
    ]
    result = parse_native_detail({"sections": [{"widgets": widgets}]})
    assert result["description"] == "شرح کامل و واقعی"
    assert result["area"] == 80 and result["rooms"] == 2
    assert result["deposit"] == 500_000_000
    assert "monthly_rent" not in result
    assert result["has_parking"] is False
    assert result["is_agency_post"] is True
    assert result["images"] == ["https://s100.divarcdn.com/a.jpg"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_native_transport_never_falls_back_on_http_failure(monkeypatch, status):
    browser = AuthenticatedDivarBrowser()
    monkeypatch.setattr(browser, "connect", lambda: browser)
    monkeypatch.setattr(browser, "_has_authenticated_cookies", lambda context: True)
    browser._verified_at = time.monotonic()
    browser._context = SimpleNamespace(request=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status=status)))
    with pytest.raises(DivarSessionConnectionError, match=str(status)):
        browser.fetch_detail_json("valid_token")


def test_removed_detail_is_not_retry_loop(monkeypatch):
    browser = AuthenticatedDivarBrowser()
    monkeypatch.setattr(browser, "connect", lambda: browser)
    monkeypatch.setattr(browser, "_has_authenticated_cookies", lambda context: True)
    browser._verified_at = time.monotonic()
    browser._context = SimpleNamespace(request=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status=404)))
    assert browser.fetch_detail_json("removed_token") == {"source_removed": True}
