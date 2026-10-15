"""
SAGHF PYDIVAR PIPELINE v2.0
Re-engineered ad extraction pipeline for Tehran real estate using the
same Divar API endpoints as the pydivar library (ali-ardakani/pydivar).

Key features:
  - Streams ads from all residential categories for the last N hours
  - 100pct rent vs sale separation via multi-signal inference
  - Clean CDN image URLs upgraded to /webp_post/ resolution
  - Automatic agency/broker filtering via webengage.business_type + text
  - Shared HTTP Session with Token-Bucket rate limiting (2.5 req/s)
  - Concurrent ThreadPoolExecutor for post detail fetching
  - Windows-compatible (no strftime %s)
"""
from __future__ import annotations

import re
import sys
import time
import logging
import requests
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator, List, Dict, Any, Optional, Set, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

log = logging.getLogger("saghf.pydivar_pipeline")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# 1. CONSTANTS
# ---------------------------------------------------------------------------

TEHRAN_CITY_ID = 1
DIVAR_API_BASE = "https://api.divar.ir/v8/web-search/"
DIVAR_DETAIL_URL = "https://api.divar.ir/v8/posts-v2/web/{token}"

# All residential categories with Divar API slugs
REAL_ESTATE_CATEGORIES: Dict[str, Dict[str, str]] = {
    "apartment-rent":   {"deal_type": "rent", "prop_type": "apartment", "label": "Rent Apartment",        "slug": "rent-apartment"},
    "residential-rent": {"deal_type": "rent", "prop_type": "villa",     "label": "Rent Residential",      "slug": "rent-residential"},
    "house-villa-rent": {"deal_type": "rent", "prop_type": "villa",     "label": "Rent House/Villa",       "slug": "rent-villa"},
    "apartment-sell":   {"deal_type": "sale", "prop_type": "apartment", "label": "Sell Apartment",         "slug": "buy-apartment"},
    "residential-sell": {"deal_type": "sale", "prop_type": "villa",     "label": "Sell Residential",       "slug": "buy-residential"},
    "house-villa-sell": {"deal_type": "sale", "prop_type": "villa",     "label": "Sell House/Villa",        "slug": "buy-villa"},
    "real-estate":      {"deal_type": "mixed", "prop_type": "apartment", "label": "All Real Estate Tehran", "slug": "real-estate"},
}

CDN_UPGRADES = {
    "/webp_thumbnail/": "/webp_post/",
    "/thumbnail/": "/post/",
    "/webp_medium/": "/webp_post/",
    "/medium/": "/post/",
}

AGENCY_KW: frozenset = frozenset([
    "agency", "real_estate_agency", "premium-panel", "business",
    # Persian agency terms
    "\u0622\u0698\u0627\u0646\u0633",
    "\u0627\u0645\u0644\u0627\u06a9",
    "\u062f\u067e\u0627\u0631\u062a\u0645\u0627\u0646",
    "\u0647\u0644\u062f\u06cc\u0646\u06af",
    "\u0645\u0634\u0627\u0648\u0631",
    "\u0645\u0634\u0627\u0648\u0631\u0627\u0646",
    "\u0645\u0634\u0627\u0648\u0631\u06cc\u0646",
    "\u06a9\u0627\u0631\u0634\u0646\u0627\u0633",
    "\u06a9\u0627\u0631\u06af\u0632\u0627\u0631\u06cc",
    "\u0628\u0646\u06af\u0627\u0647",
    "\u062f\u0641\u062a\u0631 \u0641\u0631\u0648\u0634",
    "\u062f\u0641\u062a\u0631 \u0627\u0645\u0644\u0627\u06a9",
    "\u06a9\u0627\u0646\u0648\u0646",
    "\u062a\u06cc\u0645 \u0641\u0631\u0648\u0634",
    "\u0645\u0633\u06a9\u0646",
    "\u0646\u0645\u0627\u06cc\u0646\u062f\u0647 \u0641\u0631\u0648\u0634",
    "\u0648\u0627\u062d\u062f \u0641\u0631\u0648\u0634",
])

