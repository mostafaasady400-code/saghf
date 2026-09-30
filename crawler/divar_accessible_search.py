"""Resumable, evidence-reporting crawl of accessible Divar search pages."""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from crawler.hybrid_divar import HybridDivarCrawler
from crawler.publication_time import PublicationWindow, parse_publication_time
from crawler.publisher_classifier import (
    EXPLICIT_AGENCY,
    LIKELY_INTERMEDIARY,
    LIKELY_OWNER,
    UNKNOWN,
    PublisherClassifier,
)
from crawler.schemas import parse_area, parse_price, persian_to_english_numbers
from data.tehran_districts import get_divar_slug_for_district


@dataclass
class AccessibleSearchCriteria:
    city: str = "tehran"
    districts: List[str] = field(default_factory=list)
    deal_type: str = "any"
    property_type: str = "apartment"
    min_area: Optional[float] = None
    max_area: Optional[float] = None
    rooms: Optional[int] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_deposit: Optional[int] = None
    max_deposit: Optional[int] = None
    min_rent: Optional[int] = None
    max_rent: Optional[int] = None
    has_parking: Optional[bool] = None
    has_elevator: Optional[bool] = None
    has_warehouse: Optional[bool] = None
    has_balcony: Optional[bool] = None
    window_hours: int = 24

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AccessibleSearchCriteria":
        allowed = cls.__dataclass_fields__.keys()
        clean = {key: data.get(key) for key in allowed if key in data}
        clean["districts"] = [
            str(item).strip() for item in (clean.get("districts") or []) if str(item).strip()
        ]
        return cls(**clean)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PageFetchResult:
    status_code: int
    text: str = ""
    error: Optional[str] = None
    blocked: bool = False
    retry_after: Optional[float] = None


