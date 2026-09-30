import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app
from crawler.divar_accessible_search import (
    AccessibleSearchCriteria,
    DivarAccessibleSearchCrawler,
    PageFetchResult,
)
from crawler.publication_time import parse_publication_time
from crawler.publisher_classifier import (
    EXPLICIT_AGENCY,
    LIKELY_INTERMEDIARY,
    LIKELY_OWNER,
    UNKNOWN,
    PublisherClassifier,
)
from database.db import db
from database.models import AccessibleListing, SearchRun, SearchRunItem, Property
from services.nlp_extractor import PropertyLeadNLPExtractor
from services.search_run_service import SearchRunService
from services.publisher_semantic_service import get_configured_publisher_classifier


REFERENCE = datetime(2026, 9, 29, 12, 0, 0)


def _page(tokens, cursor=None, *, after_reference_token=None):
    widgets = []
    for token in tokens:
        data = {
            "token": token,
            "title": f"آپارتمان 80 متری پونک {token}",
            "middle_description_text": "80 متر، 2 اتاق",
            "bottom_description_text": "1 ساعت پیش در پونک",
            "is_business": False,
            "action": {"payload": {"token": token, "web_info": {"district_persian": "پونک"}}},
        }
        if token == after_reference_token:
            data["created_at"] = (REFERENCE + timedelta(minutes=1)).isoformat() + "Z"
        widgets.append({"data": {"dto": {"widget_type": "POST_ROW", "data": data}}})
    state = {"nb": {"listWidgets": widgets, "pagination": {"data": {"last_post_date": cursor}}}}
    return '<script>window.__PRELOADED_STATE__ = ' + json.dumps(state, ensure_ascii=False) + ';</script>'


def _details(_token):
    return {
        "description": "مالک هستم و واحد شخصی بدون واسطه واگذار می‌شود.",
        "area": 80,
        "rooms": 2,
        "deposit": 500_000_000,
        "monthly_rent": 20_000_000,
        "has_parking": True,
        "has_elevator": True,
        "features": ["پارکینگ", "آسانسور"],
    }


def test_publisher_classifier_reviewable_evaluation_set():
    path = Path(__file__).parent / "fixtures" / "publisher_classifier_eval.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    assert dataset["dataset_kind"] == "synthetic_reviewable_evaluation"
    predictions = []
    for item in dataset["items"]:
        decision = PublisherClassifier.classify(
            title=item["title"], description=item["description"], structured=item["structured"]
        )
        predictions.append((item["label"], decision.category))
    assert all(expected == actual for expected, actual in predictions)

    # Precision/recall are measured only on this declared synthetic holdout.
    tp = sum(1 for expected, actual in predictions if expected == actual == LIKELY_OWNER)
    fp = sum(1 for expected, actual in predictions if actual == LIKELY_OWNER and expected != LIKELY_OWNER)
    fn = sum(1 for expected, actual in predictions if expected == LIKELY_OWNER and actual != LIKELY_OWNER)
    assert tp / (tp + fp) == 1.0
    assert tp / (tp + fn) == 1.0


def test_structured_agency_overrides_owner_claim_and_ambiguous_stays_unknown():
    agency = PublisherClassifier.classify(
        title="فروش آپارتمان", description="مالک هستم", structured={"is_business": True}
    )
    assert agency.category == EXPLICIT_AGENCY
    assert agency.confidence == 0.99
    assert PublisherClassifier.classify(title="واحد دو خواب", description="نورگیر").category == UNKNOWN


def test_exact_nlp_area_and_ambiguous_deal_type():
    exact = PropertyLeadNLPExtractor.extract_criteria("آپارتمان ۸۰ متری پونک که مالک مستقیم گذاشته")
    assert exact["min_area"] == exact["max_area"] == 80
    assert exact["area_match_mode"] == "exact"
    assert exact["deal_type"] == "any"
    explicit = PropertyLeadNLPExtractor.extract_criteria("سه خوابه اجاره در پونک")
    assert explicit["deal_type"] == "rent"
    assert explicit["rooms"] == 3


def test_semantic_model_is_optional_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert get_configured_publisher_classifier() is None


