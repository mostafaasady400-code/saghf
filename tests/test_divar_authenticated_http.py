import time
from types import SimpleNamespace
import json
from urllib.parse import urlencode
import pytest
from crawler.divar_authenticated_http import AuthenticatedDivarHTTP
from crawler.divar_playwright_session import DivarSessionConnectionError


@pytest.fixture(autouse=True)
def isolated_runtime_configuration(tmp_path, monkeypatch):
    # Unit tests must never inherit a real user's configured browser/session.
    monkeypatch.setattr("crawler.divar_authenticated_http.DEFAULT_CDP_RUNTIME", tmp_path / "cdp.json")


def test_detail_cache_is_labelled_and_cannot_mutate_original():
    calls = []
    transport = AuthenticatedDivarHTTP()
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: calls.append(1) or SimpleNamespace(status_code=200, json=lambda: {"sections": [{"widgets": []}]}))
    first = transport.fetch_detail_json("cached_token")
    first["sections"].clear()
    second = transport.fetch_detail_json("cached_token")
    assert len(calls) == 1
    assert second["_saghf_cached_detail"] is True
    assert len(second["sections"]) == 1


def test_http_pagination_preserves_complete_filter_template():
    requests = []
    transport = AuthenticatedDivarHTTP()
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(post=lambda url, **kwargs: requests.append(kwargs["json"]) or SimpleNamespace(status_code=200, json=lambda: {"list_widgets": [], "pagination": {}}))
    template = {"city_ids": ["1"], "search_data": {"form_data": {"size": [70, 100], "district": [5], "business-type": "personal"}}, "pagination_data": {"old": 1}}
    cursor = json.dumps({"template": template, "pagination_data": {"next": 2}})
    status, _ = transport.fetch_html("https://divar.ir/s/tehran/rent-apartment?" + urlencode({"last-post-date": cursor}))
    assert status == 200
    assert requests[0]["search_data"] == template["search_data"]
    assert requests[0]["city_ids"] == ["1"]
    assert requests[0]["pagination_data"] == {"next": 2}
    assert template["pagination_data"] == {"old": 1}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_detail_http_failure_is_explicit(status):
    transport = AuthenticatedDivarHTTP()
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=status))
    with pytest.raises(DivarSessionConnectionError, match=str(status)):
        transport.fetch_detail_json("valid_token")


def test_account_failure_closes_session_before_detail():
    calls = []
    transport = AuthenticatedDivarHTTP()
    transport._http = SimpleNamespace(post=lambda *a, **k: SimpleNamespace(status_code=401), close=lambda: calls.append("closed"))
    with pytest.raises(DivarSessionConnectionError, match="account verification"):
        transport.fetch_detail_json("valid_token")
    assert calls == ["closed"]
    assert transport._http is None


def test_removed_detail_and_invalid_token():
    transport = AuthenticatedDivarHTTP()
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=410))
    assert transport.fetch_detail_json("valid_token") == {"source_removed": True}
    with pytest.raises(ValueError):
        transport.fetch_detail_json("../private")


def test_retry_after_is_respected_without_retrying_429():
    calls = []
    transport = AuthenticatedDivarHTTP()
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: calls.append(1) or SimpleNamespace(status_code=429, headers={"Retry-After": "900"}))
    with pytest.raises(DivarSessionConnectionError) as caught:
        transport.fetch_detail_json("limited_token")
    assert caught.value.retry_after_seconds == 900
    assert calls == [1]


def test_http_account_validation_does_not_require_ui_response(monkeypatch):
    transport = AuthenticatedDivarHTTP()
    calls = []
    monkeypatch.setattr(transport, "_authenticated_http", lambda: calls.append("protected_http"))
    transport._verify_authenticated_account()
    assert calls == ["protected_http"]
    assert transport._verified_at > 0


@pytest.mark.parametrize("header", ["NaN", "Infinity", "-5", "not-a-date"])
def test_invalid_retry_after_never_breaks_worker_delay(header):
    with pytest.raises(DivarSessionConnectionError) as caught:
        AuthenticatedDivarHTTP._raise_http_error(SimpleNamespace(status_code=429, headers={"Retry-After": header}), "detail")
    assert caught.value.retry_after_seconds == 300


def test_account_rate_limit_keeps_retry_after_and_never_fetches_detail():
    calls = []
    transport = AuthenticatedDivarHTTP()
    transport._http = SimpleNamespace(post=lambda *a, **k: calls.append("account") or SimpleNamespace(status_code=429, headers={"Retry-After": "900"}), get=lambda *a, **k: pytest.fail("must not fetch detail after account 429"), close=lambda: calls.append("closed"))
    with pytest.raises(DivarSessionConnectionError) as caught:
        transport.fetch_detail_json("valid_token")
    assert caught.value.retry_after_seconds == 900
    assert calls == ["account", "closed"]
    assert transport._http is None


