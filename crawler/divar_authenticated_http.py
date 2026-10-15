"""Authenticated requests detail transport; no anonymous fallback or secrets logging."""
import time
import json
import math
from copy import deepcopy
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright
from crawler.divar_playwright_session import AuthenticatedDivarBrowser, DivarSessionConnectionError
from crawler.strict_owner_guard import install_strict_owner_guard

# Independent integration boundary: no shared source edits; all subsequent
# crawler/assistant OwnerFilter calls receive the same mandatory pre-guard.
install_strict_owner_guard()

DEFAULT_CDP_RUNTIME = Path(__file__).resolve().parents[1] / "instance" / "divar-cdp-runtime.json"


class AuthenticatedDivarHTTP(AuthenticatedDivarBrowser):
    """Use authenticated SSR/native HTTP; retain browser capture for unknown schemas."""

    def __init__(self, *, cdp_url=None, **kwargs):
        super().__init__(**kwargs)
        if cdp_url is None and DEFAULT_CDP_RUNTIME.exists():
            try:
                runtime = json.loads(DEFAULT_CDP_RUNTIME.read_text(encoding="utf-8"))
                cdp_url = runtime["cdp_url"]
                if not isinstance(cdp_url, str) or not cdp_url:
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise ValueError("invalid_local_cdp_configuration") from None
        if cdp_url is not None:
            endpoint = urlsplit(cdp_url)
            if endpoint.scheme not in {"http", "https"} or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in {"", "/"} or not endpoint.port:
                raise ValueError("cdp_endpoint_must_be_local")
        self._explicit_cdp_url = cdp_url
        self._cdp_runtime = None
        self._cdp_browser = None
        self._cdp_owned_page = None
        self._http = None
        self._http_verified_at = 0.0
        self._last_detail_at = 0.0
        self._detail_cache = {}
        self._search_templates = {}

    def connect(self):
        if not self._explicit_cdp_url:
            return super().connect()
        if self._context is not None:
            return
        try:
            self._cdp_runtime = sync_playwright().start()
            self._cdp_browser = self._cdp_runtime.chromium.connect_over_cdp(self._explicit_cdp_url, timeout=10000)
            if not self._cdp_browser.contexts:
                raise DivarSessionConnectionError("Authenticated Chrome context unavailable.")
            self._context = self._cdp_browser.contexts[0]
            if not self._state_has_authenticated_cookie({"cookies": self._context.cookies("https://divar.ir")}):
                raise DivarSessionConnectionError("Authenticated session unavailable in selected Chrome; manual login required.")
            self._authenticated_http()
            self._cdp_owned_page = self._context.new_page()
            self._page = self._cdp_owned_page
            self._verified_at = time.monotonic()
        except DivarSessionConnectionError:
            self.close()
            raise
        except Exception:
            self.close()
            raise DivarSessionConnectionError("Explicit Chrome CDP connection failed.") from None

    @staticmethod
    def _search_state(html):
        if not isinstance(html, str):
            return None
        marker = "window.__PRELOADED_STATE__"
        start = html.find(marker)
        if start < 0:
            return None
        equals = html.find("=", start + len(marker))
        if equals < 0:
            return None
        try:
            state, _ = json.JSONDecoder().raw_decode(html[equals + 1:].lstrip())
            return state if isinstance(state, dict) else None
        except (ValueError, TypeError):
            return None

    def _bootstrap_search(self, url, key, kwargs):
        session = self._authenticated_http()
        try:
            response = session.get(key, timeout=(4, 10), allow_redirects=False)
            if response.status_code != 200:
                self._raise_http_error(response, "search")
            state = self._search_state(response.text) or {}
            nb = state.get("nb") or {}
            search = (state.get("search") or {}).get("searchData") or {}
            form = search.get("formData")
            parts = urlsplit(key)
            path = parts.path.strip("/").split("/")
            from crawler.pydivar_pipeline import REAL_ESTATE_CATEGORIES
            category = next((name for name, meta in REAL_ESTATE_CATEGORIES.items() if len(path) >= 3 and meta["slug"] == path[2]), None)
            requested = {name for name, _ in parse_qsl(parts.query, keep_blank_values=True)}
            verified_filters = True
            for name, value in parse_qsl(parts.query, keep_blank_values=True):
                field = (form or {}).get(name) if isinstance(form, dict) else None
                if not isinstance(field, dict):
                    verified_filters = False
                    break
                if name == "business-type":
                    verified_filters = (field.get("repeated_string") or {}).get("value") == value.split(",")
                elif name == "districts":
                    actual = (field.get("repeated_string") or {}).get("value")
                    expected = value.split(",")
                    verified_filters = isinstance(actual, list) and len(actual) == len(expected) and {str(item) for item in actual} == set(expected)
                elif name == "size":
                    bounds = value.split("-")
                    number_range = field.get("number_range") or {}
                    verified_filters = len(bounds) == 2 and all(str(number_range.get(bound, "")) == expected for bound, expected in zip(("minimum", "maximum"), bounds))
                else:
                    # Unknown filter encodings require browser-native capture;
                    # matching field names alone does not verify their values.
                    verified_filters = False
                if not verified_filters:
                    break
            more = (nb.get("pagination") or {}).get("hasMore")
            complete = (
                len(path) >= 3 and path[:2] == ["s", "tehran"]
                and isinstance(form, dict) and requested.issubset(form) and verified_filters
                and (form.get("category") or {}).get("str", {}).get("value") == category
                and bool(category)
                and (len(path) == 3 or bool(form.get("districts") or form.get("district")))
                and isinstance(nb.get("listWidgets"), list) and bool(nb["listWidgets"])
                and isinstance(more, bool)
                and (not more or (isinstance((nb.get("pagination") or {}).get("data"), dict) and bool(nb["pagination"]["data"])))
            )
            if complete:
                template = {"city_ids": ["1"], "search_data": {"form_data": {"data": deepcopy(form)}}}
                if isinstance(search.get("serverPayload"), dict):
                    template["search_data"]["server_payload"] = deepcopy(search["serverPayload"])
                if len(self._search_templates) >= 64:
                    self._search_templates.pop(next(iter(self._search_templates)))
                self._search_templates[key] = (time.monotonic(), template)
                return 200, self._search_html({"list_widgets": nb["listWidgets"], "pagination": nb["pagination"]}, template)
        except DivarSessionConnectionError:
            raise
        except Exception:
            raise DivarSessionConnectionError("Authenticated SSR bootstrap failed.") from None
        # Unknown or incomplete SSR schemas still require native browser
        # capture. Never fabricate a filter template or drop a URL constraint.
        status, html = super().fetch_html(url, **kwargs)
        state = self._search_state(html) or {}
        nb = state.get("nb") or {}
        try:
            cursor = nb["pagination"]["data"]["last_post_date"]
            template = json.loads(cursor)["template"] if cursor else None
            if isinstance(template, dict) and isinstance(template.get("search_data"), dict):
                if len(self._search_templates) >= 64:
                    self._search_templates.pop(next(iter(self._search_templates)))
                self._search_templates[key] = (time.monotonic(), deepcopy(template))
        except (ValueError, TypeError, KeyError):
            pass  # No template means next search must bootstrap, not guess.
        return status, html

    @staticmethod
    def _raise_http_error(response, source):
        error = DivarSessionConnectionError("Authenticated " + source + " HTTP status " + str(response.status_code))
        if response.status_code == 429:
            raw = str((getattr(response, "headers", None) or {}).get("Retry-After", ""))
            try:
                delay = float(raw)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(raw).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    delay = 300
            error.retry_after_seconds = max(300, delay) if math.isfinite(delay) else 300
        raise error

    def fetch_html(self, url, **kwargs):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != "divar.ir" or not parts.path.startswith("/s/"):
            raise ValueError("unsupported_search_url")
        cursor = dict(parse_qsl(parts.query)).get("last-post-date")
        if not cursor:
            params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
            key = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(params)), ""))
            with self._lock:
                cached = self._search_templates.get(key)
                if not cached or time.monotonic() - cached[0] >= 900:
                    return self._bootstrap_search(url, key, kwargs)
                session = self._authenticated_http()
                try:
                    response = session.get(key, timeout=(4, 10), allow_redirects=False)
                    if response.status_code != 200:
                        self._raise_http_error(response, "search")
                    state = self._search_state(response.text) or {}
                    nb = state.get("nb") or {}
                    widgets = nb.get("listWidgets")
                    pagination = nb.get("pagination")
                    if isinstance(widgets, list) and widgets and isinstance(pagination, dict):
                        more = pagination.get("hasMore", pagination.get("has_more"))
                        if isinstance(more, bool):
                            if more and (not isinstance(pagination.get("data"), dict) or not pagination["data"]):
                                raise DivarSessionConnectionError("Unverifiable SSR pagination response.")
                            return 200, self._search_html({"list_widgets": widgets, "pagination": pagination}, cached[1])
                except DivarSessionConnectionError:
                    raise
                except Exception:
                    raise DivarSessionConnectionError("Authenticated SSR connection failed.") from None
                # A 200 hydration shell is not an empty successful search.
                return self._bootstrap_search(url, key, kwargs)
        with self._lock:
            session = self._authenticated_http()
            try:
                continuation = json.loads(cursor)
                template = continuation["template"]
                if not isinstance(template, dict) or not template.get("search_data"):
                    raise ValueError()
                body = deepcopy(template)
                body["pagination_data"] = continuation["pagination_data"]
            except (ValueError, KeyError, TypeError):
                raise DivarSessionConnectionError("Pagination checkpoint requires authenticated bootstrap.") from None
            try:
                response = session.post("https://api.divar.ir/v8/postlist/w/search", json=body, timeout=(4, 10), allow_redirects=False)
                if response.status_code != 200:
                    self._raise_http_error(response, "search")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("list_widgets"), list):
                    raise DivarSessionConnectionError("Unverifiable search pagination response.")
                return 200, self._search_html(payload, template)
            except DivarSessionConnectionError:
                raise
            except Exception:
                raise DivarSessionConnectionError("Authenticated search connection failed.") from None

    def _authenticated_http(self):
        if self._http is None:
            if self._explicit_cdp_url and self._context is None:
                self.connect()
                return self._http
            state = {"cookies": self._context.cookies("https://divar.ir")} if self._context is not None else self._load_storage_state()
            if not state or not self._state_has_authenticated_cookie(state):
                if self._explicit_cdp_url:
                    raise DivarSessionConnectionError("Authenticated session unavailable in selected Chrome; manual login required.")
                self.connect()
                state = {"cookies": self._context.cookies("https://divar.ir")}
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://divar.ir/", "Accept-Language": "fa"})
            for cookie in state["cookies"]:
                domain = str(cookie.get("domain", "")).lower().lstrip(".")
                if domain == "divar.ir" or domain.endswith(".divar.ir"):
                    session.cookies.set(cookie["name"], cookie["value"], domain=cookie["domain"], path=cookie.get("path", "/"), secure=bool(cookie.get("secure", True)), expires=int(cookie["expires"]) if cookie.get("expires", -1) > 0 else None)
            self._http = session
        if not self._http_verified_at or time.monotonic() - self._http_verified_at > 60:
            try:
                response = self._http.post("https://api.divar.ir/v8/my-posts/w/list-v2", json={}, timeout=(4, 10), allow_redirects=False)
                if response.status_code in {401, 403}:
                    try:
                        ref_res = self._http.post("https://api.divar.ir/v8/authenticate/session/refresh", json={}, timeout=(4, 10), allow_redirects=False)
                        if ref_res.status_code == 200:
                            self._persist_session_cookies(self._http)
                            response = self._http.post("https://api.divar.ir/v8/my-posts/w/list-v2", json={}, timeout=(4, 10), allow_redirects=False)
                    except Exception:
                        pass
                if response.status_code != 200:
                    self._raise_http_error(response, "account verification")
                payload = response.json()
                if not isinstance(payload, dict) or not {"page", "tab_bar"}.issubset(payload):
                    raise DivarSessionConnectionError("Protected account verification failed.")
                self._http_verified_at = time.monotonic()
                self._persist_session_cookies(self._http)
            except DivarSessionConnectionError:
                self.close()
                raise
            except Exception:
                self.close()
                raise DivarSessionConnectionError("Protected account verification failed.") from None
        return self._http

    def _persist_session_cookies(self, session):
        try:
            target_path = self.project_root / "divar_storage_state.json"
            cookies_list = []
            for cookie in session.cookies:
                cookies_list.append({
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain or ".divar.ir",
                    "path": cookie.path or "/",
                    "secure": bool(cookie.secure),
                    "expires": cookie.expires if cookie.expires else -1,
                })
            if cookies_list:
                existing = {}
                if target_path.exists():
                    try:
                        existing = json.loads(target_path.read_text(encoding="utf-8"))
                    except Exception:
                        existing = {}
                existing["cookies"] = cookies_list
                target_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _verify_authenticated_account(self):
        # The protected HTTP endpoint is authoritative. Waiting for the UI to
        # emit that same response falsely failed healthy sessions during resume.
        self._authenticated_http()
        self._verified_at = time.monotonic()

    def fetch_detail_json(self, token, **_kwargs):
        if not token or not all(c.isalnum() or c in "_-" for c in token):
            raise ValueError("invalid_post_token")
        with self._lock:
            session = self._authenticated_http()
            cached = self._detail_cache.get(token)
            if cached and time.monotonic() - cached[0] < 900:
                result = deepcopy(cached[1])
                result["_saghf_cached_detail"] = True
                return result
            time.sleep(max(0.0, 2.0 - (time.monotonic() - self._last_detail_at)))
            self._last_detail_at = time.monotonic()
            try:
                # Reuse the same authenticated session for bounded transient
                # network retries; never retry access-denied/rate-limit responses.
                for attempt in range(3):
                    try:
                        response = session.get("https://api.divar.ir/v8/posts-v2/web/" + token, timeout=(4, 10), allow_redirects=False)
                        break
                    except (requests.ConnectionError, requests.Timeout):
                        if attempt == 2:
                            raise
                        time.sleep(0.5 * (attempt + 1))
                if response.status_code in {404, 410}:
                    return {"source_removed": True}
                if response.status_code != 200:
                    self._raise_http_error(response, "detail")
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
                    raise DivarSessionConnectionError("Unverifiable native detail response.")
                if len(self._detail_cache) >= 1000:
                    self._detail_cache.pop(next(iter(self._detail_cache)))
                self._detail_cache[token] = (time.monotonic(), deepcopy(payload))
                return payload
            except DivarSessionConnectionError:
                raise
            except Exception:
                raise DivarSessionConnectionError("Authenticated detail connection failed.") from None

    def close(self):
        if self._http is not None:
            self._http.close()
        self._http = None
        self._http_verified_at = 0.0
        self._detail_cache.clear()
        self._search_templates.clear()
        if self._cdp_runtime is not None:
            # Never close the user's CDP browser/context or any original tab.
            if self._cdp_owned_page is not None:
                try:
                    self._cdp_owned_page.close()
                except Exception:
                    pass
            self._cdp_owned_page = None
            self._page = None
            self._context = None
            try:
                self._cdp_runtime.stop()
            finally:
                self._cdp_runtime = None
                self._cdp_browser = None
        super().close()
