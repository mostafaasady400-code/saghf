import json
import time

import pytest

from crawler.authenticated_watch import AuthenticatedWatch, WorkerLock, save_state


def test_rate_limit_cooldown_survives_restart_without_source_call(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    save_state(path, {"backfill": {}, "head": {}, "health": "degraded", "error_code": "source_rate_limited", "retry_not_before": time.time() + 300, "consecutive_failures": 3})
    watch = AuthenticatedWatch(path)
    monkeypatch.setattr(watch, "_execute", lambda *args: pytest.fail("source must not be called during cooldown"))
    state = watch.cycle()
    assert watch.failures == 3
    assert state["error_code"] == "source_rate_limited"
    assert 298 <= state["next_delay_seconds"] <= 300


def test_single_worker_lock(tmp_path):
    with WorkerLock(tmp_path / "worker.lock"):
        with pytest.raises(RuntimeError, match="already_running"):
            with WorkerLock(tmp_path / "worker.lock"):
                pass
    with WorkerLock(tmp_path / "worker.lock"):
        pass


def test_state_restart_and_atomic_replace(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"backfill": {"rent": {"run_id": "persisted"}}, "head": {}})
    assert AuthenticatedWatch(path).state["backfill"]["rent"]["run_id"] == "persisted"
    assert not path.with_suffix(".tmp").exists()


def test_atomic_state_retries_transient_windows_lock(tmp_path, monkeypatch):
    import crawler.authenticated_watch as module
    replace = module.os.replace
    attempts = []
    def intermittent(*args):
        attempts.append(True)
        if len(attempts) < 3:
            raise PermissionError("temporary file lock")
        return replace(*args)
    monkeypatch.setattr(module.os, "replace", intermittent)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    save_state(tmp_path / "state.json", {"health": "running"})
    assert len(attempts) == 3


def test_failure_is_visible_and_backoff_is_bounded(tmp_path, monkeypatch):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    def fail(*args):
        raise RuntimeError("private connection information")
    monkeypatch.setattr(watch, "_execute", fail)
    for _ in range(10):
        state = watch.cycle()
    assert state["health"] == "degraded"
    assert state["next_delay_seconds"] == 300
    assert "last_success_at" not in state
    assert "private" not in watch.path.read_text()


def test_cycle_runs_separate_head_and_backfill(tmp_path, monkeypatch):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    calls = []
    monkeypatch.setattr(watch, "_execute", lambda *args: calls.append(args))
    assert watch.cycle()["health"] == "running"
    assert [(c[0], c[1]) for c in calls] == [("rent", "head"), ("sale", "head"), ("rent", "head_backlog"), ("sale", "head_backlog"), ("rent", "backfill"), ("sale", "backfill")]
    assert sum(c[2] for c in calls) == 2 * (watch.head_seconds + watch.chunk_seconds)


def test_pending_head_survives_restart_and_is_not_duplicated(tmp_path):
    from types import SimpleNamespace
    path = tmp_path / "state.json"
    watch = AuthenticatedWatch(path)
    run = SimpleNamespace(run_id="owned-head", can_resume=True)
    watch._remember_head("rent", run)
    watch._remember_head("rent", run)
    watch._remember_head("sale", SimpleNamespace(run_id="done", can_resume=False))
    save_state(path, watch.state)
    resumed = AuthenticatedWatch(path)
    assert resumed.state["pending_heads"] == {"rent": ["owned-head"]}


def test_backlog_prunes_only_finished_missing_or_expired_snapshots(tmp_path):
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    watch = AuthenticatedWatch(tmp_path / "state.json")
    now = datetime.utcnow()
    def run(name, hours=1, resumable=True):
        return SimpleNamespace(run_id=name, reference_time=now - timedelta(hours=hours), can_resume=resumable)
    rows = {"done": run("done", resumable=False), "expired": run("expired", hours=25), "pending": run("pending")}
    watch.state["pending_heads"]["rent"] = ["missing", "done", "expired", "pending"]
    assert watch._next_pending_head("rent", rows.get, now) is rows["pending"]
    assert watch.state["pending_heads"]["rent"] == ["pending"]
    assert set(rows) == {"done", "expired", "pending"}


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_watch_rejects_invalid_time_limits(tmp_path, value):
    with pytest.raises(ValueError, match="finite_positive"):
        AuthenticatedWatch(tmp_path / "state.json", chunk_seconds=value)


def test_watch_reuses_one_crawler_and_closes_on_failure(tmp_path, monkeypatch):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    class Crawler:
        closed = False
        def close(self):
            self.closed = True
    crawler = Crawler()
    watch._crawler = crawler
    assert watch._get_crawler() is crawler
    def fail(*args):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(watch, "_execute", fail)
    assert watch.cycle()["health"] == "degraded"
    assert crawler.closed is True
    assert watch._crawler is None


def test_old_rate_limit_is_not_reused_for_unrelated_worker_failure(tmp_path, monkeypatch):
    watch = AuthenticatedWatch(tmp_path / "state.json")
    watch.state.update(error_code="source_rate_limited", retry_not_before=time.time() - 1)
    def fail(*args):
        raise RuntimeError("unrelated error")
    monkeypatch.setattr(watch, "_execute", fail)
    state = watch.cycle()
    assert state["error_code"] == "worker_error"
    assert "retry_not_before" not in state
    assert state["next_delay_seconds"] == 60
def test_authenticated_session_failure_is_explicit_and_keeps_pending_work(tmp_path, monkeypatch):
    from crawler.divar_playwright_session import DivarSessionConnectionError
    watch = AuthenticatedWatch(tmp_path / "state.json")
    watch.state["pending_heads"]["rent"] = ["unfinished"]
    def fail(*args):
        raise DivarSessionConnectionError("Authenticated session unavailable; no anonymous fallback.")
    monkeypatch.setattr(watch, "_execute", fail)
    state = watch.cycle()
    assert state["health"] == "degraded"
    assert state["error_code"] == "account_verification_failed"
    assert state["pending_heads"]["rent"] == ["unfinished"]
