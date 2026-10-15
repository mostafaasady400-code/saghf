"""Independent regions 2/5 discovery. No contact harvesting or ownership proof."""
import argparse
import json
import math
import os
import time
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crawler.authenticated_watch import AuthenticatedWatch, WorkerLock, save_state
from crawler.divar_accessible_search import DivarAccessibleSearchCrawler
from crawler.owner_search_policy import load_policy

ROOT = Path(__file__).resolve().parents[1]


def district_key(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.translate(str.maketrans({"ي": "ی", "ك": "ک"}))
    return "".join(c for c in value if not c.isspace() and unicodedata.category(c) != "Cf")


def region_catalog():
    # Project region names are a scope catalog, NOT municipal boundary proof.
    # Resolve exact official names, never broad substring or historic alias IDs.
    from data.tehran_districts import REGION_2_DISTRICT_NAMES, REGION_5_DISTRICT_NAMES
    official = json.loads((ROOT / "data/divar_official_districts.json").read_text(encoding="utf-8"))["districts"]
    by_name = {district_key(row["name"]): row for row in official}
    mapped = {}
    missing = []
    for name in dict.fromkeys(REGION_2_DISTRICT_NAMES + REGION_5_DISTRICT_NAMES):
        row = by_name.get(district_key(name))
        if row is None:
            missing.append(name)
        else:
            mapped[str(row["id"])] = {"name": row["name"], "id": str(row["id"])}
    if not mapped:
        raise ValueError("regional_district_catalog_unavailable")
    return list(mapped.values()), sorted(set(missing))


class RegionalDivarSearchCrawler(DivarAccessibleSearchCrawler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._publication_evidence = {}
        original_fetcher = self.detail_fetcher
        def capture(token):
            details = original_fetcher(token)
            if isinstance(details, dict) and details.get("original_publication"):
                self._publication_evidence[token] = details["original_publication"]
            return details
        self.detail_fetcher = capture

    def _enrich_candidate(self, candidate, criteria, reference_time):
        token = candidate["token"]
        self._publication_evidence.pop(token, None)
        try:
            record, meta = super()._enrich_candidate(candidate, criteria, reference_time)
            evidence = self._publication_evidence.get(token)
            if evidence:
                from crawler.publication_time import PublicationWindow
                earliest = datetime.fromisoformat(evidence["earliest"]).astimezone(timezone.utc).replace(tzinfo=None)
                latest = datetime.fromisoformat(evidence["latest"]).astimezone(timezone.utc).replace(tzinfo=None)
                window = PublicationWindow(earliest, earliest, latest, evidence["accuracy"], evidence["source"])
                record.update(published_at=earliest, publication_earliest_at=earliest,
                              publication_latest_at=latest, publication_accuracy=window.accuracy,
                              publication_source_text=window.source_text)
                meta["temporal_status"] = window.membership(reference_time, criteria.window_hours)
                meta["discovered_after_reference"] = meta["temporal_status"] == "after_reference"
            return record, meta
        finally:
            self._publication_evidence.pop(token, None)

    def _build_targets(self, criteria):
        catalog, _ = region_catalog()
        by_name = {district_key(row["name"]): row["id"] for row in catalog}
        requested = [district_key(name) for name in criteria.districts]
        if not requested or any(name not in by_name for name in requested):
            raise ValueError("regional_scope_must_be_explicit_and_resolvable")
        targets = super()._build_targets(replace(criteria, districts=[]))
        ids = sorted({by_name[name] for name in requested}, key=int)
        for target in targets:
            parts = urlsplit(target["url"])
            params = parse_qsl(parts.query, keep_blank_values=True) + [("districts", ",".join(ids))]
            target["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
            target["district"] = "regions_2_5_project_catalog"
        return targets

    @staticmethod
    def matches_criteria(record, criteria):
        # A title mentioning Punak cannot move an ad from another district.
        allowed = {district_key(name) for name in criteria.districts}
        if district_key(record.get("district")) not in allowed:
            return False
        return DivarAccessibleSearchCrawler.matches_criteria(record, replace(criteria, districts=[]))


class RegionalOwnerWatch(AuthenticatedWatch):
    def cycle(self):
        state = super().cycle()
        if getattr(self, "backfill_only", False) and state.get("health") == "running" and all(
            state.get("backfill", {}).get(deal, {}).get("coverage") == "complete_accessible_scope"
            and state["backfill"][deal].get("can_resume") is False for deal in ("rent", "sale")
        ):
            self.backfill_only = False
            state["crawl_mode"] = "head_and_archive"
            save_state(self.path, state)
        return state

    def _execute(self, deal, kind, seconds):
        if getattr(self, "backfill_only", False):
            if kind != "backfill":
                return
            seconds = self.chunk_seconds
        return super()._execute(deal, kind, seconds)

    def _get_crawler(self):
        if self._crawler is None:
            from crawler.divar_authenticated_http import AuthenticatedDivarHTTP
            self._crawler = RegionalDivarSearchCrawler(browser_session=AuthenticatedDivarHTTP(cdp_url=self.cdp_url))
        return self._crawler


def prepare_policy(path):
    catalog, missing = region_catalog()
    policy = load_policy()
    policy["user_filters"].update(districts=[row["name"] for row in catalog], min_area=None, max_area=None)
    # Local generated policy is non-secret, versioned by the base fingerprint.
    save_state(path, policy)
    return {"municipal_regions_requested": [2, 5], "mapped_districts": len(catalog),
            "unresolved_catalog_names": missing, "municipal_boundary_coverage": "unverified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--backfill-only", action="store_true")
    parser.add_argument("--chunk-seconds", type=float, default=120)
    parser.add_argument("--interval", type=float, default=120)
    parser.add_argument("--cdp-url", default=None)
    args = parser.parse_args()
    if any(not math.isfinite(v) or v <= 0 for v in (args.chunk_seconds, args.interval)):
        parser.error("Time limits must be finite and positive")
    os.environ["SAGHF_LEGACY_DIVAR_MONITOR"] = "0"
    from crawler.strict_owner_guard import install_strict_owner_guard
    install_strict_owner_guard()
    policy_path = ROOT / "instance/regions-2-5-policy.json"
    with WorkerLock(ROOT / "instance/authenticated-watch.lock"):
        scope = prepare_policy(policy_path)
        from app import app
        from database.db import db
        watch = RegionalOwnerWatch(ROOT / "instance/regions-2-5-watch.json", chunk_seconds=args.chunk_seconds,
                                   head_seconds=30, interval=args.interval, policy_path=policy_path, cdp_url=args.cdp_url)
        if watch.state.get("publication_schema_version") != 2:
            # Reinspect prior candidates with authoritative original dates.
            # Database runs/records remain untouched; retain their IDs for audit.
            watch.state.setdefault("superseded_runs", []).extend(
                value["run_id"] for kind in ("head", "head_backlog", "backfill")
                for value in watch.state.get(kind, {}).values() if value.get("run_id")
            )
            for kind in ("head", "head_backlog", "backfill", "pending_heads"):
                watch.state[kind] = {}
            watch.state["publication_schema_version"] = 2
        watch.state.update(geographic_scope=scope, contact_collection="disabled",
                           independent_ownership_verified=False, worker_pid=os.getpid(), worker_active=True)
        watch.backfill_only = args.backfill_only and watch.state.get("crawl_mode") != "head_and_archive"
        watch.state["crawl_mode"] = "seven_day_backfill" if watch.backfill_only else "head_and_archive"
        try:
            with app.app_context():
                while True:
                    state = watch.cycle()
                    db.session.remove()
                    print(json.dumps(state, ensure_ascii=True), flush=True)
                    if args.once or state.get("error_code") == "account_verification_failed":
                        return 0 if state["health"] == "running" else 1
                    time.sleep(state["next_delay_seconds"])
        finally:
            watch.close()
            watch.state["worker_active"] = False
            save_state(watch.path, watch.state)


if __name__ == "__main__":
    raise SystemExit(main())
