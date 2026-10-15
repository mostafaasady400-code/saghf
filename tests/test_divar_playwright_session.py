from pathlib import Path
import json
import pytest
from urllib.parse import urlsplit, parse_qs

from crawler.divar_playwright_session import AuthenticatedDivarBrowser, DivarSessionConnectionError


@pytest.mark.parametrize("status,payload,valid", [(200, {"page": {}, "tab_bar": {}}, True), (401, {}, False), (200, {"login": True}, False)])
def test_protected_account_verification(status, payload, valid):
    class Response:
        url = "https://api.divar.ir/v8/my-posts/w/list-v2"
        def json(self):
            return payload
    response = Response()
    response.status = status
    class Page:
        callback = None
        def on(self, event, callback):
            self.callback = callback
        def goto(self, *args, **kwargs):
            self.callback(response)
        def wait_for_timeout(self, delay):
            pass
        def remove_listener(self, event, callback):
            self.callback = None
    browser = AuthenticatedDivarBrowser()
    browser._page = Page()
    if valid:
        browser._verify_authenticated_account()
        assert browser._verified_at > 0
    else:
        with pytest.raises(DivarSessionConnectionError):
            browser._verify_authenticated_account()
    assert browser._page.callback is None
from crawler.divar_accessible_search import DivarAccessibleSearchCrawler


def test_native_pagination_preserves_template_and_all_cursor_fields():
    template = {"search_data": {"form_data": {"credit": {"max": 100}}}, "city_ids": [1]}
    pagination = {"last_post_date": "2026-10-01T00:00:00Z", "viewed_tokens": ["ad1"], "page": 2}
    html = AuthenticatedDivarBrowser._search_html({"list_widgets": [{"widget_type": "POST_ROW", "data": {"token": "ad1", "title": "real schema"}}], "pagination": {"has_more": True, "data": pagination}}, template)
    rows, cursor = DivarAccessibleSearchCrawler().parse_page(html)
    assert len(rows) == 1
    assert json.loads(cursor) == {"pagination_data": pagination, "template": template}
    url = DivarAccessibleSearchCrawler._with_cursor("https://divar.ir/s/tehran/rent-apartment?business-type=personal&credit=0-100", cursor, 2)
    query = parse_qs(urlsplit(url).query)
    assert query["credit"] == ["0-100"]
    assert json.loads(query["last-post-date"][0])["template"] == template


def test_legacy_cookie_map_is_kept_in_memory_as_storage_state():
    state = AuthenticatedDivarBrowser._normalize_storage_state({"token": "secret", "city": "tehran"})
    assert state is not None
    assert state["origins"] == []
    assert {cookie["name"] for cookie in state["cookies"]} == {"token", "city"}
    assert AuthenticatedDivarBrowser._state_has_authenticated_cookie(state) is True


def test_anonymous_storage_state_is_rejected():
    state = AuthenticatedDivarBrowser._normalize_storage_state({"city": "tehran", "theme": "light"})
    assert state is not None
    assert AuthenticatedDivarBrowser._state_has_authenticated_cookie(state) is False


def test_public_client_session_cookie_is_not_login():
    state = AuthenticatedDivarBrowser._normalize_storage_state({"csid": "client-session"})
    assert AuthenticatedDivarBrowser._state_has_authenticated_cookie(state) is False


def test_current_access_cookie_recognized_but_refresh_only_rejected():
    state = AuthenticatedDivarBrowser._normalize_storage_state({"sAccessToken": "test-only"})
    assert AuthenticatedDivarBrowser._state_has_authenticated_cookie(state) is True
    state = AuthenticatedDivarBrowser._normalize_storage_state({"sRefreshToken": "test-only", "csid": "public"})
    assert AuthenticatedDivarBrowser._state_has_authenticated_cookie(state) is False


def test_browser_resolution_uses_existing_executable(monkeypatch, tmp_path: Path):
    browser = tmp_path / "msedge.exe"
    browser.write_bytes(b"")
    monkeypatch.setenv("DIVAR_BROWSER_EXECUTABLE", str(browser))
    assert AuthenticatedDivarBrowser._find_system_browser() == browser
