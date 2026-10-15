from urllib.parse import parse_qs, urlsplit

import pytest

from crawler.divar_accessible_search import AccessibleSearchCriteria
from crawler.owner_search_policy import load_policy
from crawler.regional_owner_watch import RegionalDivarSearchCrawler, district_key, prepare_policy, region_catalog


def test_catalog_uses_exact_official_ids_not_stale_aliases():
    catalog, missing = region_catalog()
    assert len(catalog) > 15
    assert len({row["id"] for row in catalog}) == len(catalog)
    assert missing  # Never claim municipal completeness from project aliases.
    assert district_key("باغ‌فیض") == district_key("باغ فیض")


def test_local_regional_policy_does_not_inherit_old_area_limit(tmp_path):
    path = tmp_path / "policy.json"
    scope = prepare_policy(path)
    policy = load_policy(path)
    assert policy["user_filters"]["min_area"] is None
    assert policy["user_filters"]["max_area"] is None
    assert policy["user_filters"]["districts"]
    assert scope["municipal_boundary_coverage"] == "unverified"
    assert load_policy()["user_filters"]["min_area"] == 70


def test_union_target_and_pagination_preserve_all_filters():
    catalog, _ = region_catalog()
    criteria = AccessibleSearchCriteria(districts=[row["name"] for row in catalog], deal_type="rent", min_area=80, max_deposit=1000)
    crawler = RegionalDivarSearchCrawler()
    targets = crawler._build_targets(criteria)
    assert len(targets) == 1
    query = parse_qs(urlsplit(targets[0]["url"]).query)
    assert set(query["districts"][0].split(",")) == {row["id"] for row in catalog}
    assert query["business-type"] == ["personal"]
    assert query["size"] == ["80-"] and query["credit"] == ["0-1000"]
    continued = crawler._with_cursor(targets[0]["url"], "opaque-cursor", 2)
    continuation = parse_qs(urlsplit(continued).query)
    assert all(continuation[key] == value for key, value in query.items())


def test_missing_district_and_title_mentions_never_prove_location():
    criteria = AccessibleSearchCriteria(districts=["پونک"], deal_type="rent")
    row = {"district": "نیاوران", "title": "دسترسی به پونک", "deal_type": "rent", "property_type": "apartment"}
    assert not RegionalDivarSearchCrawler.matches_criteria(row, criteria)
    row["district"] = None
    assert not RegionalDivarSearchCrawler.matches_criteria(row, criteria)
    row["district"] = "پونک"
    assert RegionalDivarSearchCrawler.matches_criteria(row, criteria)


def test_unknown_scope_fails_closed():
    with pytest.raises(ValueError, match="explicit_and_resolvable"):
        RegionalDivarSearchCrawler()._build_targets(AccessibleSearchCriteria(districts=["unknown"]))


def test_repeated_backfill_cycles_do_not_recurse_or_starve_archive(tmp_path, monkeypatch):
    from crawler.authenticated_watch import AuthenticatedWatch
    from crawler.regional_owner_watch import RegionalOwnerWatch
    watch = RegionalOwnerWatch(tmp_path / "state.json", chunk_seconds=120)
    watch.backfill_only = True
    calls = []
    monkeypatch.setattr(AuthenticatedWatch, "_execute", lambda self, *args: calls.append(args))
    assert watch.cycle()["health"] == "running"
    assert watch.cycle()["health"] == "running"
    assert calls == [("rent", "backfill", 120), ("sale", "backfill", 120)] * 2


def test_only_proven_source_completion_switches_to_head_monitor(tmp_path, monkeypatch):
    from crawler.authenticated_watch import AuthenticatedWatch
    from crawler.regional_owner_watch import RegionalOwnerWatch
    watch = RegionalOwnerWatch(tmp_path / "state.json")
    watch.backfill_only = True
    monkeypatch.setattr(AuthenticatedWatch, "cycle", lambda self: self.state)
    watch.state["health"] = "running"
    watch.state["backfill"] = {deal: {"coverage": "incomplete", "can_resume": True} for deal in ("rent", "sale")}
    watch.cycle()
    assert watch.backfill_only
    for deal in ("rent", "sale"):
        watch.state["backfill"][deal] = {"coverage": "complete_accessible_scope", "can_resume": False}
    watch.cycle()
    assert not watch.backfill_only
    assert watch.state["crawl_mode"] == "head_and_archive"


def test_original_date_overrides_recent_bump_in_real_enrichment_contract():
    from datetime import datetime, timezone, timedelta
    from crawler.parsers.divar_native_detail import parse_original_publication
    details = {"description": "مالک هستم", "area": 80, "business_type": "personal", "original_publication": parse_original_publication("انتشار آگهی: ۲۲ شهریور ۱۴۰۵، ۱۶:۲۴")}
    crawler = RegionalDivarSearchCrawler(detail_fetcher=lambda token: details)
    candidate = {"token": "date_test", "source_id": "divar_date_test", "source_url": "https://divar.ir/v/date_test", "title": "آپارتمان", "district": "پونک", "bottom_description": "۱ ساعت پیش در پونک", "structured": {}, "is_ladder": True}
    record, meta = crawler._enrich_candidate(candidate, AccessibleSearchCriteria(districts=["پونک"], deal_type="rent", window_hours=168), datetime(2026,10,9,18))
    assert meta["temporal_status"] == "outside"
    assert record["publication_accuracy"] == "source_minute"
    assert record["published_at"] == datetime(2026,9,13,12,54)
    assert not crawler._publication_evidence
