"""
Automated unit & integration test suite for Two-Tier Hybrid Crawler Architecture.
Validates Tier 1 TLS Impersonator, Tier 2 Stealth Solver, Failover Matrix, and Owner Filter.
"""

import pytest
from crawler.network.impersonator import TLSImpersonatorClient, FINGERPRINT_PROFILES
from crawler.fallback_solver import FallbackSolver, FallbackResponse
from crawler.owner_filter import OwnerFilter, extract_phone_number
from crawler.schemas import NormalizedPropertySchema, OwnerSchema
from crawler.dedup import dedup_engine


class TestTwoTierCrawlerAudit:
    def test_tier1_fingerprint_profiles(self):
        assert 'chrome124' in FINGERPRINT_PROFILES
        assert 'chrome120' in FINGERPRINT_PROFILES
        assert 'chrome131' in FINGERPRINT_PROFILES

        c124 = FINGERPRINT_PROFILES['chrome124']
        assert '124' in c124['sec_ch_ua']
        assert 'Chrome/124' in c124['user_agent']

    def test_tier1_context_headers(self):
        client = TLSImpersonatorClient(impersonate="chrome124")
        api_hdrs = client.generate_context_headers("https://api.divar.ir/v8/web-search/tehran/buy-apartment")
        html_hdrs = client.generate_context_headers("https://www.sheypoor.com/iran/real-estate")

        assert api_hdrs['Sec-Fetch-Dest'] == 'empty'
        assert api_hdrs['Sec-Fetch-Mode'] == 'cors'
        assert html_hdrs['Sec-Fetch-Dest'] == 'document'
        assert html_hdrs['Sec-Fetch-Mode'] == 'navigate'

    def test_tier1_session_recycling(self):
        client = TLSImpersonatorClient(impersonate="chrome124", max_requests_per_session=3)
        init_sess = client.session

        # Simulate 3 requests
        client.session_request_count = 3
        # Calling request on a dummy url or triggering recycling
        assert client.session_request_count >= client.max_requests_per_session
        client._init_session()
        assert client.session is not init_sess
        assert client.session_request_count == 0

    def test_fallback_solver_block_detection(self):
        fb = FallbackSolver()
        assert fb.is_blocked_response(403) is True
        assert fb.is_blocked_response(429) is True
        assert fb.is_blocked_response(503) is True
        assert fb.is_blocked_response(200, "<title>Just a moment...</title>") is True
        assert fb.is_blocked_response(200, "<div id='cf-challenge'></div>") is True
        assert fb.is_blocked_response(200, "<html><head><title>سقف</title></head></html>") is False

    def test_fallback_response_wrapper(self):
        resp = FallbackResponse(status_code=200, text='{"status": "success", "count": 5}', url="https://example.com")
        assert resp.status_code == 200
        assert resp.url == "https://example.com"
        assert resp.json()['status'] == 'success'
        assert resp.json()['count'] == 5

    def test_owner_filter_evaluation(self):
        # Direct owner listing
        res_owner = OwnerFilter.evaluate(
            platform='divar',
            title='آپارتمان ۱۱۰ متری نیاوران مالک شخصی',
            description='فروشنده واقعی، سند تک‌برگ، آشپزخانه بزرگ، صاحبخانه هستم و خودم سکونت دارم.'
        )
        assert res_owner.is_personal is True
        assert res_owner.status == 'approved_personal'

        # Agency / Realtor listing
        res_agency = OwnerFilter.evaluate(
            platform='divar',
            title='فروش آپارتمان لوکس فرمانیه',
            description='املاک بزرگ دیپلمات، مشاور شما مهندس رستمی، کمیسیون طبق تعرفه اتحادیه املاک'
        )
        assert res_agency.is_personal is False
        assert res_agency.owner_type == 'agency'

    def test_owner_filter_phone_extraction(self):
        phone_fa = extract_phone_number("شماره تماس مالک: ۰۹۱۲۱۱۱۸۸۹۹")
        assert phone_fa == "09121118899"

        phone_words = extract_phone_number("با شماره نهصد و دوازده یک دو سه چهار پنج شش هفت تماس بگیرید")
        assert phone_words == "09121234567"

    def test_pydantic_schema_and_deduplication(self):
        payload = {
            "source": "divar",
            "source_id": "pytest_test_token_123",
            "source_url": "https://divar.ir/v/pytest_test_token_123",
            "title": "آپارتمان ۱۰۰ متری سعادت‌آباد",
            "deal_type": "sale",
            "district": "سعادت‌آباد",
            "total_price": 20000000000,
            "area": 100,
            "rooms": 2,
            "owner_info": {
                "name": "مالک",
                "phone": "+98-912-444-5566"
            }
        }
        schema = NormalizedPropertySchema(**payload)
        assert schema.owner_info.phone == "09124445566"
        assert schema.total_price == 20000000000

        # Deduplication check
        token = "pytest_test_token_123"
        dedup_engine.mark_seen(token)
        assert dedup_engine.is_duplicate(token) is True