def test_new_http_session_is_verified_even_early_in_monotonic_clock(monkeypatch):
    calls = []
    transport = AuthenticatedDivarHTTP()
    transport._http = SimpleNamespace(post=lambda *a, **k: calls.append("account") or SimpleNamespace(status_code=200, json=lambda: {"page": {}, "tab_bar": []}))
    monkeypatch.setattr("crawler.divar_authenticated_http.time.monotonic", lambda: 1.0)
    transport._authenticated_http()
    assert calls == ["account"]


def test_repeated_search_uses_authenticated_ssr_and_original_template(monkeypatch):
    transport = AuthenticatedDivarHTTP()
    template = {"search_data": {"form_data": {"size": [70, 100], "business-type": "personal"}}, "city_ids": ["1"]}
    key = "https://divar.ir/s/tehran/rent-apartment?business-type=personal&size=70-100"
    transport._search_templates[key] = (time.monotonic(), template)
    state = {"nb": {"listWidgets": [{"widget_type": "POST_ROW", "data": {"token": "example"}}], "pagination": {"hasMore": True, "data": {"next": 2}}}}
    calls = []
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda url, **kwargs: calls.append(url) or SimpleNamespace(status_code=200, text='<script>window.__PRELOADED_STATE__=' + json.dumps(state) + ';</script>'))
    monkeypatch.setattr(transport, "_bootstrap_search", lambda *a: pytest.fail("complete SSR must not start a browser"))
    status, html = transport.fetch_html(key)
    assert status == 200 and calls == [key]
    result = transport._search_state(html)
    cursor = json.loads(result["nb"]["pagination"]["data"]["last_post_date"])
    assert cursor["template"] == template
    assert cursor["pagination_data"] == {"next": 2}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_ssr_http_failure_never_falls_back_to_browser(monkeypatch, status):
    transport = AuthenticatedDivarHTTP()
    key = "https://divar.ir/s/tehran/rent-apartment?business-type=personal"
    transport._search_templates[key] = (time.monotonic(), {"search_data": {}})
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=status))
    monkeypatch.setattr(transport, "_bootstrap_search", lambda *a: pytest.fail("must not bypass source failure"))
    with pytest.raises(DivarSessionConnectionError, match=str(status)):
        transport.fetch_html(key)


def test_ssr_has_more_without_cursor_is_not_exhaustion(monkeypatch):
    transport = AuthenticatedDivarHTTP()
    key = "https://divar.ir/s/tehran/rent-apartment?business-type=personal"
    transport._search_templates[key] = (time.monotonic(), {"search_data": {"form_data": {}}})
    state = {"nb": {"listWidgets": [{"widget_type": "POST_ROW", "data": {"token": "example"}}], "pagination": {"hasMore": True, "data": {}}}}
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text="window.__PRELOADED_STATE__=" + json.dumps(state)))
    with pytest.raises(DivarSessionConnectionError, match="Unverifiable SSR pagination"):
        transport.fetch_html(key)


def test_complete_ssr_bootstrap_preserves_server_form_without_browser(monkeypatch):
    transport = AuthenticatedDivarHTTP()
    form = {"category": {"str": {"value": "apartment-rent"}}, "business-type": {"repeated_string": {"value": ["personal"]}}, "size": {"number_range": {"minimum": "70", "maximum": "100"}}}
    server_payload = {"additional_form_data": {"data": {"sort": {"str": {"value": "sort_date"}}}}}
    state = {"search": {"searchData": {"formData": form, "serverPayload": server_payload}}, "nb": {"listWidgets": [{"widget_type": "POST_ROW", "data": {"token": "example"}}], "pagination": {"hasMore": True, "data": {"next": 2}}}}
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text="window.__PRELOADED_STATE__=" + json.dumps(state)))
    monkeypatch.setattr(transport, "connect", lambda: pytest.fail("complete SSR must not connect browser"))
    key = "https://divar.ir/s/tehran/rent-apartment?business-type=personal&size=70-100"
    status, html = transport.fetch_html(key)
    result = transport._search_state(html)
    cursor = json.loads(result["nb"]["pagination"]["data"]["last_post_date"])
    assert status == 200
    assert cursor["template"]["search_data"]["form_data"]["data"] == form
    assert cursor["template"]["search_data"]["server_payload"] == server_payload
    assert cursor["template"]["city_ids"] == ["1"]


