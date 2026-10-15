import json
from types import SimpleNamespace

import pytest

from crawler.owner_search_policy import load_policy, search_criteria, policy_fingerprint
from crawler.authenticated_watch import AuthenticatedWatch


def test_saved_filter_and_windows_are_exact():
    policy = load_policy()
    for deal in ("rent", "sale"):
        head = search_criteria(policy, deal, "head")
        archive = search_criteria(policy, deal, "backfill")
        assert head["city"] == "tehran" and head["property_type"] == "apartment"
        assert head["min_area"] == 70 and head["max_area"] == 100
        assert head["deal_type"] == deal and head["window_hours"] == 24
        assert archive["window_hours"] == 168
    assert policy["owner_guard"]["require_shared_owner_filter_approval"] is True
    assert policy["truthfulness"]["anonymous_fallback"] is False


def test_criteria_are_independent_copies():
    policy = load_policy()
    criteria = search_criteria(policy, "rent", "head")
    criteria["districts"].append("district")
    assert policy["user_filters"]["districts"] == []


@pytest.mark.parametrize("section,key,value", [("truthfulness", "anonymous_fallback", True), ("owner_guard", "require_shared_owner_filter_approval", False), ("user_filters", "min_area", 101), ("user_filters", "rooms", 1.5), ("user_filters", "max_price", float("nan"))])
def test_policy_rejects_weakened_or_invalid_rules(tmp_path, section, key, value):
    policy = load_policy()
    policy[section][key] = value
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(path)


def test_fingerprint_is_stable_for_equivalent_key_order():
    policy = load_policy()
    assert policy_fingerprint(policy) == policy_fingerprint(dict(reversed(list(policy.items()))))


def test_old_checkpoint_with_different_filters_is_not_reused(tmp_path):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    criteria = search_criteria(watch.policy, "rent", "backfill")
    run = SimpleNamespace(criteria=criteria)
    assert watch._matches_policy(run, "rent", "backfill")
    run.criteria = {**criteria, "min_area": None}
    assert not watch._matches_policy(run, "rent", "backfill")
    run.criteria = criteria
    assert not watch._matches_policy(run, "sale", "backfill")


def test_worker_records_policy_identity(tmp_path):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    assert watch.state["policy_version"] == 1
    assert watch.state["policy_fingerprint"] == policy_fingerprint(load_policy())