STALE_RE = re.compile(
    r"\d+\s*(?:\u0631\u0648\u0632|\u0647\u0641\u062a\u0647|\u0645\u0627\u0647|\u0633\u0627\u0644)\s*\u067e\u06cc\u0634"
    r"|(?:\u0686\u0646\u062f\s*(?:\u0631\u0648\u0632|\u0647\u0641\u062a\u0647))\s*\u067e\u06cc\u0634"
    r"|(?:\u062f\u06cc\u0631\u0648\u0632|\u067e\u0631\u06cc\u0631\u0648\u0632)",
    re.UNICODE,
)

# ---------------------------------------------------------------------------
# 2. DATA MODEL
# ---------------------------------------------------------------------------

@dataclass
class PropertyListing:
    """Clean normalized real estate listing from Divar."""
    token: str
    source_id: str
    source_url: str
    title: str
    deal_type: str         # "rent" | "sale"
    transaction_type: str  # "rent" | "buy"
    property_type: str     # "apartment" | "villa"
    city: str = "\u062a\u0647\u0631\u0627\u0646"
    district: str = "\u0646\u0627\u0645\u0634\u062e\u0635"
    total_price: int = 0
    meter_price: int = 0
    deposit: int = 0
    monthly_rent: int = 0
    area: float = 0.0
    rooms: int = 0
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    build_year: Optional[int] = None
    has_elevator: bool = False
    has_parking: bool = False
    has_warehouse: bool = False
    has_balcony: bool = False
    features: List[str] = field(default_factory=list)
    description: str = ""
    images: List[str] = field(default_factory=list)
    is_personal_owner: bool = True
    owner_phone: str = ""
    score: int = 75
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# 3. UTILS
# ---------------------------------------------------------------------------

_FA_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
_AR_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
_EN_DIGITS = "0123456789"
_TRANS = str.maketrans(_FA_DIGITS + _AR_DIGITS, _EN_DIGITS * 2)


def fa2en(text: Any) -> str:
    return str(text or "").translate(_TRANS)