@pytest.mark.parametrize("actual,valid", [(["82", "177"], True), (["177", "82"], True), (["82"], False), (["82", "999"], False), (["82", "82", "177"], False), (None, False)])
def test_ssr_verifies_all_district_values_before_reusing_template(monkeypatch, actual, valid):
    transport = AuthenticatedDivarHTTP()
    form = {"category": {"str": {"value": "apartment-rent"}}, "business-type": {"repeated_string": {"value": ["personal"]}}, "districts": {"repeated_string": {"value": actual}}}
    state = {"search": {"searchData": {"formData": form}}, "nb": {"listWidgets": [{"data": {"token": "example"}}], "pagination": {"hasMore": True, "data": {"next": 2}}}}
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text="window.__PRELOADED_STATE__=" + json.dumps(state)))
    calls = []
    monkeypatch.setattr("crawler.divar_playwright_session.AuthenticatedDivarBrowser.fetch_html", lambda self, url, **kwargs: calls.append(url) or (200, "native capture"))
    url = "https://divar.ir/s/tehran/rent-apartment?business-type=personal&districts=82,177"
    status, html = transport.fetch_html(url)
    assert status == 200
    if valid:
        assert not calls
        cursor = json.loads(transport._search_state(html)["nb"]["pagination"]["data"]["last_post_date"])
        assert cursor["template"]["search_data"]["form_data"]["data"] == form
    else:
        assert html == "native capture" and calls == [url]
        assert not transport._search_templates
@pytest.mark.parametrize("field,value", [("business-type", {"repeated_string": {"value": ["agency"]}}), ("size", {"number_range": {"minimum": "1", "maximum": "999"}})])
def test_ssr_dropped_filter_values_require_native_capture(monkeypatch, field, value):
    transport = AuthenticatedDivarHTTP()
    form = {"category": {"str": {"value": "apartment-rent"}}, "business-type": {"repeated_string": {"value": ["personal"]}}, "size": {"number_range": {"minimum": "70", "maximum": "100"}}}
    form[field] = value
    state = {"search": {"searchData": {"formData": form}}, "nb": {"listWidgets": [{"data": {"token": "example"}}], "pagination": {"hasMore": True, "data": {"next": 2}}}}
    transport._http_verified_at = time.monotonic()
    transport._http = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200, text="window.__PRELOADED_STATE__=" + json.dumps(state)))
    calls = []
    monkeypatch.setattr("crawler.divar_playwright_session.AuthenticatedDivarBrowser.fetch_html", lambda self, url, **kwargs: calls.append(url) or (200, "native capture"))
    url = "https://divar.ir/s/tehran/rent-apartment?business-type=personal&size=70-100"
    assert transport.fetch_html(url) == (200, "native capture")
    assert calls == [url]
    assert not transport._search_templates
@pytest.mark.parametrize("url", ["https://example.com:9222", "http://user:pass@127.0.0.1:9222", "http://127.0.0.1:9222/path", "http://127.0.0.1:9222/?secret=test"])
def test_explicit_cdp_is_local_and_has_no_embedded_credentials(url):
    with pytest.raises(ValueError, match="cdp_endpoint_must_be_local"):
        AuthenticatedDivarHTTP(cdp_url=url)


def test_explicit_cdp_cannot_fall_back_to_saved_session(monkeypatch):
    transport = AuthenticatedDivarHTTP(cdp_url="http://127.0.0.1:9222")
    transport._context = SimpleNamespace(cookies=lambda *a: [])
    monkeypatch.setattr(transport, "_load_storage_state", lambda: pytest.fail("selected Chrome must not use old saved state"))
    with pytest.raises(DivarSessionConnectionError, match="manual login required"):
        transport._authenticated_http()


def test_explicit_cdp_close_preserves_user_browser_and_tabs(monkeypatch):
    transport = AuthenticatedDivarHTTP(cdp_url="http://127.0.0.1:9222")
    calls = []
    transport._cdp_runtime = SimpleNamespace(stop=lambda: calls.append("detach"))
    transport._cdp_owned_page = SimpleNamespace(close=lambda: calls.append("own_page"))
    transport._page = transport._cdp_owned_page
    transport._context = SimpleNamespace(close=lambda: pytest.fail("user context must stay open"))
    transport._cdp_browser = SimpleNamespace(close=lambda: pytest.fail("user browser must stay open"))
    transport.close()
    assert calls == ["own_page", "detach"]
def test_default_transport_uses_local_cdp_configuration(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"cdp_url": "http://127.0.0.1:9222"}), encoding="utf-8")
    monkeypatch.setattr("crawler.divar_authenticated_http.DEFAULT_CDP_RUNTIME", path)
    transport = AuthenticatedDivarHTTP()
    assert transport._explicit_cdp_url == "http://127.0.0.1:9222"


def test_malformed_runtime_does_not_fall_back_to_old_state(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_text('{}', encoding="utf-8")
    monkeypatch.setattr("crawler.divar_authenticated_http.DEFAULT_CDP_RUNTIME", path)
    with pytest.raises(ValueError, match="invalid_local_cdp_configuration"):
        AuthenticatedDivarHTTP()