def test_publication_boundary_update_is_not_publication_and_uncertainty_is_separate():
    inside = parse_publication_time("23 ساعت پیش", REFERENCE)
    outside = parse_publication_time("25 ساعت پیش", REFERENCE)
    yesterday = parse_publication_time("دیروز", REFERENCE)
    exact_old = parse_publication_time("لحظاتی پیش", REFERENCE, REFERENCE - timedelta(days=2))
    assert inside.membership(REFERENCE) == "inside"
    assert outside.membership(REFERENCE) == "outside"
    assert yesterday.membership(REFERENCE) == "uncertain"
    assert exact_old.membership(REFERENCE) == "outside"


def test_cursor_crawl_has_no_result_cap_survives_duplicates_slow_page_and_rechecks_head():
    calls = {"head": 0, "c1": 0}

    def fetch(url):
        cursor = parse_qs(urlsplit(url).query).get("last-post-date", [None])[0]
        if cursor is None:
            calls["head"] += 1
            tokens = [f"t{i}" for i in range(10)]
            if calls["head"] > 1:
                tokens.append("fresh")
            return PageFetchResult(200, _page(tokens, "c1", after_reference_token="fresh"))
        if cursor == "c1":
            calls["c1"] += 1
            if calls["c1"] == 1:
                return PageFetchResult(200, _page([], "c1"))
            return PageFetchResult(200, _page([f"t{i}" for i in range(5, 20)], "c2"))
        return PageFetchResult(200, _page([f"t{i}" for i in range(20, 25)], None))

    records = []
    crawler = DivarAccessibleSearchCrawler(
        page_fetcher=fetch, detail_fetcher=_details, request_delay_seconds=0
    )
    report = crawler.crawl(
        AccessibleSearchCriteria(
            districts=["پونک"], deal_type="rent", min_area=80, max_area=80,
            rooms=2, max_deposit=500_000_000, max_rent=20_000_000,
        ),
        reference_time=REFERENCE,
        max_runtime_seconds=30,
        on_record=lambda record, meta: records.append((record, meta)),
    )
    assert report["unique_received"] == 26
    assert report["duplicates_seen"] == 5
    assert report["new_on_recheck"] == 1
    assert report["pages_traversed"] == 4  # one empty-but-cursored response is evidence too
    assert report["coverage_status"] == "complete_accessible_scope"
    assert report["can_resume"] is False
    assert any(meta["discovered_after_reference"] for _, meta in records)
    assert all("phone" not in record for record, _ in records)


def test_blocked_source_reports_incomplete_without_bypass():
    crawler = DivarAccessibleSearchCrawler(
        page_fetcher=lambda _url: PageFetchResult(429, blocked=True, error="rate limited"),
        detail_fetcher=_details,
        request_delay_seconds=0,
    )
    report = crawler.crawl(
        AccessibleSearchCriteria(districts=["پونک"], deal_type="rent"),
        reference_time=REFERENCE,
    )
    assert report["coverage_status"] == "incomplete"
    assert report["source_status"] == "blocked_or_rate_limited"
    assert report["can_resume"] is True
    assert report["unique_received"] == 0


def test_static_captcha_word_does_not_hide_valid_preloaded_state(monkeypatch):
    class Response:
        status_code = 200
        text = '<script>const captcha="optional";</script><script>window.__PRELOADED_STATE__={"nb":{}};</script>'
        headers = {}

    crawler = DivarAccessibleSearchCrawler(detail_fetcher=_details, request_delay_seconds=0)
    monkeypatch.setattr(crawler.session, "get", lambda *args, **kwargs: Response())
    fetched = crawler._fetch_page("https://divar.ir/s/tehran/rent-apartment")
    assert fetched.status_code == 200
    assert fetched.blocked is False


def test_model_outage_keeps_ambiguous_listing_pending_not_owner():
    attempts = {"count": 0}
    def unavailable_model(_payload):
        attempts["count"] += 1
        raise TimeoutError("model down")

    crawler = DivarAccessibleSearchCrawler(
        page_fetcher=lambda _url: PageFetchResult(200, _page([], None)),
        detail_fetcher=lambda _token: {"description": "واحد نورگیر و آماده تحویل", "area": 80, "rooms": 2},
        semantic_classifier=unavailable_model,
        request_delay_seconds=0,
    )
    candidate = {
        "token": "ambiguous", "source_id": "divar_ambiguous",
        "source_url": "https://divar.ir/v/ambiguous", "title": "آپارتمان دو خواب",
        "district": "پونک", "middle_description": "80 متر، 2 اتاق",
        "bottom_description": "1 ساعت پیش در پونک", "structured": {},
        "structured_published_at": None, "structured_updated_at": None, "raw_image": None,
    }
    record, meta = crawler._enrich_candidate(
        candidate,
        AccessibleSearchCriteria(districts=["پونک"], deal_type="rent", min_area=80, max_area=80, rooms=2),
        REFERENCE,
    )
    assert record["publisher_category"] == UNKNOWN
    assert record["classification_model_status"] == "pending"
    assert meta["publisher_category"] != LIKELY_OWNER
    assert attempts["count"] == 2

    # A second complete failure opens the short circuit; later ambiguous ads
    # are persisted as pending without repeatedly calling the broken service.
    crawler._enrich_candidate(candidate, AccessibleSearchCriteria(deal_type="rent"), REFERENCE)
    before = attempts["count"]
    crawler._enrich_candidate(candidate, AccessibleSearchCriteria(deal_type="rent"), REFERENCE)
    assert attempts["count"] == before


