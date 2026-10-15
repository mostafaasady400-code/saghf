"""Authenticated Playwright transport for Divar using an existing local session.

The transport never installs a browser and never logs cookie values.  It first
tries an already-running Chrome/Edge CDP endpoint, then a local storage-state
file.  It does not fall back to anonymous HTTP when authentication is absent.
"""

from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class DivarSessionConnectionError(RuntimeError):
    """Raised when no usable authenticated browser session can be attached."""


class AuthenticatedDivarBrowser:
    AUTH_COOKIE_NAMES = {"token", "access_token", "auth", "session", "sessionid", "saccesstoken"}
    DEFAULT_CDP_ENDPOINTS = ("http://127.0.0.1:9223", "http://127.0.0.1:9222")

    def __init__(self, *, project_root: Optional[Path] = None, headless: bool = True):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1])
        self.headless = headless
        self._lock = threading.RLock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._owns_browser = False
        self.connection_mode: Optional[str] = None
        self._verified_at = 0.0

    def connect(self) -> "AuthenticatedDivarBrowser":
        with self._lock:
            if self._page is not None:
                return self
            try:
                from playwright.sync_api import sync_playwright
                self._playwright = sync_playwright().start()
                if self._connect_cdp():
                    self._verify_authenticated_account()
                    return self
                if self._connect_storage_state():
                    self._verify_authenticated_account()
                    return self
            except DivarSessionConnectionError:
                self.close()
                raise
            except Exception as exc:
                self.close()
                raise DivarSessionConnectionError(
                    f"اتصال امن Playwright به نشست دیوار ناموفق بود ({type(exc).__name__})."
                ) from exc
            self.close()
            raise DivarSessionConnectionError(
                "نشست احراز‌شدهٔ دیوار پیدا نشد؛ CDP فعال یا storage_state معتبر لازم است."
            )

    def _verify_authenticated_account(self) -> None:
        """SSR user.isLoggedIn can be false before client-side authentication.

        Validate a native protected account response instead of trusting a
        public client-session cookie or serializing account data.
        """
        verified = []
        def capture(response):
            if urlsplit(response.url).hostname == "api.divar.ir" and urlsplit(response.url).path == "/v8/my-posts/w/list-v2" and response.status == 200:
                try:
                    payload = response.json()
                    if isinstance(payload, dict) and "page" in payload and "tab_bar" in payload:
                        verified.append(True)
                except Exception:
                    pass
        self._page.on("response", capture)
        try:
            self._page.goto("https://divar.ir/my-divar/my-posts", wait_until="domcontentloaded", timeout=15000)
            for _ in range(20):
                self._page.wait_for_timeout(250)
                if verified:
                    self._verified_at = time.monotonic()
                    return
            raise DivarSessionConnectionError("Protected account verification failed; manual login may be required.")
        finally:
            self._page.remove_listener("response", capture)

    def _connect_cdp(self) -> bool:
        configured = os.getenv("DIVAR_CDP_ENDPOINT", "").strip()
        endpoints: Iterable[str] = [configured] if configured else self.DEFAULT_CDP_ENDPOINTS
        for endpoint in endpoints:
            if not endpoint:
                continue
            try:
                browser = self._playwright.chromium.connect_over_cdp(endpoint, timeout=2500)
            except Exception:
                continue
            contexts = list(browser.contexts)
            context = next((ctx for ctx in contexts if self._has_authenticated_cookies(ctx)), None)
            if context is None:
                # Disconnect only; never close the user's remotely controlled browser.
                continue
            self._browser = browser
            self._context = context
            self._page = context.new_page()
            self._owns_browser = False
            self.connection_mode = "cdp"
            return True
        return False

    def _connect_storage_state(self) -> bool:
        state = self._load_storage_state()
        if state is None:
            return False
        executable = self._find_system_browser()
        if executable is None:
            raise DivarSessionConnectionError("Chrome یا Edge نصب‌شده برای Playwright پیدا نشد.")
        browser = self._playwright.chromium.launch(
            executable_path=str(executable),
            headless=self.headless,
        )
        context = browser.new_context(storage_state=state, locale="fa-IR")
        if not self._has_authenticated_cookies(context):
            browser.close()
            raise DivarSessionConnectionError("storage_state محلی فاقد نشست احراز‌شدهٔ دیوار است.")
        self._browser = browser
        self._context = context
        self._page = context.new_page()
        self._owns_browser = True
        self.connection_mode = "storage_state"
        return True

    def _load_storage_state(self) -> Optional[Dict[str, Any]]:
        configured = os.getenv("DIVAR_STORAGE_STATE", "").strip()
        candidates = [Path(configured)] if configured else []
        candidates.extend([
            self.project_root / "divar_storage_state.json",
            self.project_root / "playwright" / ".auth" / "divar.json",
            self.project_root / "divar_cookies.json",
        ])
        for path in candidates:
            try:
                if not path.is_file():
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
                state = self._normalize_storage_state(raw)
                if state and self._state_has_authenticated_cookie(state):
                    return state
            except (OSError, ValueError, TypeError):
                continue
        return None

    @classmethod
    def _normalize_storage_state(cls, raw: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw, dict) and isinstance(raw.get("cookies"), list):
            return {"cookies": raw["cookies"], "origins": raw.get("origins", [])}
        if isinstance(raw, list):
            return {"cookies": raw, "origins": []}
        if isinstance(raw, dict):
            # Legacy local cookie map. Values stay in memory and are never logged/written.
            cookies = [
                {"name": str(name), "value": str(value), "domain": ".divar.ir", "path": "/"}
                for name, value in raw.items()
                if value not in (None, "") and isinstance(value, (str, int, float, bool))
            ]
            return {"cookies": cookies, "origins": []}
        return None

    @classmethod
    def _state_has_authenticated_cookie(cls, state: Dict[str, Any]) -> bool:
        return any(
            str(cookie.get("name", "")).lower() in cls.AUTH_COOKIE_NAMES
            and bool(cookie.get("value"))
            and (str(cookie.get("domain", "")).lstrip(".").lower() == "divar.ir" or str(cookie.get("domain", "")).lower().endswith(".divar.ir"))
            for cookie in state.get("cookies", []) if isinstance(cookie, dict)
        )

    @classmethod
    def _has_authenticated_cookies(cls, context: Any) -> bool:
        try:
            cookies = context.cookies("https://divar.ir")
        except Exception:
            return False
        return cls._state_has_authenticated_cookie({"cookies": cookies})

    @staticmethod
    def _find_system_browser() -> Optional[Path]:
        configured = os.getenv("DIVAR_BROWSER_EXECUTABLE", "").strip()
        candidates = [Path(configured)] if configured else []
        candidates.extend([
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ])
        return next((path for path in candidates if path.is_file()), None)

    def fetch_html(self, url: str, *, timeout_ms: int = 15000) -> tuple[int, str]:
        self.connect()
        with self._lock:
            try:
                if not self._has_authenticated_cookies(self._context):
                    raise DivarSessionConnectionError("Authenticated browser session was removed or expired.")
                if time.monotonic() - self._verified_at > 60:
                    self._verify_authenticated_account()
                if urlsplit(url).path.startswith("/s/"):
                    return self._fetch_search(url, timeout_ms)
                response = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                status = response.status if response is not None else 0
                if status == 200 and urlsplit(url).path.startswith("/v/"):
                    self._page.wait_for_selector("h1", timeout=min(timeout_ms, 8000))
                    self._page.wait_for_selector(".kt-group-row-item__value, .kt-unexpandable-row__value", timeout=min(timeout_ms, 8000))
                return status, self._page.content()
            except Exception as exc:
                raise DivarSessionConnectionError(
                    f"واکشی صفحه با نشست Playwright ناموفق بود ({type(exc).__name__})."
                ) from exc

    def fetch_detail_json(self, token: str, *, timeout_ms: int = 10000) -> Dict[str, Any]:
        if not token or not all(c.isalnum() or c in "_-" for c in token):
            raise ValueError("invalid_post_token")
        self.connect()
        with self._lock:
            if not self._has_authenticated_cookies(self._context):
                raise DivarSessionConnectionError("Authenticated session is unavailable.")
            if time.monotonic() - self._verified_at > 60:
                self._verify_authenticated_account()
            try:
                response = self._context.request.get("https://api.divar.ir/v8/posts-v2/web/" + token, timeout=timeout_ms)
                if response.status in {404, 410}:
                    return {"source_removed": True}
                if response.status != 200:
                    raise DivarSessionConnectionError("Authenticated detail HTTP status " + str(response.status))
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
                    raise DivarSessionConnectionError("Unverifiable native detail response.")
                return payload
            except DivarSessionConnectionError:
                raise
            except Exception as exc:
                raise DivarSessionConnectionError("Native detail failed (" + type(exc).__name__ + ")") from None

    @staticmethod
    def _search_html(data: Dict[str, Any], template: Dict[str, Any]) -> str:
        pagination = data.get("pagination") or {}
        next_data = pagination.get("data") or {}
        more = pagination.get("has_more", pagination.get("hasMore", bool(next_data)))
        cursor = None
        if more and next_data:
            cursor = json.dumps({"pagination_data": next_data, "template": template}, separators=(",", ":"))
        widgets = data.get("list_widgets") or []
        wrapped = [{"data": {"dto": w}} if w.get("widget_type") == "POST_ROW" else w for w in widgets]
        state = {"nb": {"listWidgets": wrapped, "pagination": {"data": {"last_post_date": cursor}}}}
        return '<script>window.__PRELOADED_STATE__=' + json.dumps(state) + ';</script>'

    def _fetch_search(self, url: str, timeout_ms: int) -> tuple[int, str]:
        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        cursor = params.pop("last-post-date", None)
        params.pop("page", None)
        if cursor:
            try:
                continuation = json.loads(cursor)
                template = continuation["template"]
                payload = deepcopy(template)
                payload["pagination_data"] = continuation["pagination_data"]
            except (ValueError, KeyError, TypeError) as exc:
                raise DivarSessionConnectionError("Pagination checkpoint requires a new authenticated search.") from exc
            response = self._context.request.post(
                "https://api.divar.ir/v8/postlist/w/search", data=payload, timeout=timeout_ms,
            )
            if response.status != 200:
                return response.status, ""
            return 200, self._search_html(response.json(), template)

        base_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
        captured = []
        received = []
        def capture(request):
            if urlsplit(request.url).path == "/v8/postlist/w/search" and request.method == "POST":
                captured.append(request.post_data_json)
        self._page.on("request", capture)
        def capture_response(response):
            if urlsplit(response.url).path == "/v8/postlist/w/search" and response.status == 200:
                try:
                    received.append(response.json())
                except Exception:
                    pass
        self._page.on("response", capture_response)
        try:
            response = self._page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
            from crawler.divar_accessible_search import DivarAccessibleSearchCrawler
            state = DivarAccessibleSearchCrawler._extract_preloaded_state(self._page.content()) or {}
            nb = state.get("nb") or {}
            if not nb.get("listWidgets"):
                # Divar sometimes returns an empty SSR shell and hydrates via its
                # native authenticated request. Never interpret that as exhaustion.
                for _ in range(20):
                    self._page.wait_for_timeout(500)
                    if received and captured:
                        return 200, self._search_html(received[0], captured[0])
                raise DivarSessionConnectionError("Search returned no verifiable listing state; coverage remains incomplete.")
            pagination = nb.get("pagination") or {}
            if pagination.get("hasMore", bool(pagination.get("data"))):
                for _ in range(6):
                    self._page.evaluate("""() => {
                        const root = document.scrollingElement;
                        if (root) root.scrollTop = root.scrollHeight;
                        window.scrollTo(0, document.body.scrollHeight);
                        for (const element of document.querySelectorAll('main, div')) {
                            const overflow = getComputedStyle(element).overflowY;
                            if ((overflow === 'auto' || overflow === 'scroll') &&
                                element.scrollHeight > element.clientHeight + 32) {
                                element.scrollTop = element.scrollHeight;
                            }
                        }
                    }""")
                    self._page.wait_for_timeout(500)
                    if captured:
                        break
                if not captured:
                    raise DivarSessionConnectionError("Native pagination request was not available; coverage remains incomplete.")
            template = captured[0] if captured else {}
            data = {"list_widgets": nb["listWidgets"], "pagination": pagination}
            return response.status if response else 0, self._search_html(data, template)
        finally:
            self._page.remove_listener("request", capture)
            self._page.remove_listener("response", capture_response)

    def close(self) -> None:
        with self._lock:
            try:
                if self._page is not None:
                    self._page.close()
            except Exception:
                pass
            try:
                if self._owns_browser and self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            try:
                if self._playwright is not None:
                    self._playwright.stop()
            except Exception:
                pass
            self._page = self._context = self._browser = self._playwright = None
            self._owns_browser = False

    def __enter__(self) -> "AuthenticatedDivarBrowser":
        return self.connect()

    def __exit__(self, *_args: Any) -> None:
        self.close()
