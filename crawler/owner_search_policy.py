"""Versioned non-secret owner discovery policy for the independent worker."""
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path

DEFAULT_POLICY = Path(__file__).resolve().parent / "config" / "owner_search_policy.json"
FILTER_FIELDS = {"districts", "min_area", "max_area", "rooms", "max_price", "max_deposit", "max_rent", "has_parking", "has_elevator", "has_warehouse", "has_balcony"}


def load_policy(path=DEFAULT_POLICY):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("version") != 1 or policy.get("scope") != {"city": "tehran", "property_type": "apartment", "deal_types": ["rent", "sale"]}:
        raise ValueError("unsupported_owner_policy_scope")
    if policy.get("windows") != {"head_hours": 24, "archive_hours": 168}:
        raise ValueError("unsupported_owner_policy_windows")
    guard = policy.get("owner_guard", {})
    if guard != {"account_type": "personal", "reject_agency_metadata": True, "require_shared_owner_filter_approval": True, "require_direct_owner_claim": True, "reject_phrases": ["فایل شخصی", "کلید در اختیار", "عکس مشابه", "همکار"], "ownership_is_independently_verified": False}:
        raise ValueError("owner_guard_cannot_be_weakened")
    if policy.get("truthfulness") != {"anonymous_fallback": False, "archive_is_live": False, "unknown_contact_is_verified": False, "unknown_publication_is_fresh": False, "coverage_requires_source_evidence": True}:
        raise ValueError("owner_policy_truthfulness_required")
    if policy.get("output") != {"target_total": 30, "source_link_required": True, "deduplicate_source_id": True, "cdn_images_only": True}:
        raise ValueError("unsupported_owner_policy_output")
    filters = policy.get("user_filters")
    if not isinstance(filters, dict) or set(filters) != FILTER_FIELDS:
        raise ValueError("unsupported_owner_policy_filters")
    if not isinstance(filters["districts"], list) or any(not isinstance(d, str) or not d.strip() for d in filters["districts"]):
        raise ValueError("invalid_owner_policy_districts")
    for key, value in filters.items():
        if key == "districts" or value is None:
            continue
        if key.startswith("has_"):
            if not isinstance(value, bool):
                raise ValueError("invalid_owner_policy_amenity")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or (key == "rooms" and int(value) != value):
            raise ValueError("invalid_owner_policy_number")
    if filters["min_area"] is not None and filters["max_area"] is not None and filters["min_area"] > filters["max_area"]:
        raise ValueError("invalid_owner_policy_area_range")
    return policy


def policy_fingerprint(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def search_criteria(policy, deal, kind):
    if deal not in policy["scope"]["deal_types"] or kind not in {"head", "head_backlog", "backfill"}:
        raise ValueError("unsupported_owner_policy_target")
    return {"city": policy["scope"]["city"], "property_type": policy["scope"]["property_type"], "deal_type": deal, "window_hours": policy["windows"]["archive_hours" if kind == "backfill" else "head_hours"], **deepcopy(policy["user_filters"])}