class _MemoryConfig:
    TESTING = True
    DEBUG = True
    SECRET_KEY = "test-only"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    COMPRESS_ALGORITHM = ["gzip"]
    COMPRESS_MIN_SIZE = 500


@pytest.fixture()
def isolated_app():
    app = create_app(_MemoryConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _record(index):
    published = REFERENCE - timedelta(minutes=index + 1)
    return {
        "source": "divar", "source_id": f"divar_p{index}",
        "source_url": f"https://divar.ir/v/p{index}", "title": f"مالک پونک {index}",
        "description": "مالک هستم و بدون واسطه", "city": "tehran", "district": "پونک",
        "deal_type": "rent", "property_type": "apartment", "area": 80.0, "rooms": 2,
        "total_price": None, "deposit": 500_000_000, "monthly_rent": 20_000_000,
        "has_parking": True, "has_elevator": True, "has_warehouse": None,
        "has_balcony": None, "features": ["پارکینگ"], "images": [],
        "published_at": published, "publication_earliest_at": published,
        "publication_latest_at": published, "publication_accuracy": "exact",
        "publication_source_text": "structured_timestamp", "source_updated_at": None,
        "publisher_category": LIKELY_OWNER, "publisher_confidence": 0.82,
        "publisher_reason": "نشانهٔ مستقیم مالک", "publisher_evidence": ["owner_text:مالک هستم"],
        "publisher_classifier_version": "publisher-rules-test", "publisher_checked_at": REFERENCE,
        "classification_model_status": "not_required",
    }


class _FakeCrawler:
    def __init__(self, count=25, fail=False):
        self.count = count
        self.fail = fail

    def crawl(self, _criteria, **kwargs):
        if self.fail:
            raise RuntimeError("simulated source outage")
        for index in range(self.count):
            kwargs["on_record"](_record(index), {
                "temporal_status": "inside", "criteria_match": True,
                "discovered_after_reference": False,
            })
        checkpoint = {"target_index": 1, "cursor": None, "seen_source_ids": [f"divar_p{i}" for i in range(self.count)]}
        kwargs["on_checkpoint"](checkpoint, {"coverage_status": "complete_accessible_scope", "source_status": "completed"})
        return {
            "unique_received": self.count, "within_window": self.count,
            "criteria_matched": self.count, "likely_owner": self.count,
            "explicit_agency": 0, "likely_intermediary": 0, "unknown": 0,
            "pending_model_review": 0, "pages_traversed": 3, "categories_traversed": 1,
            "coverage_status": "complete_accessible_scope", "source_status": "completed",
            "classification_status": "rules_complete", "stop_reason": "source_end",
            "can_resume": False, "checkpoint": checkpoint,
        }


class _InterruptedCrawler(_FakeCrawler):
    def crawl(self, _criteria, **kwargs):
        for index in range(10):
            kwargs["on_record"](_record(index), {
                "temporal_status": "inside", "criteria_match": True,
                "discovered_after_reference": False,
            })
        checkpoint = {"target_index": 0, "cursor": "resume-cursor", "seen_source_ids": [f"divar_p{i}" for i in range(10)]}
        kwargs["on_checkpoint"](checkpoint, {"coverage_status": "incomplete", "source_status": "source_error"})
        return {
            "unique_received": 10, "within_window": 10, "criteria_matched": 10,
            "likely_owner": 10, "explicit_agency": 0, "likely_intermediary": 0,
            "unknown": 0, "pending_model_review": 0, "pages_traversed": 1,
            "coverage_status": "incomplete", "source_status": "source_error",
            "classification_status": "rules_complete", "stop_reason": "simulated outage",
            "can_resume": True, "checkpoint": checkpoint,
        }


def test_persistence_restart_dedup_and_more_than_twenty_paginated_results(isolated_app):
    with isolated_app.app_context():
        criteria = {"deal_type": "rent", "property_type": "apartment", "districts": ["پونک"]}
        first = SearchRunService.create_run(criteria, reference_time=REFERENCE)
        SearchRunService.execute(first.run_id, crawler=_FakeCrawler(25))
        page1 = SearchRunService.paginated_results(first.run_id, page=1, per_page=20)
        page2 = SearchRunService.paginated_results(first.run_id, page=2, per_page=20)
        assert page1["pagination"]["total"] == 25
        assert len(page1["items"]) == 20
        assert len(page2["items"]) == 5

        # A later run sees the same source IDs: listings update, they do not duplicate.
        second = SearchRunService.create_run(criteria, reference_time=REFERENCE)
        SearchRunService.execute(second.run_id, crawler=_FakeCrawler(25))
        assert AccessibleListing.query.count() == 25
        assert SearchRunItem.query.filter_by(run_id=second.run_id).count() == 25

        corrected = SearchRunService.apply_manual_correction(
            page1["items"][0]["id"], LIKELY_INTERMEDIARY, "بازبینی انسانی: معرفی دفتر"
        )
        assert corrected.effective_publisher_category == LIKELY_INTERMEDIARY
        assert SearchRunService.paginated_results(first.run_id, section="main")["pagination"]["total"] == 24


def test_interrupted_run_persists_then_recovers_without_duplicate_loss(isolated_app):
    with isolated_app.app_context():
        criteria = {"deal_type": "rent", "property_type": "apartment", "districts": ["پونک"]}
        run = SearchRunService.create_run(criteria, reference_time=REFERENCE)
        interrupted = SearchRunService.execute(run.run_id, crawler=_InterruptedCrawler())
        assert interrupted.status == "interrupted"
        assert interrupted.can_resume is True
        assert AccessibleListing.query.count() == 10
        recovered = SearchRunService.execute(run.run_id, crawler=_FakeCrawler(25))
        assert recovered.status == "completed"
        assert recovered.can_resume is False
        assert AccessibleListing.query.count() == 25
        assert SearchRunItem.query.filter_by(run_id=run.run_id).count() == 25
        assert recovered.report["within_window"] == 25


def test_api_requires_deal_clarification_and_exposes_paginated_run(isolated_app):
    client = isolated_app.test_client()
    unclear = client.post('/crawler/search-runs', json={
        "query": "آپارتمان ۸۰ متری پونک", "start": False,
    })
    assert unclear.status_code == 400
    assert unclear.get_json()["error"] == "clarification_required"

    created = client.post('/crawler/search-runs', json={
        "query": "آپارتمان ۸۰ متری پونک برای اجاره", "start": False,
    })
    assert created.status_code == 201
    payload = created.get_json()
    assert payload["run"]["criteria"]["min_area"] == 80
    assert payload["run"]["criteria"]["max_area"] == 80
    status = client.get(payload["status_url"])
    assert status.status_code == 200
    assert status.get_json()["run"]["coverage_status"] == "unknown"
    view = client.get(payload["results_url"])
    assert view.status_code == 200
    assert "نتایج جست" in view.get_data(as_text=True)


def test_deferred_pending_queue_processing_and_api(isolated_app):
    with isolated_app.app_context():
        run = SearchRunService.create_run({"deal_type": "sale", "districts": ["پونک"]}, query_text="خرید پونک")
        target_run_id = str(run.run_id)
        listing = AccessibleListing(
            source="divar",
            source_id="divar_test_pending_1",
            source_url="https://divar.ir/v/test_pending_1",
            title="آپارتمان پونک",
            description="متن بدون نشانه واضح",
            deal_type="sale",
            property_type="apartment",
            area=85,
            district='پونک',
            total_price=5000000000,
            publisher_category=UNKNOWN,
            classification_model_status="pending",
            publisher_reason="عدم قطعیت در بررسی اولیه",
        )
        db.session.add(listing)
        db.session.flush()
        link = SearchRunItem(
            run_id=run.run_id,
            listing_id=listing.id,
            temporal_status="inside",
            criteria_match=True,
            publisher_category_snapshot=UNKNOWN,
        )
        db.session.add(link)
        db.session.commit()

        # Test service method
        def fake_classifier(payload):
            return {"category": LIKELY_OWNER, "confidence": 0.85}

        res = SearchRunService.process_pending_classifications(
            run_id=run.run_id,
            classifier=fake_classifier,
        )
        assert res["success"] is True
        assert res["processed"] == 1
        assert res["converted_to_owner"] == 1

        updated = db.session.get(AccessibleListing, listing.id)
        assert updated.publisher_category == LIKELY_OWNER
        assert updated.classification_model_status == "completed"

        # Verify synced to Property table
        prop = Property.query.filter_by(source_id="divar_test_pending_1").first()
        assert prop is not None
        assert prop.is_personal_owner is True

    # Test API endpoint
    client = isolated_app.test_client()
    api_res = client.post(f"/crawler/search-runs/{target_run_id}/process-pending", json={"max_items": 10})
    assert api_res.status_code == 200
    assert api_res.get_json()["success"] is True


def test_mid_page_stopping_preserves_remaining_candidates_without_early_cursor_advance():
    """Verify that stopping mid-page saves remaining candidates and does not prematurely advance next_cursor."""
    fetch_calls = []

    def mock_fetch(url):
        fetch_calls.append(url)
        cursor = parse_qs(urlsplit(url).query).get("last-post-date", [None])[0]
        if cursor is None:
            # Page 1 has 5 candidates
            tokens = [f"tok_{i}" for i in range(5)]
            return PageFetchResult(200, _page(tokens, cursor="cur_page_2"))
        elif cursor == "cur_page_2":
            # Page 2 has 3 candidates
            tokens = [f"tok_{i}" for i in range(5, 8)]
            return PageFetchResult(200, _page(tokens, cursor=None))
        return PageFetchResult(200, _page([], cursor=None))

    records_leg1 = []
    checkpoints_leg1 = []

    crawler1 = DivarAccessibleSearchCrawler(
        page_fetcher=mock_fetch,
        detail_fetcher=_details,
        request_delay_seconds=0,
    )

    # We deliberately abort after candidate 2 (so candidates 0 and 1 are processed, 2, 3, 4 remain)
    count_processed = {"val": 0}
    def hook_record(rec, meta):
        records_leg1.append(rec["source_id"])
        count_processed["val"] += 1

    # Simulate stopping mid-page using a tight max_runtime or custom hook
    import time
    start_t = time.monotonic()
    
    # We patch time.monotonic in crawler loop so after 2 candidates it triggers time_budget_reached
    original_monotonic = time.monotonic
    call_count = {"ticks": 0}
    def mock_monotonic():
        call_count["ticks"] += 1
        # After 2 candidates processed, pretend max_runtime exceeded
        if count_processed["val"] >= 2:
            return start_t + 999.0
        return start_t + 0.1

    import crawler.divar_accessible_search as das
    saved_monotonic = das.time.monotonic
    das.time.monotonic = mock_monotonic

    try:
        report1 = crawler1.crawl(
            AccessibleSearchCriteria(districts=["پونک"], deal_type="rent"),
            reference_time=REFERENCE,
            max_runtime_seconds=10.0,
            on_record=hook_record,
            on_checkpoint=lambda cp, rep: checkpoints_leg1.append(dict(cp)),
        )
    finally:
        das.time.monotonic = saved_monotonic

    assert report1["coverage_status"] == "incomplete"
    assert report1["source_status"] == "time_budget_reached"
    assert len(records_leg1) == 2
    assert records_leg1 == ["divar_tok_0", "divar_tok_1"]

    last_cp = report1["checkpoint"]
    # Check that cursor did NOT prematurely jump to cur_page_2!
    assert last_cp["cursor"] is None
    assert last_cp["next_page_cursor"] == "cur_page_2"
    # Remaining candidates from page 1 must be preserved in checkpoint
    assert len(last_cp["pending_candidates"]) == 3
    remaining_tokens = [c["token"] for c in last_cp["pending_candidates"]]
    assert remaining_tokens == ["tok_2", "tok_3", "tok_4"]

    # Now RESUME with this exact checkpoint!
    records_leg2 = []
    crawler2 = DivarAccessibleSearchCrawler(
        page_fetcher=mock_fetch,
        detail_fetcher=_details,
        request_delay_seconds=0,
    )
    report2 = crawler2.crawl(
        AccessibleSearchCriteria(districts=["پونک"], deal_type="rent"),
        reference_time=REFERENCE,
        checkpoint=last_cp,
        max_runtime_seconds=60.0,
        on_record=lambda rec, meta: records_leg2.append(rec["source_id"]),
    )

    assert report2["coverage_status"] == "complete_accessible_scope"
    assert report2["source_status"] == "completed"
    # Resumed candidates must be processed first (tok_2, tok_3, tok_4), then page 2 (tok_5, tok_6, tok_7)
    assert records_leg2 == [
        "divar_tok_2", "divar_tok_3", "divar_tok_4",
        "divar_tok_5", "divar_tok_6", "divar_tok_7"
    ]
    # In total all 8 candidates are received with zero duplicates and zero skipped!
    assert report2["unique_received"] == 8


def test_ladder_bump_is_not_fresh_publication_and_time_uncertainty():
    """Verify that bumped posts ('نردبان') are not assumed fresh publications without structured evidence."""
    # 1. Bumped text without structured timestamp -> ladder_bump_unknown -> uncertain
    bumped_text = parse_publication_time("نردبان شده در ۱۰ دقیقه پیش در پونک", REFERENCE)
    assert bumped_text.accuracy == "ladder_bump_unknown"
    assert bumped_text.estimated_at is None
    assert bumped_text.membership(REFERENCE) == "uncertain"

    # 2. Ladder flag explicitly passed without structured timestamp -> uncertain
    ladder_flag = parse_publication_time("۱۰ دقیقه پیش", REFERENCE, is_ladder=True)
    assert ladder_flag.accuracy == "ladder_bump_unknown"
    assert ladder_flag.membership(REFERENCE) == "uncertain"

    # 3. Bumped ad that was originally published 5 days ago (structured timestamp old) -> outside
    old_pub = REFERENCE - timedelta(days=5)
    bumped_old = parse_publication_time("نردبان شده دقایقی پیش", REFERENCE, structured_timestamp=old_pub, is_ladder=True)
    assert bumped_old.accuracy == "exact_with_ladder"
    assert bumped_old.membership(REFERENCE) == "outside"

    # 4. Genuine fresh ad without ladder -> inside
    genuine_fresh = parse_publication_time("۱۰ دقیقه پیش", REFERENCE)
    assert genuine_fresh.accuracy == "approx_minute"
    assert genuine_fresh.membership(REFERENCE) == "inside"


def test_single_owner_claim_alone_is_insufficient_and_agent_disclaimer_is_not_intermediary():
    """Verify that 'مالک هستم' alone is insufficient proof and disclaimers are respected."""
    # 1. Bare claim 'مالک هستم' without personal account or corroboration -> UNKNOWN
    bare_claim = PublisherClassifier.classify(
        title="آپارتمان ۷۰ متری پونک",
        description="مالک هستم، تماس بگیرید.",
        structured={},
        model_available=False,
    )
    assert bare_claim.category == UNKNOWN
    assert "unverified_single_owner_claim" in bare_claim.evidence
    assert "ادعای «مالک هستم» به‌تنهایی اثبات مالکیت نیست" in bare_claim.reason

    # 2. Disclaimer: 'مشاوران تماس نگیرند' is an owner signal, NOT an intermediary!
    disclaimer_only = PublisherClassifier.classify(
        title="فروش آپارتمان ۷۰ متری",
        description="مشاوران محترم لطفا تماس نگیرند؛ مستقیم از مالک.",
        structured={},
    )
    assert disclaimer_only.category == LIKELY_OWNER
    assert any("owner_disclaimer" in ev for ev in disclaimer_only.evidence)

    # 3. Complex disclaimers with agency words:
    disclaimer_complex = PublisherClassifier.classify(
        title="اجاره واحد شخصی",
        description="از دفاتر مشاورین محترم املاک خواهشمندم تماس نگیرند. خودم مالک هستم و سکونت خودم بوده.",
        structured={},
    )
    assert disclaimer_complex.category == LIKELY_OWNER

    # 4. 'مالک هستم' corroborated by structured personal account -> LIKELY_OWNER
    corroborated_account = PublisherClassifier.classify(
        title="آپارتمان پونک",
        description="مالک هستم.",
        structured={"is_business": False},
    )
    assert corroborated_account.category == LIKELY_OWNER
    assert "structured:personal_account" in corroborated_account.evidence