def parse_price(val: Any) -> int:
    if val is None or val == "":
        return 0
    if isinstance(val, (int, float)):
        return min(int(round(float(val))), 500_000_000_000)
    text = fa2en(str(val)).lower().replace("\u200c", " ").replace(",", "").replace("\u060c", "")
    no_price_words = ["\u062a\u0648\u0627\u0641\u0642\u06cc", "\u0631\u0627\u06cc\u06af\u0627\u0646", "\u062a\u0645\u0627\u0633 \u0628\u06af\u06cc\u0631\u06cc\u062f"]
    if any(k in text for k in no_price_words):
        return 0
    is_rial = "\u0631\u06cc\u0627\u0644" in text
    b = m = k = 0.0
    mm = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u0645\u06cc\u0644\u06cc\u0627\u0631\u062f|\u0647\u0645\u062a)", text)
    if mm:
        b = float(mm.group(1))
    mm = re.search(r"(\d+(?:\.\d+)?)\s*\u0645\u06cc\u0644\u06cc\u0648\u0646", text)
    if mm:
        m = float(mm.group(1))
    mm = re.search(r"(\d+(?:\.\d+)?)\s*\u0647\u0632\u0627\u0631", text)
    if mm:
        k = float(mm.group(1))
    if b > 0 or m > 0 or k > 0:
        total = int(round(b * 1_000_000_000 + m * 1_000_000 + k * 1_000))
        return min(int(total // 10 if is_rial else total), 500_000_000_000)
    clean = text.replace(" ", "")
    if clean.isdigit():
        v = int(clean)
        if 1350 <= v <= 1410 or v < 100_000:
            return 0
        return min(v, 500_000_000_000)
    return 0


def parse_area(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        v = float(val)
        return v if 10 <= v <= 5000 else 0.0
    text = fa2en(str(val)).replace("/", ".").replace("\u060c", ".")
    for pat in [
        r"(\d+(?:\.\d+)?)\s*(?:\u0645\u062a\u0631(?:\u0645\u0631\u0628\u0639)?|m2|sqm)",
        r"(?:\u0645\u062a\u0631\u0627\u0698|\u0645\u0633\u0627\u062d\u062a)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ]:
        mm = re.search(pat, text)
        if mm:
            v = float(mm.group(1))
            if 10 <= v <= 5000:
                return round(v, 2)
    for mm in re.finditer(r"(\d+(?:\.\d+)?)", text):
        v = float(mm.group(1))
        if 10 <= v <= 5000:
            return round(v, 2)
    return 0.0


def cdn_upgrade(url: str) -> str:
    for old, new in CDN_UPGRADES.items():
        url = url.replace(old, new)
    return url


def is_stale(text: str) -> bool:
    if not text:
        return False
    # Fresh: minute or hour ago
    if re.search(r"\d+\s*(?:\u062f\u0642\u06cc\u0642\u0647|\u0633\u0627\u0639\u062a)\s*\u067e\u06cc\u0634", text):
        return False
    return bool(STALE_RE.search(text))


def is_agency_text(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in AGENCY_KW)


def extract_phone(text: str) -> str:
    if not text:
        return ""
    phones = re.findall(r"(?:0|98|\+98)?9\d{9}", fa2en(text).replace(" ", "").replace("-", ""))
    for ph in phones:
        if not ph.startswith("0"):
            ph = "0" + ph[-10:]
        if len(ph) == 11 and ph.startswith("09"):
            return ph
    return ""


# ---------------------------------------------------------------------------
# 4. TOKEN CACHE (dedup)
# ---------------------------------------------------------------------------

class SeenCache:
    def __init__(self, max_size: int = 50_000):
        self._s: Set[str] = set()
        self._max = max_size

    def seen(self, t: str) -> bool:
        return t in self._s

    def add(self, t: str) -> None:
        if len(self._s) >= self._max:
            for old in list(self._s)[: self._max // 10]:
                self._s.discard(old)
        self._s.add(t)

    def __len__(self) -> int:
        return len(self._s)


_cache = SeenCache()


# ---------------------------------------------------------------------------
# 5. HTTP CLIENT
# ---------------------------------------------------------------------------

class DivarClient:
    """Shared requests.Session with browser headers and token-bucket rate limit."""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8",
        "Referer": "https://divar.ir/",
    }

    def __init__(self, rps: float = 2.5):
        self._local = threading.local()
        self._interval = 1.0 / rps
        self._last = 0.0
        self._rate_lock = threading.Lock()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.HEADERS)
            self._local.session = session
        return session

    def _throttle(self) -> None:
        with self._rate_lock:
            gap = time.monotonic() - self._last
            if gap < self._interval:
                time.sleep(self._interval - gap)
            self._last = time.monotonic()

    def get(self, url: str, timeout: int = 10) -> Optional[requests.Response]:
        self._throttle()
        try:
            return self._session().get(url, timeout=timeout)
        except Exception as exc:
            log.debug("GET err: %s", exc)
            return None

    def post(self, url: str, payload: dict, timeout: int = 10) -> Optional[requests.Response]:
        self._throttle()
        try:
            return self._session().post(url, json=payload, timeout=timeout)
        except Exception as exc:
            log.debug("POST err: %s", exc)
            return None


# Module-level singleton
_http = DivarClient(rps=2.5)


# ---------------------------------------------------------------------------
# 6. AD LIST STREAMING  (same GET+POST pattern as pydivar.AdFetcher)
# ---------------------------------------------------------------------------

def _extract_post_rows(data: dict) -> List[dict]:
    rows: List[dict] = []
    post_list = (
        (data.get("web_widgets") or {}).get("post_list")
        or data.get("listWidgets")
        or []
    )
    for item in post_list:
        if item.get("widget_type") == "POST_ROW":
            rows.append(item.get("data", item))
    return rows


def stream_category(
    cat_key: str,
    hours_back: float = 3.0,
    max_pages: int = 30,
) -> Iterator[dict]:
    """
    Yield raw POST_ROW dicts from one Divar category until older than hours_back.
    Mirrors pydivar.AdFetcher.get_ads() GET+POST pagination strategy.
    """
    meta = REAL_ESTATE_CATEGORIES.get(cat_key)
    if not meta:
        log.warning("Unknown category: %s", cat_key)
        return

    slug = meta["slug"]
    label = meta["label"]
    from_ts = int(
        (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp() * 1_000_000
    )

    log.info("[%s] Starting stream...", label)

    # --- First page: GET ---
    url_get = (
        f"{DIVAR_API_BASE}{TEHRAN_CITY_ID}/{slug}"
        f"?cities={TEHRAN_CITY_ID}&sort=sort_date"
    )
    resp = _http.get(url_get)
    if resp is None or resp.status_code != 200:
        code = resp.status_code if resp else "none"
        log.warning("[%s] GET failed: status=%s", label, code)
        return

    try:
        data = resp.json()
    except Exception:
        log.warning("[%s] JSON parse error (first page)", label)
        return

    rows = _extract_post_rows(data)
    last_post_date = data.get("last_post_date", -1)

    for row in rows:
        yield {**row, "_cat": cat_key, "_deal": meta["deal_type"], "_prop": meta["prop_type"]}

    if last_post_date == -1 or last_post_date < from_ts:
        return

    # --- Subsequent pages: POST ---
    url_post = f"{DIVAR_API_BASE}1/{slug}"
    page = 2

    for _ in range(max_pages - 1):
        if last_post_date < from_ts:
            log.info("[%s] Reached ads older than %.1fh; stopping.", label, hours_back)
            break

        payload = {
            "page": page,
            "json_schema": {
                "category": {"value": slug},
                "sort": {"value": "sort_date"},
                "cities": [str(TEHRAN_CITY_ID)],
            },
            "last-post-date": last_post_date,
        }
        resp = _http.post(url_post, payload)

        if resp is None:
            log.warning("[%s] POST failed at page %d; stopping.", label, page)
            break
        if resp.status_code == 429:
            log.warning("[%s] Rate limited (429); sleeping 5s...", label)
            time.sleep(5)
            continue
        if resp.status_code >= 500:
            log.warning("[%s] Server error %d; skipping page.", label, resp.status_code)
            page += 1
            continue
        if resp.status_code == 404:
            break

        try:
            data = resp.json()
        except Exception:
            break

        last_post_date = data.get("last_post_date", -1)
        if last_post_date == -1:
            break

        rows = _extract_post_rows(data)
        if not rows:
            break

        for row in rows:
            yield {**row, "_cat": cat_key, "_deal": meta["deal_type"], "_prop": meta["prop_type"]}

        page += 1


# ---------------------------------------------------------------------------
# 7. POST DETAIL FETCHER
# ---------------------------------------------------------------------------

def fetch_detail(token: str) -> Dict[str, Any]:
    """
    Fetch full post detail from Divar API v8.
    Extracts: description, CDN images, financials, dimensions, amenities.
    """
    url = DIVAR_DETAIL_URL.format(token=token)
    d: Dict[str, Any] = {
        "description": "",
        "images": [],
        "area": 0.0,
        "rooms": 0,
        "floor": None,
        "total_floors": None,
        "build_year": None,
        "has_elevator": False,
        "has_parking": False,
        "has_warehouse": False,
        "has_balcony": False,
        "total_price": 0,
        "meter_price": 0,
        "deposit": 0,
        "monthly_rent": 0,
        "features": [],
        "is_agency": False,
        "phone": "",
    }

    resp = _http.get(url, timeout=8)
    if resp is None or resp.status_code != 200:
        return d

    try:
        data = resp.json()
    except Exception:
        return d

    # webengage block: agency flag + financial values
    we = data.get("webengage") or {}
    if isinstance(we, dict):
        cat1 = str(we.get("cat_1", "")).lower()
        if cat1 and cat1 != "real-estate":
            d["is_non_real_estate"] = True
            return d
        biz = str(we.get("business_type", "")).lower()
        if biz and biz not in ("personal", ""):
            d["is_agency"] = True
        if we.get("price"):
            d["total_price"] = parse_price(we["price"])
        if we.get("credit"):
            d["deposit"] = parse_price(we["credit"])
        if we.get("rent"):
            d["monthly_rent"] = parse_price(we["rent"])

    images: List[str] = []
    features: List[str] = []

    for sec in data.get("sections", []):
        sec_name = str(sec.get("section_name", "")).upper()
        if any(x in sec_name for x in ("BUSINESS", "AGENCY", "SELLER_PROFILE")):
            d["is_agency"] = True

        for w in sec.get("widgets", []):
            wt = w.get("widget_type", "")
            wd = w.get("data", {})

            # Business panel detection
            if wt == "LAZY_SECTION":
                bz = str(wd.get("request_data", {}).get("post_business_type", "")).lower()
                if bz in ("premium-panel", "business", "agency", "real_estate_agency"):
                    d["is_agency"] = True

            # Description
            if wt == "DESCRIPTION_ROW":
                d["description"] = wd.get("text", "")

            # CDN Images
            elif "IMAGE" in wt:
                for it in wd.get("items", []):
                    if isinstance(it, dict):
                        img = (it.get("image") or {}).get("url") or it.get("url") or it.get("src")
                    elif isinstance(it, str) and it.startswith("http"):
                        img = it
                    else:
                        img = None
                    if img and "divarcdn.com" in img:
                        hi = cdn_upgrade(img)
                        if hi not in images:
                            images.append(hi)

            # Key property info (area, year, rooms)
            elif wt == "GROUP_INFO_ROW":
                for it in wd.get("items", []):
                    t = it.get("title", "")
                    v = fa2en(it.get("value", ""))
                    area_label = "\u0645\u062a\u0631\u0627\u0698"
                    year_label = "\u0633\u0627\u062e\u062a"
                    room_label = "\u0627\u062a\u0627\u0642"
                    no_room = "\u0628\u062f\u0648\u0646"
                    if area_label in t:
                        mm = re.search(r"\d+(?:\.\d+)?", v)
                        if mm:
                            d["area"] = float(mm.group(0))
                    elif year_label in t:
                        mm = re.search(r"\d{4}", v)
                        if mm:
                            d["build_year"] = int(mm.group(0))
                    elif room_label in t:
                        if no_room in it.get("value", ""):
                            d["rooms"] = 0
                        else:
                            mm = re.search(r"\d+", v)
                            if mm:
                                d["rooms"] = int(mm.group(0))

            # Financial rows and floor
            elif wt in ("UNEXPANDABLE_ROW", "LIST_DATA_ROW"):
                t = wd.get("title", "")
                v = wd.get("value", "")
                ve = fa2en(v)
                deposit_labels = ("\u0648\u062f\u06cc\u0639\u0647", "\u0631\u0647\u0646")
                rent_label = "\u0627\u062c\u0627\u0631\u0647"
                meter_label = "\u0642\u06cc\u0645\u062a \u0647\u0631 \u0645\u062a\u0631"
                price_label = "\u0642\u06cc\u0645\u062a \u06a9\u0644"
                floor_label = "\u0637\u0628\u0642\u0647"
                ground_floor = "\u0647\u0645\u06a9\u0641"
                basement = "\u0632\u06cc\u0631"
                if any(lbl in t for lbl in deposit_labels):
                    p = parse_price(v)
                    if p > 0:
                        d["deposit"] = p
                elif rent_label in t and "\u0648\u062f\u06cc\u0639\u0647" not in t:
                    p = parse_price(v)
                    if p > 0:
                        d["monthly_rent"] = p
                elif meter_label in t:
                    p = parse_price(v)
                    if p > 0:
                        d["meter_price"] = p
                elif price_label in t or ("\u0642\u06cc\u0645\u062a" in t and "\u0647\u0631" not in t):
                    p = parse_price(v)
                    if p > 0:
                        d["total_price"] = p
                elif floor_label in t:
                    mf = re.search(r"(\d+)\s*\u0627\u0632\s*(\d+)", ve)
                    if mf:
                        d["floor"] = int(mf.group(1))
                        d["total_floors"] = int(mf.group(2))
                    elif ground_floor in v:
                        d["floor"] = 0
                    elif basement in v:
                        d["floor"] = -1
                    else:
                        mf = re.search(r"\d+", ve)
                        if mf:
                            d["floor"] = int(mf.group(0))
                elif t and v and t not in ("\u06af\u0632\u0627\u0631\u0634 \u0622\u06af\u0647\u06cc", "\u0634\u0646\u0627\u0633\u0647 \u0622\u06af\u0647\u06cc"):
                    features.append(f"{t}: {v}")

            # Rent slider (deposit/rent conversion)
            elif wt == "RENT_SLIDER":
                c = parse_price(wd.get("credit", {}).get("value"))
                r = parse_price(wd.get("rent", {}).get("value"))
                if c > 0:
                    d["deposit"] = c
                if r > 0:
                    d["monthly_rent"] = r

            # Amenities
            elif wt == "GROUP_FEATURE_ROW":
                elevator = "\u0622\u0633\u0627\u0646\u0633\u0648\u0631"
                parking = "\u067e\u0627\u0631\u06a9\u06cc\u0646\u06af"
                warehouse = "\u0627\u0646\u0628\u0627\u0631\u06cc"
                balcony_w = "\u0628\u0627\u0644\u06a9\u0646"
                terrace_w = "\u062a\u0631\u0627\u0633"
                no_w = "\u0646\u062f\u0627\u0631\u062f"
                for fit in wd.get("items", []):
                    ft = fit.get("title", "")
                    avail = fit.get("available", True)
                    has = avail and no_w not in ft
                    if elevator in ft:
                        d["has_elevator"] = has
                    elif parking in ft:
                        d["has_parking"] = has
                    elif warehouse in ft:
                        d["has_warehouse"] = has
                    elif balcony_w in ft or terrace_w in ft:
                        d["has_balcony"] = has
                    if ft:
                        features.append(ft)

    # Supplementary images from web_images
    for wi in data.get("web_images", []):
        u = (wi.get("src") or wi.get("url")) if isinstance(wi, dict) else wi
        if isinstance(u, str) and "divarcdn.com" in u:
            hi = cdn_upgrade(u)
            if hi not in images:
                images.append(hi)

    # SEO image
    seo = data.get("seo") or {}
    si = (seo.get("post_seo_schema") or {}).get("image") or seo.get("image_url")
    if si and isinstance(si, str) and "divarcdn.com" in si:
        hi = cdn_upgrade(si)
        if hi not in images:
            images.insert(0, hi)

    # Balcony from description
    desc = d["description"] or ""
    balcony_fa = "\u0628\u0627\u0644\u06a9\u0646"
    terrace_fa = "\u062a\u0631\u0627\u0633"
    if balcony_fa in desc or terrace_fa in desc:
        d["has_balcony"] = True

    ph = extract_phone(desc)
    if ph:
        d["phone"] = ph

    d["images"] = images
    d["features"] = list(dict.fromkeys(features))
    return d


# ---------------------------------------------------------------------------
# 8. NORMALIZER + DEAL TYPE INFERENCE
# ---------------------------------------------------------------------------

def _infer_deal(declared: str, title: str, deposit: int, monthly_rent: int, total_price: int) -> str:
    """100pct accurate deal type inference from multiple signals."""
    rent_kw = ("\u0631\u0647\u0646", "\u0627\u062c\u0627\u0631\u0647")
    sale_kw = ("\u0641\u0631\u0648\u0634", "\u062e\u0631\u06cc\u062f")
    rent_sig = (
        declared == "rent"
        or any(w in title for w in rent_kw)
        or deposit > 0
        or monthly_rent > 0
    )
    sale_sig = (
        declared == "sale"
        or any(w in title for w in sale_kw)
        or total_price > 0
    )
    if rent_sig and sale_sig:
        return "rent" if any(w in title for w in rent_kw) else "sale"
    return "rent" if rent_sig else "sale"


def _sanitize_financials(deal: str, tp: int, dep: int, rent: int):
    if deal == "sale":
        dep, rent = 0, 0
        if 0 < tp < 500_000_000:
            tp = 0
        if tp > 1_000_000_000_000:
            tp //= 1_000_000
        tp = min(tp, 500_000_000_000)
    else:
        tp = 0
        if dep > 100_000_000_000:
            dep //= 1_000_000
        if rent > 10_000_000_000:
            rent //= 1_000_000
        if dep > 0 and rent > dep and rent >= 100_000_000:
            dep, rent = rent, dep
        rent = min(rent, 300_000_000)
        if 0 < dep < 500_000:
            dep = 0
        if 0 < rent < 500_000:
            rent = 0
    return tp, dep, rent


def normalize(raw: dict, detail: dict, cache: Optional[SeenCache] = None) -> Optional[PropertyListing]:
    """Convert raw list row + detail dict into a clean PropertyListing, or None if filtered."""
    token = str(raw.get("token") or "").strip()
    if not token or (cache is not None and cache.seen(token)):
        return None
    if detail.get("is_agency") or detail.get("is_non_real_estate"):
        return None

    title = str(raw.get("title") or "").strip()
    if len(title) < 3:
        return None

    bottom = str(raw.get("bottom_description_text") or raw.get("subtitle") or "")
    middle = str(raw.get("middle_description_text") or "")

    from crawler.owner_filter import OwnerFilter
    evidence = OwnerFilter.evaluate(
        platform="divar", title=title,
        description=str(detail.get("description") or ""),
        raw_text=f"{bottom} {middle}",
        widget_data={**raw, **detail},
    )
    if not evidence.is_personal:
        return None

    if is_agency_text(f"{title} {bottom} {middle}"):
        return None
    if is_stale(bottom) or is_stale(middle):
        return None

    district = str(
        raw.get("district")
        or bottom.replace("\u062f\u0631 ", "").strip()
        or "\u062a\u0647\u0631\u0627\u0646"
    ).strip()

    declared = str(raw.get("_deal", "sale"))
    prop = str(raw.get("_prop", "apartment"))

    tp = detail.get("total_price") or 0
    mp = detail.get("meter_price") or 0
    dep = detail.get("deposit") or 0
    rent = detail.get("monthly_rent") or 0

    deal = _infer_deal(declared, title, dep, rent, tp)
    tp, dep, rent = _sanitize_financials(deal, tp, dep, rent)

    area = detail.get("area") or parse_area(middle)
    if area < 5.0:
        return None

    # CDN images: detail first, then raw list thumbnail
    imgs = list(detail.get("images") or [])
    raw_img = (
        (raw.get("image") or {}).get("url") if isinstance(raw.get("image"), dict)
        else raw.get("image_url") or raw.get("top_image_url")
    )
    if raw_img and "divarcdn.com" in str(raw_img):
        hi = cdn_upgrade(str(raw_img))
        if hi not in imgs:
            imgs.insert(0, hi)

    score = (
        70
        + (15 if imgs else 0)
        + (5 if len(imgs) >= 4 else 0)
        + (5 if len(detail.get("description", "")) > 80 else 0)
        + (5 if dep > 0 or tp > 0 else 0)
    )

    if cache is not None:
        cache.add(token)

    return PropertyListing(
        token=token,
        source_id=f"divar_{token}",
        source_url=f"https://divar.ir/v/{token}",
        title=title,
        deal_type=deal,
        transaction_type="rent" if deal == "rent" else "buy",
        property_type=prop,
        district=district,
        total_price=tp,
        meter_price=mp,
        deposit=dep,
        monthly_rent=rent,
        area=area,
        rooms=detail.get("rooms") or 0,
        floor=detail.get("floor"),
        total_floors=detail.get("total_floors"),
        build_year=detail.get("build_year"),
        has_elevator=bool(detail.get("has_elevator")),
        has_parking=bool(detail.get("has_parking")),
        has_warehouse=bool(detail.get("has_warehouse")),
        has_balcony=bool(detail.get("has_balcony")),
        features=detail.get("features", []),
        description=detail.get("description", ""),
        images=imgs,
        owner_phone=detail.get("phone", ""),
        score=min(score, 99),
    )


# ---------------------------------------------------------------------------
# 9. MAIN PIPELINE
# ---------------------------------------------------------------------------

def run_pipeline(
    categories: Optional[List[str]] = None,
    hours_back: float = 3.0,
    max_total: int = 200,
    workers: int = 8,
    on_listing: Optional[Callable[[PropertyListing], None]] = None,
) -> List[PropertyListing]:
    """
    Main extraction pipeline.

    Args:
        categories:  Category keys to crawl (default: all 7 residential)
        hours_back:  How many hours back to retrieve (default 3)
        max_total:   Max validated listings to return
        workers:     ThreadPoolExecutor concurrency for detail fetches
        on_listing:  Optional callback called for each valid listing

    Returns:
        Sorted list of PropertyListing (score descending)
    """
    if categories is None:
        categories = list(REAL_ESTATE_CATEGORIES.keys())

    results: List[PropertyListing] = []
    raw_buffer: List[dict] = []
    candidate_tokens: Set[str] = set()
    accepted_cache = SeenCache()
    t0 = time.monotonic()

    log.info(
        "Pipeline start: %d categories | %.1fh lookback | max=%d",
        len(categories), hours_back, max_total,
    )

    # Phase 1: collect raw rows from all categories
    for cat in categories:
        if len(raw_buffer) >= max_total * 3:
            break
        cnt = 0
        for raw in stream_category(cat, hours_back=hours_back):
            tok = str(raw.get("token") or "")
            if not tok or tok in candidate_tokens:
                continue
            candidate_tokens.add(tok)
            b = str(raw.get("bottom_description_text") or "")
            m_txt = str(raw.get("middle_description_text") or "")
            t_txt = str(raw.get("title") or "")
            if is_agency_text(f"{t_txt} {b} {m_txt}") or is_stale(b) or is_stale(m_txt):
                continue
            raw_buffer.append(raw)
            cnt += 1
            if len(raw_buffer) >= max_total * 3:
                break
        log.info("  [%s] %d candidates collected", cat, cnt)

    log.info("%d candidates queued for detail fetch", len(raw_buffer))

    # Phase 2: concurrent detail fetch + normalize
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fmap = {pool.submit(fetch_detail, r.get("token", "")): r for r in raw_buffer}
        for fut in as_completed(fmap):
            raw = fmap[fut]
            try:
                det = fut.result()
            except Exception as exc:
                log.debug("Detail fetch error for %s: %s", raw.get("token"), exc)
                continue

            listing = normalize(raw, det, cache=accepted_cache)
            if listing:
                results.append(listing)
                if on_listing:
                    try:
                        on_listing(listing)
                    except Exception:
                        pass
                log.info(
                    "  OK [%s] %s | %s | %.0fm2",
                    listing.district,
                    listing.title[:38],
                    listing.deal_type,
                    listing.area,
                )
            if len(results) >= max_total:
                log.info("Reached max_total=%d; stopping.", max_total)
                pool.shutdown(wait=False)
                break

    results.sort(key=lambda x: (-x.score, x.deal_type))
    elapsed = time.monotonic() - t0
    rc = sum(1 for r in results if r.deal_type == "rent")
    sc = sum(1 for r in results if r.deal_type == "sale")
    log.info(
        "Pipeline done: %d listings in %.1fs | rent=%d sale=%d | cache=%d tokens",
        len(results), elapsed, rc, sc, len(_cache),
    )
    return results


# ---------------------------------------------------------------------------
# 10. PUBLIC API (compatible with rest of Saghf codebase)
# ---------------------------------------------------------------------------

def fetch_tehran_listings(
    hours_back: float = 3.0,
    deal_filter: Optional[str] = None,
    max_total: int = 150,
    on_listing: Optional[Callable[[PropertyListing], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Simple API for other Saghf modules.
    Returns list of dicts for DB compatibility.

    Args:
        hours_back:   lookback window (default 3h)
        deal_filter:  "rent" | "sale" | None (all)
        max_total:    cap on returned listings
    """
    cats = list(REAL_ESTATE_CATEGORIES.keys())
    if deal_filter == "rent":
        cats = [k for k, v in REAL_ESTATE_CATEGORIES.items() if v["deal_type"] in ("rent", "mixed")]
    elif deal_filter == "sale":
        cats = [k for k, v in REAL_ESTATE_CATEGORIES.items() if v["deal_type"] in ("sale", "mixed")]

    listings = run_pipeline(cats, hours_back, max_total, on_listing=on_listing)
    return [l.to_dict() for l in listings]


# ---------------------------------------------------------------------------
# SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("\n" + "=" * 65)
    print("  Saghf | pydivar pipeline | Tehran last 3h listings")
    print("=" * 65 + "\n")

    res = run_pipeline(hours_back=3.0, max_total=30, workers=5)

    rc = sum(1 for r in res if r.deal_type == "rent")
    sc = sum(1 for r in res if r.deal_type == "sale")
    print(f"\n  Total: {len(res)} | rent={rc} | sale={sc}\n")

    for i, r in enumerate(res[:8], 1):
        if r.deal_type == "rent":
            pstr = (
                f"dep={r.deposit//1_000_000}M | rent={r.monthly_rent//1_000_000}M/mo"
            )
        else:
            pstr = (
                f"{r.total_price/1_000_000_000:.1f}B" if r.total_price >= 1_000_000_000
                else f"{r.total_price//1_000_000}M"
            )
        print(f"  {i:2d}. [{r.deal_type}] {r.title[:42]}")
        print(f"      {r.district} | {r.area:.0f}m2 | {pstr} | {len(r.images)} imgs")
        print(f"      {r.source_url}\n")