class DivarAccessibleSearchCrawler:
    """
    Crawl every accessible page for an exact request.

    No browser automation, proxy rotation, CAPTCHA solving or login automation is
    used. A blocked/limited source produces a resumable, incomplete report.
    """

    BASE_URL = "https://divar.ir/s"
    SOURCE_RETRY_LIMIT = 2
    EMPTY_PAGE_RETRY_LIMIT = 2
    REPEATED_CURSOR_LIMIT = 2

    def __init__(
        self,
        page_fetcher: Optional[Callable[[str], PageFetchResult]] = None,
        detail_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
        semantic_classifier: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        request_delay_seconds: float = 0.8,
        semantic_timeout_seconds: float = 10.0,
        semantic_retry_limit: int = 1,
    ):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Saghf-Local-Property-Search/2.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.5",
        })
        self.page_fetcher = page_fetcher or self._fetch_page
        self._detail_crawler = HybridDivarCrawler(city="tehran", use_proxy=False)
        self.detail_fetcher = detail_fetcher or (
            lambda token: self._detail_crawler._fetch_post_details(token, include_contact=False)
        )
        self.semantic_classifier = semantic_classifier
        self.request_delay_seconds = max(0.0, float(request_delay_seconds))
        self.semantic_timeout_seconds = max(0.1, float(semantic_timeout_seconds))
        self.semantic_retry_limit = max(0, min(2, int(semantic_retry_limit)))
        self._semantic_failures = 0
        self._semantic_circuit_open_until = 0.0

    def crawl(
        self,
        criteria: AccessibleSearchCriteria,
        *,
        reference_time: Optional[datetime] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        max_runtime_seconds: float = 180.0,
        on_record: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None,
        on_checkpoint: Optional[Callable[[Dict[str, Any], Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        if criteria.deal_type not in {"sale", "rent"}:
            raise ValueError("نوع معامله باید پیش از شروع پیمایش مشخص باشد.")

        ref = _naive_utc(reference_time or datetime.now(timezone.utc))
        window_start = ref - timedelta(hours=max(1, int(criteria.window_hours or 24)))
        targets = self._build_targets(criteria)
        checkpoint = checkpoint or {}
        start_target = int(checkpoint.get("target_index") or 0)
        resume_cursor = checkpoint.get("cursor")
        pending_candidates_from_checkpoint = list(checkpoint.get("pending_candidates") or [])
        seen_ids = set(checkpoint.get("seen_source_ids") or [])
        started = time.monotonic()

        report: Dict[str, Any] = {
            "reference_time": ref.isoformat(),
            "window_start": window_start.isoformat(),
            "timezone": "Asia/Tehran",
            "targets_total": len(targets),
            "categories_traversed": 0,
            "pages_traversed": int(checkpoint.get("pages_traversed") or 0),
            "unique_received": len(seen_ids),
            "duplicates_seen": int(checkpoint.get("duplicates_seen") or 0),
            "within_window": 0,
            "uncertain_time": 0,
            "outside_window": 0,
            "after_reference": 0,
            "criteria_matched": 0,
            "likely_owner": 0,
            "explicit_agency": 0,
            "likely_intermediary": 0,
            "unknown": 0,
            "pending_model_review": 0,
            "new_on_recheck": 0,
            "source_retries": 0,
            "coverage_status": "unknown",
            "source_status": "running",
            "stop_reason": None,
            "can_resume": True,
        }

        all_targets_complete = True
        current_checkpoint: Dict[str, Any] = {}

        for target_index, target in enumerate(targets):
            if target_index < start_target:
                continue
            report["categories_traversed"] += 1
            cursor = resume_cursor if target_index == start_target else None
            cursor_repeats = 0
            empty_retries = 0
            page_number = int(checkpoint.get("page_number") or 0) if target_index == start_target else 0
            target_complete = False
            pending_candidates = pending_candidates_from_checkpoint if target_index == start_target else []
            pending_candidates_from_checkpoint = []

            while True:
                if time.monotonic() - started >= max_runtime_seconds:
                    report.update({
                        "coverage_status": "incomplete",
                        "source_status": "time_budget_reached",
                        "stop_reason": "سقف زمان فنی اجرا رسید؛ نقطهٔ ادامه ذخیره شد.",
                    })
                    all_targets_complete = False
                    break

                if pending_candidates:
                    # کاندیدهای باقیمانده از توقف قبلی وسط صفحه بدون نیاز به درخواست مجدد پردازش می‌شوند
                    candidates = pending_candidates
                    pending_candidates = []
                    next_cursor = checkpoint.get("next_page_cursor")
                else:
                    page_number += 1
                    url = self._with_cursor(target["url"], cursor, page_number)
                    fetched = self._fetch_with_retry(url, report)
                    if fetched.blocked or fetched.status_code in {401, 403, 429}:
                        report.update({
                            "coverage_status": "incomplete",
                            "source_status": "blocked_or_rate_limited",
                            "stop_reason": fetched.error or f"منبع با وضعیت {fetched.status_code} دسترسی را محدود کرد.",
                        })
                        all_targets_complete = False
                        break
                    if fetched.status_code != 200:
                        report.update({
                            "coverage_status": "incomplete",
                            "source_status": "source_error",
                            "stop_reason": fetched.error or f"پاسخ ناموفق منبع: {fetched.status_code}",
                        })
                        all_targets_complete = False
                        break

                    candidates, next_cursor = self.parse_page(fetched.text)
                    report["pages_traversed"] += 1

                    if not candidates:
                        empty_retries += 1
                        if empty_retries <= self.EMPTY_PAGE_RETRY_LIMIT and next_cursor:
                            time.sleep(min(2.0, 0.4 * empty_retries))
                            continue
                        if not next_cursor:
                            target_complete = True
                            break
                        report.update({
                            "coverage_status": "incomplete",
                            "source_status": "empty_page_stalled",
                            "stop_reason": "صفحهٔ خالی با نشانگر ادامه دریافت شد و پس از تلاش محدود بازیابی نشد.",
                        })
                        all_targets_complete = False
                        break
                    empty_retries = 0

                page_interrupted = False
                for cand_idx, candidate in enumerate(candidates):
                    if time.monotonic() - started >= max_runtime_seconds:
                        report.update({
                            "coverage_status": "incomplete",
                            "source_status": "time_budget_reached",
                            "stop_reason": "سقف زمان فنی اجرا رسید؛ نقطهٔ ادامه ذخیره شد.",
                        })
                        all_targets_complete = False
                        page_interrupted = True
                        remaining = candidates[cand_idx:]
                        current_checkpoint = {
                            "target_index": target_index,
                            "cursor": cursor,  # cursor صفحهٔ بعد زودتر جلو نمی‌رود
                            "next_page_cursor": next_cursor,
                            "pending_candidates": remaining,
                            "page_number": page_number,
                            "pages_traversed": report["pages_traversed"],
                            "duplicates_seen": report["duplicates_seen"],
                            "seen_source_ids": sorted(seen_ids),
                        }
                        if on_checkpoint:
                            on_checkpoint(current_checkpoint, dict(report))
                        break

                    source_id = candidate["source_id"]
                    if source_id in seen_ids:
                        report["duplicates_seen"] += 1
                        continue
                    seen_ids.add(source_id)
                    report["unique_received"] = len(seen_ids)
                    record, run_meta = self._enrich_candidate(candidate, criteria, ref)
                    self._accumulate_report(report, record, run_meta)
                    if on_record:
                        on_record(record, run_meta)

                    # نقطهٔ ذخیره حین صفحه: کاندیدهای باقیمانده حفظ شده و cursor جلوتر نمی‌رود
                    current_checkpoint = {
                        "target_index": target_index,
                        "cursor": cursor,
                        "next_page_cursor": next_cursor,
                        "pending_candidates": candidates[cand_idx + 1:],
                        "page_number": page_number,
                        "pages_traversed": report["pages_traversed"],
                        "duplicates_seen": report["duplicates_seen"],
                        "seen_source_ids": sorted(seen_ids),
                    }
                    if on_checkpoint:
                        on_checkpoint(current_checkpoint, dict(report))

                if page_interrupted or not all_targets_complete:
                    break

                # صفحه به طور کامل پایان یافت: اکنون cursor به صفحه بعد جلو می‌رود
                current_checkpoint = {
                    "target_index": target_index,
                    "cursor": next_cursor,
                    "next_page_cursor": None,
                    "pending_candidates": [],
                    "page_number": page_number,
                    "pages_traversed": report["pages_traversed"],
                    "duplicates_seen": report["duplicates_seen"],
                    "seen_source_ids": sorted(seen_ids),
                }
                if on_checkpoint:
                    on_checkpoint(current_checkpoint, dict(report))

                if not next_cursor:
                    target_complete = True
                    break
                if str(next_cursor) == str(cursor):
                    cursor_repeats += 1
                    if cursor_repeats >= self.REPEATED_CURSOR_LIMIT:
                        report.update({
                            "coverage_status": "incomplete",
                            "source_status": "pagination_stalled",
                            "stop_reason": "نشانگر ادامه بدون پیشرفت تکرار شد؛ نقطهٔ ادامه ذخیره شد.",
                        })
                        all_targets_complete = False
                        break
                else:
                    cursor_repeats = 0
                cursor = next_cursor
                if self.request_delay_seconds:
                    time.sleep(self.request_delay_seconds)

            if not target_complete:
                break
            resume_cursor = None
            current_checkpoint = {
                "target_index": target_index + 1,
                "cursor": None,
                "next_page_cursor": None,
                "pending_candidates": [],
                "page_number": 0,
                "pages_traversed": report["pages_traversed"],
                "duplicates_seen": report["duplicates_seen"],
                "seen_source_ids": sorted(seen_ids),
            }
            if on_checkpoint:
                on_checkpoint(current_checkpoint, dict(report))

        # One bounded head recheck catches listings published while the finite crawl ran.
        if all_targets_complete:
            for target in targets:
                fetched = self._fetch_with_retry(target["url"], report, allow_retry=False)
                if fetched.status_code != 200 or fetched.blocked:
                    report["coverage_status"] = "incomplete"
                    report["source_status"] = "recheck_failed"
                    report["stop_reason"] = "بازبینی محدود ابتدای نتایج کامل نشد."
                    all_targets_complete = False
                    break
                candidates, _ = self.parse_page(fetched.text)
                for candidate in candidates:
                    is_new = candidate["source_id"] not in seen_ids
                    if is_new:
                        seen_ids.add(candidate["source_id"])
                        report["new_on_recheck"] += 1
                        report["unique_received"] = len(seen_ids)
                    record, run_meta = self._enrich_candidate(candidate, criteria, ref)
                    run_meta["discovered_on_recheck"] = True
                    if is_new:
                        self._accumulate_report(report, record, run_meta)
                        if on_record:
                            on_record(record, run_meta)

        if all_targets_complete:
            report.update({
                "coverage_status": "complete_accessible_scope",
                "source_status": "completed",
                "stop_reason": "نشانگر ادامهٔ همهٔ مسیرهای مرتبط به پایان واقعی منبع رسید.",
                "can_resume": False,
            })
            current_checkpoint = {
                "target_index": len(targets),
                "cursor": None,
                "pages_traversed": report["pages_traversed"],
                "duplicates_seen": report["duplicates_seen"],
                "seen_source_ids": sorted(seen_ids),
            }
        else:
            report["can_resume"] = True

        if report["pending_model_review"]:
            report["classification_status"] = "pending_review"
        else:
            report["classification_status"] = "rules_complete"
        report["checkpoint"] = current_checkpoint
        return report

    def parse_page(self, html: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        state = self._extract_preloaded_state(html)
        if not state:
            return [], None
        nb = state.get("nb", {}) if isinstance(state, dict) else {}
        widgets = nb.get("listWidgets") or nb.get("list_widgets") or []
        pagination = nb.get("pagination") or {}
        next_cursor = None
        if isinstance(pagination, dict):
            page_data = pagination.get("data") if isinstance(pagination.get("data"), dict) else {}
            next_cursor = page_data.get("last_post_date") or pagination.get("last_post_date")
        next_cursor = next_cursor or nb.get("last_post_date")

        candidates: List[Dict[str, Any]] = []
        for widget in widgets:
            dto = (widget.get("data") or {}).get("dto") or {}
            if dto.get("widget_type") != "POST_ROW":
                continue
            data = dto.get("data") or {}
            token = data.get("token") or (((data.get("action") or {}).get("payload") or {}).get("token"))
            title = str(data.get("title") or "").strip()
            if not token or not title:
                continue
            payload = ((data.get("action") or {}).get("payload") or {})
            web_info = payload.get("web_info") if isinstance(payload.get("web_info"), dict) else {}
            bottom = str(data.get("bottom_description_text") or "")
            middle = str(data.get("middle_description_text") or "")
            top = str(data.get("top_description_text") or "")
            chips = data.get("chips") or []
            is_ladder = (
                "نردبان" in title
                or "نردبان" in bottom
                or "نردبان" in middle
                or "نردبان" in top
                or any("نردبان" in str(chip.get("text") or "") for chip in chips if isinstance(chip, dict))
                or bool(data.get("has_ladder") or data.get("is_ladder"))
            )
            district = str(web_info.get("district_persian") or "").strip()
            if not district and " در " in f" {bottom}":
                district = bottom.rsplit("در ", 1)[-1].strip()
            candidates.append({
                "token": str(token),
                "source_id": f"divar_{token}",
                "source_url": f"https://divar.ir/v/{token}",
                "title": title,
                "district": district or None,
                "middle_description": middle,
                "bottom_description": bottom,
                "structured": data,
                "structured_published_at": self._find_timestamp(data, publication=True),
                "structured_updated_at": self._find_timestamp(data, publication=False),
                "is_ladder": is_ladder,
                "raw_image": self._extract_image(data),
            })
        return candidates, str(next_cursor) if next_cursor not in (None, "") else None

    def _enrich_candidate(
        self,
        candidate: Dict[str, Any],
        criteria: AccessibleSearchCriteria,
        reference_time: datetime,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        try:
            details = self.detail_fetcher(candidate["token"]) or {}
        except Exception:
            details = {"detail_fetch_error": True}

        description = str(details.get("description") or "").strip() or None
        time_text = " ".join(
            item for item in (
                candidate.get("bottom_description"),
                details.get("time_title"),
            ) if item
        )
        is_ladder = bool(candidate.get("is_ladder") or ("نردبان" in time_text))
        publication = parse_publication_time(
            time_text,
            reference_time,
            structured_timestamp=candidate.get("structured_published_at"),
            is_ladder=is_ladder,
        )
        temporal_status = publication.membership(reference_time, criteria.window_hours)

        structured = dict(candidate.get("structured") or {})
        if details.get("is_agency_post"):
            structured["is_business"] = True

        decision = PublisherClassifier.classify(
            title=candidate["title"],
            description=description or "",
            structured=structured,
            listing_context=time_text,
            model_available=self.semantic_classifier is not None,
        )
        if is_ladder and "source:ladder_bump" not in decision.evidence:
            decision.evidence.append("source:ladder_bump")
        if decision.category == UNKNOWN and self.semantic_classifier:
            semantic, semantic_status = self._semantic_with_resilience({
                    "title": candidate["title"],
                    "description": description,
                    "structured_evidence": decision.evidence,
                })
            if semantic:
                decision = PublisherClassifier.classify(
                    title=candidate["title"],
                    description=description or "",
                    structured=structured,
                    listing_context=time_text,
                    semantic_label=semantic.get("category"),
                    semantic_confidence=semantic.get("confidence"),
                    model_available=True,
                )
            else:
                decision.model_status = "pending"
                decision.evidence.append(f"semantic_model:{semantic_status}")

        combined = " ".join(filter(None, [
            candidate.get("title"),
            candidate.get("middle_description"),
            candidate.get("bottom_description"),
            description,
        ]))
        area = details.get("area") or parse_area(combined)
        area = float(area) if area and float(area) > 0 else None
        rooms = details.get("rooms")
        if rooms is None:
            rooms = self._extract_rooms(combined)
        rooms = int(rooms) if rooms is not None else None

        deal_type = criteria.deal_type
        total_price = details.get("total_price") if deal_type == "sale" else None
        deposit = details.get("deposit") if deal_type == "rent" else None
        monthly_rent = details.get("monthly_rent") if deal_type == "rent" else None
        total_price = int(total_price) if total_price is not None else None
        deposit = int(deposit) if deposit is not None else None
        monthly_rent = int(monthly_rent) if monthly_rent is not None else None

        raw_images = details.get("images") or []
        images = list(raw_images) if isinstance(raw_images, (list, tuple)) else []
        raw_image = candidate.get("raw_image")
        if raw_image and raw_image not in images:
            images.insert(0, raw_image)

        record = {
            "source": "divar",
            "source_id": candidate["source_id"],
            "source_url": candidate["source_url"],
            "title": candidate["title"],
            "description": description,
            "city": "تهران" if criteria.city == "tehran" else criteria.city,
            "district": candidate.get("district"),
            "deal_type": deal_type,
            "property_type": criteria.property_type,
            "area": area,
            "rooms": rooms,
            "total_price": total_price,
            "deposit": deposit,
            "monthly_rent": monthly_rent,
            "has_parking": details.get("has_parking") if "has_parking" in details else None,
            "has_elevator": details.get("has_elevator") if "has_elevator" in details else None,
            "has_warehouse": details.get("has_warehouse") if "has_warehouse" in details else None,
            "has_balcony": details.get("has_balcony") if "has_balcony" in details else None,
            "features": list(details.get("features") or []) if isinstance(details.get("features"), (list, tuple)) else [],
            "images": images,
            "published_at": publication.estimated_at,
            "publication_earliest_at": publication.earliest_at,
            "publication_latest_at": publication.latest_at,
            "publication_accuracy": publication.accuracy,
            "publication_source_text": publication.source_text,
            "source_updated_at": self._to_datetime(candidate.get("structured_updated_at")),
            "publisher_category": decision.category,
            "publisher_confidence": decision.confidence,
            "publisher_reason": decision.reason,
            "publisher_evidence": decision.evidence,
            "publisher_classifier_version": decision.classifier_version,
            "publisher_checked_at": self._to_datetime(decision.checked_at),
            "classification_model_status": decision.model_status,
        }
        run_meta = {
            "temporal_status": temporal_status,
            "criteria_match": self.matches_criteria(record, criteria),
            "discovered_after_reference": temporal_status == "after_reference",
            "publisher_category": decision.category,
        }
        return record, run_meta

    def _semantic_with_resilience(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """Bound retries/time and temporarily sideline a repeatedly failing model."""
        if not self.semantic_classifier:
            return None, "unavailable"
        now = time.monotonic()
        if now < self._semantic_circuit_open_until:
            return None, "circuit_open"

        status = "failed"
        for attempt in range(self.semantic_retry_limit + 1):
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="SaghfPublisherSemantic")
            future = pool.submit(self.semantic_classifier, payload)
            try:
                result = future.result(timeout=self.semantic_timeout_seconds)
                if isinstance(result, dict):
                    self._semantic_failures = 0
                    return result, "completed"
                status = "invalid_response"
            except FutureTimeoutError:
                future.cancel()
                status = "timeout"
            except Exception:
                status = "failed"
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            if attempt < self.semantic_retry_limit:
                time.sleep(min(1.0, 0.2 * (2 ** attempt)))

        self._semantic_failures += 1
        if self._semantic_failures >= 2:
            self._semantic_circuit_open_until = time.monotonic() + 60.0
            status = "circuit_open"
        return None, status

    @staticmethod
    def matches_criteria(record: Dict[str, Any], criteria: AccessibleSearchCriteria) -> bool:
        if record.get("deal_type") != criteria.deal_type:
            return False
        if criteria.districts:
            district = str(record.get("district") or "")
            title = str(record.get("title") or "")
            if not any(str(item) in district or str(item) in title for item in criteria.districts):
                return False
        if criteria.property_type and record.get("property_type") != criteria.property_type:
            return False
        area = record.get("area")
        if criteria.min_area is not None and (area is None or area < criteria.min_area):
            return False
        if criteria.max_area is not None and (area is None or area > criteria.max_area):
            return False
        if criteria.rooms is not None and record.get("rooms") != criteria.rooms:
            return False
        if criteria.deal_type == "sale":
            price = record.get("total_price")
            if criteria.min_price is not None and (price is None or price < criteria.min_price):
                return False
            if criteria.max_price is not None and (price is None or price > criteria.max_price):
                return False
        else:
            deposit = record.get("deposit")
            rent = record.get("monthly_rent")
            if criteria.min_deposit is not None and (deposit is None or deposit < criteria.min_deposit):
                return False
            if criteria.max_deposit is not None and (deposit is None or deposit > criteria.max_deposit):
                return False
            if criteria.min_rent is not None and (rent is None or rent < criteria.min_rent):
                return False
            if criteria.max_rent is not None and (rent is None or rent > criteria.max_rent):
                return False
        for key in ("has_parking", "has_elevator", "has_warehouse", "has_balcony"):
            if getattr(criteria, key) is True and record.get(key) is not True:
                return False
        return True

    def _build_targets(self, criteria: AccessibleSearchCriteria) -> List[Dict[str, str]]:
        category_map = {
            ("sale", "apartment"): "buy-apartment",
            ("rent", "apartment"): "rent-apartment",
            ("sale", "villa"): "buy-residential",
            ("rent", "villa"): "rent-residential",
            ("sale", "commercial"): "commercial-sell",
            ("rent", "commercial"): "commercial-rent",
        }
        category = category_map.get((criteria.deal_type, criteria.property_type))
        if not category:
            category = "buy-apartment" if criteria.deal_type == "sale" else "rent-apartment"

        params: List[Tuple[str, str]] = []
        if criteria.min_area is not None or criteria.max_area is not None:
            params.append(("size", f"{int(criteria.min_area or 0)}-{int(criteria.max_area or '') if criteria.max_area is not None else ''}"))
        if criteria.rooms is not None:
            params.append(("rooms", str(criteria.rooms)))
        if criteria.deal_type == "sale" and (criteria.min_price is not None or criteria.max_price is not None):
            params.append(("price", f"{criteria.min_price or 0}-{criteria.max_price or ''}"))
        if criteria.deal_type == "rent":
            if criteria.min_deposit is not None or criteria.max_deposit is not None:
                params.append(("credit", f"{criteria.min_deposit or 0}-{criteria.max_deposit or ''}"))
            if criteria.min_rent is not None or criteria.max_rent is not None:
                params.append(("rent", f"{criteria.min_rent or 0}-{criteria.max_rent or ''}"))
        for key in ("has-parking", "has-elevator", "has-warehouse"):
            attr = key.replace("-", "_")
            if getattr(criteria, attr, None) is True:
                params.append((key, "true"))

        targets: List[Dict[str, str]] = []
        districts = criteria.districts or [""]
        for district in districts:
            slug = get_divar_slug_for_district(district) if district else None
            path = f"{self.BASE_URL}/{criteria.city}/{category}"
            if slug:
                path += f"/{slug}"
            elif district:
                params_for_target = params + [("q", district)]
                query = urlencode(params_for_target)
                targets.append({"district": district, "category": category, "url": f"{path}?{query}"})
                continue
            query = urlencode(params)
            targets.append({
                "district": district,
                "category": category,
                "url": f"{path}?{query}" if query else path,
            })
        return targets

    def _fetch_with_retry(
        self,
        url: str,
        report: Dict[str, Any],
        allow_retry: bool = True,
    ) -> PageFetchResult:
        attempts = self.SOURCE_RETRY_LIMIT + 1 if allow_retry else 1
        last = PageFetchResult(status_code=0, error="خطای نامشخص منبع")
        for attempt in range(attempts):
            last = self.page_fetcher(url)
            if last.status_code == 200 or last.blocked or last.status_code in {401, 403, 429}:
                return last
            if attempt + 1 < attempts:
                report["source_retries"] += 1
                time.sleep(min(3.0, 0.5 * (2 ** attempt)))
        return last

    def _fetch_page(self, url: str) -> PageFetchResult:
        try:
            response = self.session.get(url, timeout=(4, 12), allow_redirects=True)
            text = response.text or ""
            lower = text.lower()
            # The normal Divar bundle may contain the word "captcha" in JS.
            # Treat it as a challenge only when the usable state is absent and
            # the response carries an actual challenge marker.
            has_search_state = "window.__preloaded_state__" in lower
            challenge_marker = any(marker in lower for marker in (
                "g-recaptcha", "hcaptcha", "cf-chl-captcha", "access denied",
                "برای ادامه کپچا", "تأیید کنید ربات نیستید", "verify you are human",
            ))
            blocked = response.status_code in {401, 403, 429} or (
                challenge_marker and not has_search_state
            )
            retry_after = None
            if response.headers.get("Retry-After"):
                try:
                    retry_after = float(response.headers["Retry-After"])
                except ValueError:
                    retry_after = None
            return PageFetchResult(
                status_code=response.status_code,
                text=text,
                blocked=blocked,
                retry_after=retry_after,
                error=("محدودیت دسترسی یا کپچا از سوی منبع" if blocked else None),
            )
        except requests.RequestException as exc:
            return PageFetchResult(status_code=0, error=f"خطای شبکه: {type(exc).__name__}")

    @staticmethod
    def _with_cursor(base_url: str, cursor: Optional[str], page: int) -> str:
        if not cursor:
            return base_url
        parts = urlsplit(base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["last-post-date"] = str(cursor)
        query["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    @staticmethod
    def _extract_preloaded_state(html: str) -> Optional[Dict[str, Any]]:
        marker = "window.__PRELOADED_STATE__"
        start = str(html or "").find(marker)
        if start < 0:
            return None
        equals = html.find("=", start + len(marker))
        if equals < 0:
            return None
        payload = DivarAccessibleSearchCrawler._balanced_json(html, equals + 1)
        if not payload:
            return None
        try:
            value = json.loads(payload)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _balanced_json(text: str, start: int) -> Optional[str]:
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text) or text[start] not in "[{":
            return None
        opening = text[start]
        closing = "}" if opening == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    @staticmethod
    def _extract_image(data: Dict[str, Any]) -> Optional[str]:
        image = data.get("image")
        url = data.get("image_url")
        if not url and isinstance(image, dict):
            url = image.get("url")
        if not url:
            images = data.get("images")
            if isinstance(images, list) and images:
                first = images[0]
                url = first if isinstance(first, str) else None
        return str(url) if isinstance(url, str) and url.startswith(("https://", "http://")) else None

    @staticmethod
    def _find_timestamp(data: Any, publication: bool) -> Any:
        keys = (
            {"published_at", "publish_time", "publication_time", "created_at", "post_date"}
            if publication else
            {"updated_at", "update_time", "last_update", "modified_at"}
        )
        if isinstance(data, dict):
            for key, value in data.items():
                if str(key).lower() in keys and value not in (None, ""):
                    return value
            for value in data.values():
                if isinstance(value, (dict, list)):
                    found = DivarAccessibleSearchCrawler._find_timestamp(value, publication)
                    if found not in (None, ""):
                        return found
        elif isinstance(data, list):
            for value in data:
                found = DivarAccessibleSearchCrawler._find_timestamp(value, publication)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _extract_rooms(text: str) -> Optional[int]:
        normalized = persian_to_english_numbers(text or "")
        match = re.search(r"(\d+)\s*(?:خواب|خوابه|اتاق)", normalized)
        if match:
            return int(match.group(1))
        words = {"بدون اتاق": 0, "تک خواب": 1, "یک خواب": 1, "دو خواب": 2, "سه خواب": 3, "چهار خواب": 4}
        for marker, value in words.items():
            if marker in normalized:
                return value
        return None

    @staticmethod
    def _to_datetime(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        try:
            if isinstance(value, datetime):
                return _naive_utc(value)
            if isinstance(value, (int, float)) or str(value).isdigit():
                numeric = float(value)
                if numeric > 10_000_000_000:
                    numeric /= 1000
                return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None)
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return _naive_utc(parsed)
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _accumulate_report(report: Dict[str, Any], record: Dict[str, Any], meta: Dict[str, Any]) -> None:
        temporal = meta["temporal_status"]
        if temporal == "inside":
            report["within_window"] += 1
        elif temporal == "outside":
            report["outside_window"] += 1
        elif temporal == "after_reference":
            report["after_reference"] += 1
        else:
            report["uncertain_time"] += 1
        if meta["criteria_match"]:
            report["criteria_matched"] += 1
        category = record["publisher_category"]
        report[category] = report.get(category, 0) + 1
        if record.get("classification_model_status") == "pending":
            report["pending_model_review"] += 1


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
