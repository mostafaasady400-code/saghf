"""Single-process, restart-safe authenticated discovery and seven-day backfill.

Coverage is authoritative only in SearchRun, never inferred from worker liveness.
No credentials or pagination payloads are written to the health file.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from crawler.owner_search_policy import DEFAULT_POLICY, load_policy, policy_fingerprint, search_criteria


class WorkerLock:
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError("authenticated_watch_already_running") from None
        return self

    def __exit__(self, *args):
        self.handle.close()


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            # Windows indexers/antivirus can briefly hold the destination.
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


class AuthenticatedWatch:
    def __init__(self, state_path, *, chunk_seconds=30, head_seconds=15, interval=120, policy_path=DEFAULT_POLICY, cdp_url=None):
        self.path = Path(state_path)
        self.chunk_seconds = chunk_seconds
        self.head_seconds = head_seconds
        self.interval = interval
        self.policy = load_policy(policy_path)
        self.cdp_url = cdp_url
        if any(not math.isfinite(value) or value <= 0 for value in (chunk_seconds, head_seconds, interval)):
            raise ValueError("watch_time_limits_must_be_finite_positive")
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"backfill": {}, "head": {}}
        for bucket in ("backfill", "head", "head_backlog", "pending_heads"):
            self.state.setdefault(bucket, {})
        self.failures = int(self.state.get("consecutive_failures", 0))
        self.state["policy_version"] = self.policy["version"]
        self.state["policy_fingerprint"] = policy_fingerprint(self.policy)
        self._crawler = None

    def _get_crawler(self):
        if self._crawler is None:
            from crawler.divar_accessible_search import DivarAccessibleSearchCrawler
            from services.publisher_semantic_service import get_configured_publisher_classifier
            from crawler.divar_authenticated_http import AuthenticatedDivarHTTP
            self._crawler = DivarAccessibleSearchCrawler(semantic_classifier=get_configured_publisher_classifier(), browser_session=AuthenticatedDivarHTTP(cdp_url=self.cdp_url))
        return self._crawler

    def close(self):
        if self._crawler is not None:
            self._crawler.close()
            self._crawler = None

    def _remember_head(self, deal, run):
        if run is not None and run.can_resume:
            queue = self.state["pending_heads"].setdefault(deal, [])
            if run.run_id not in queue:
                queue.append(run.run_id)

    def _matches_policy(self, run, deal, kind):
        actual = run.criteria
        return isinstance(actual, dict) and all(actual.get(key) == value for key, value in search_criteria(self.policy, deal, kind).items())

    def _next_pending_head(self, deal, lookup, now):
        queue = self.state["pending_heads"].setdefault(deal, [])
        while queue:
            run = lookup(queue[0])
            if run is not None and run.can_resume and (now - run.reference_time).total_seconds() < 86400:
                return run
            # No rows are deleted. Expired snapshot work remains auditable in
            # SearchRun; the separate seven-day backfill covers older data.
            queue.pop(0)
        return None

    def _execute(self, deal, kind, seconds):
        from database.db import db
        from database.models import SearchRun
        from services.search_run_service import SearchRunService
        bucket = self.state[kind]
        saved = bucket.get(deal, {})
        run = SearchRun.query.filter_by(run_id=saved.get("run_id")).first() if saved.get("run_id") else None
        if run is not None and not self._matches_policy(run, deal, kind):
            run = None  # Preserve the old database run, never reuse different filters.
        if kind == "head_backlog":
            def lookup(run_id):
                candidate = SearchRun.query.filter_by(run_id=run_id).first()
                return candidate if candidate is not None and self._matches_policy(candidate, deal, kind) else None
            run = self._next_pending_head(deal, lookup, datetime.utcnow())
            if run is None:
                bucket[deal] = {"coverage": "not_applicable", "pending_runs": 0}
                save_state(self.path, self.state)
                return
        if kind == "head":
            self._remember_head(deal, run)
        if kind == "head" or run is None:
            run = SearchRunService.create_run(search_criteria(self.policy, deal, kind), query_text="authenticated_watch:" + kind)
            bucket[deal] = {"run_id": run.run_id, "coverage": "unknown"}
            save_state(self.path, self.state)
        elif not run.can_resume:
            # Repeat completed snapshots daily; publication age, not last_seen,
            # controls the rolling seven-day archive returned by the assistant.
            if (datetime.utcnow() - run.reference_time).total_seconds() < 86400:
                return
            run = SearchRunService.create_run(search_criteria(self.policy, deal, kind), query_text="authenticated_watch:backfill")
            bucket[deal] = {"run_id": run.run_id, "coverage": "unknown"}
            save_state(self.path, self.state)
        # Only worker-owned IDs are recovered, while the process lock is held.
        if run.status == "running":
            run.status = "interrupted"
            db.session.commit()
        run = SearchRunService.execute(run.run_id, crawler=self._get_crawler(), max_runtime_seconds=seconds)
        bucket[deal] = {"run_id": run.run_id, "coverage": run.coverage_status, "source_status": run.source_status, "can_resume": run.can_resume, "pages": (run.report or {}).get("pages_traversed", 0), "owners": (run.report or {}).get("main_results", 0)}
        if kind == "head_backlog":
            queue = self.state["pending_heads"].get(deal, [])
            if not run.can_resume and run.run_id in queue:
                queue.remove(run.run_id)
            bucket[deal]["pending_runs"] = len(queue)
        save_state(self.path, self.state)
        if run.source_status not in {"completed", "time_budget_reached"}:
            if run.source_status == "authenticated_session_unavailable":
                from crawler.divar_playwright_session import DivarSessionConnectionError
                raise DivarSessionConnectionError("Authenticated session unavailable; no anonymous fallback.")
            if (run.report or {}).get("stop_reason") == "source_rate_limited":
                from crawler.divar_playwright_session import DivarSessionConnectionError
                error = DivarSessionConnectionError("Authenticated search HTTP status 429")
                error.retry_after_seconds = (run.report or {}).get("retry_after") or 300
                raise error
            raise RuntimeError("source_unavailable_or_incomplete")

    def cycle(self):
        if time.time() < float(self.state.get("retry_not_before", 0)):
            self.state["next_delay_seconds"] = max(1, int(self.state["retry_not_before"] - time.time()))
            return self.state
        self.state["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        self.state.pop("retry_not_before", None)
        self.state["health"] = "working"
        save_state(self.path, self.state)
        try:
            # Discover both contracts before spending time on older details.
            for deal in ("rent", "sale"):
                self._execute(deal, "head", self.head_seconds)
            for deal in ("rent", "sale"):
                self._execute(deal, "head_backlog", self.chunk_seconds / 2)
            for deal in ("rent", "sale"):
                self._execute(deal, "backfill", self.chunk_seconds / 2)
            self.failures = 0
            self.state.pop("retry_not_before", None)
            self.state["health"] = "running"
            self.state["last_success_at"] = datetime.now(timezone.utc).isoformat()
            self.state.pop("error", None)
            self.state.pop("error_code", None)
        except Exception as exc:
            self.close()
            self.failures += 1
            self.state["health"] = "degraded"
            self.state["error"] = type(exc).__name__
            self.state["error_code"] = "worker_error"
            from crawler.divar_playwright_session import DivarSessionConnectionError
            if isinstance(exc, DivarSessionConnectionError):
                message = str(exc)
                self.state["error_code"] = (
                    "source_rate_limited" if "status 429" in message
                    else "account_verification_failed" if "account verification" in message.lower() or "authenticated session unavailable" in message.lower()
                    else "native_detail_failed" if "detail" in message.lower()
                    else "authenticated_transport_failed"
                )
            self.state["last_failure_at"] = datetime.now(timezone.utc).isoformat()
            if self.state.get("error_code") == "source_rate_limited":
                self.state["retry_not_before"] = time.time() + max(300, float(getattr(exc, "retry_after_seconds", 300)))
        self.state["consecutive_failures"] = self.failures
        self.state["next_delay_seconds"] = min(300, 30 * 2 ** min(self.failures, 4)) if self.failures else self.interval
        if self.state.get("error_code") == "source_rate_limited":
            self.state["next_delay_seconds"] = max(300, int(self.state.get("retry_not_before", time.time() + 300) - time.time()))
        save_state(self.path, self.state)
        return self.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--chunk-seconds", type=float, default=30)
    parser.add_argument("--head-seconds", type=float, default=15)
    parser.add_argument("--interval", type=float, default=120)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--cdp-url", default=None, help="Explicit existing local Chrome/Edge CDP endpoint; no saved-session fallback")
    args = parser.parse_args()
    if any(not math.isfinite(value) or value <= 0 for value in (args.chunk_seconds, args.head_seconds, args.interval)):
        parser.error("Time limits must be finite and positive")
    root = Path(__file__).resolve().parents[1]
    os.environ["SAGHF_LEGACY_DIVAR_MONITOR"] = "0"
    with WorkerLock(root / "instance" / "authenticated-watch.lock"):
        from crawler.strict_owner_guard import install_strict_owner_guard, VERSION
        install_strict_owner_guard()
        from app import app
        watch = AuthenticatedWatch(root / "instance" / "authenticated-watch.json", chunk_seconds=args.chunk_seconds, head_seconds=args.head_seconds, interval=args.interval, policy_path=args.policy, cdp_url=args.cdp_url)
        watch.state["owner_guard_version"] = VERSION
        try:
            with app.app_context():
                from database.db import db
                while True:
                    state = watch.cycle()
                    db.session.remove()
                    print(json.dumps(state, ensure_ascii=True), flush=True)
                    if args.once:
                        return 0 if state["health"] == "running" else 1
                    time.sleep(state["next_delay_seconds"])
        finally:
            watch.close()


if __name__ == "__main__":
    raise SystemExit(main())
