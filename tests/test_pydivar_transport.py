from concurrent.futures import ThreadPoolExecutor
import threading

from crawler.pydivar_pipeline import DivarClient


def test_worker_threads_do_not_share_mutable_http_sessions():
    client = DivarClient()
    barrier = threading.Barrier(2)

    def worker():
        session = client._session()
        barrier.wait(timeout=5)
        assert client._session() is session
        return session

    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(lambda _: worker(), range(2)))
    assert sessions[0] is not sessions[1]


def test_get_and_post_reach_transport(monkeypatch):
    client = DivarClient()
    response = object()
    session = client._session()
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr(session, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(session, "post", lambda *args, **kwargs: response)
    assert client.get("https://divar.ir") is response
    assert client.post("https://divar.ir", {}) is response
