"""Publication-time parsing with explicit uncertainty for Divar listings."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from crawler.contact_extractor import ContactExtractor
from crawler.owner_filter import clean_persian_text


try:
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except ZoneInfoNotFoundError:
    # Windows images may not ship the IANA database. Iran currently observes
    # UTC+03:30 without DST; keep the crawler usable without a new dependency.
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30), name="Asia/Tehran")


@dataclass
class PublicationWindow:
    estimated_at: Optional[datetime]
    earliest_at: Optional[datetime]
    latest_at: Optional[datetime]
    accuracy: str
    source_text: str

    def membership(self, reference_time: datetime, hours: int = 24) -> str:
        ref = _aware_utc(reference_time)
        boundary = ref - timedelta(hours=hours)
        if self.earliest_at and _aware_utc(self.earliest_at) > ref:
            return "after_reference"
        if self.latest_at and _aware_utc(self.latest_at) < boundary:
            return "outside"
        if (
            self.earliest_at
            and self.latest_at
            and _aware_utc(self.earliest_at) >= boundary
            and _aware_utc(self.latest_at) <= ref
        ):
            return "inside"
        return "uncertain"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key in ("estimated_at", "earliest_at", "latest_at"):
            value = data[key]
            data[key] = value.isoformat() if value else None
        return data


def parse_publication_time(
    text: str,
    reference_time: datetime,
    structured_timestamp: Any = None,
    is_ladder: bool = False,
) -> PublicationWindow:
    ref = _aware_utc(reference_time)
    exact = _parse_structured_timestamp(structured_timestamp)

    raw = str(text or "").strip()
    norm = clean_persian_text(ContactExtractor.normalize_persian_digits(raw))
    has_ladder = is_ladder or ("نردبان" in norm)

    if exact:
        accuracy = "exact_with_ladder" if has_ladder else "exact"
        return PublicationWindow(exact, exact, exact, accuracy, "structured_timestamp")

    if has_ladder:
        # نردبان انتشار جدید نیست؛ زمان متنی فقط نشان‌دهندهٔ لحظهٔ ارتقای آگهی است.
        # در نبود زمان ساختاریافتهٔ اولیه، زمان انتشار نامشخص باقی می‌ماند تا به‌اشتباه تازه فرض نشود.
        return PublicationWindow(None, None, None, "ladder_bump_unknown", raw)

    if any(marker in norm for marker in ("لحظاتی پیش", "همین الان", "چند لحظه پیش")):
        return _relative_window(ref, minutes=2, uncertainty_minutes=3, source=raw, accuracy="approx_minute")
    if "دقایقی پیش" in norm:
        return _relative_window(ref, minutes=5, uncertainty_minutes=5, source=raw, accuracy="approx_minute")
    if "یک ربع پیش" in norm:
        return _relative_window(ref, minutes=15, uncertainty_minutes=3, source=raw, accuracy="approx_minute")
    if "نیم ساعت پیش" in norm:
        return _relative_window(ref, minutes=30, uncertainty_minutes=5, source=raw, accuracy="approx_minute")

    minute_match = re.search(r"(\d+)\s*دقیقه\s*پیش", norm)
    if minute_match:
        return _relative_window(
            ref,
            minutes=int(minute_match.group(1)),
            uncertainty_minutes=2,
            source=raw,
            accuracy="approx_minute",
        )

    hour_match = re.search(r"(\d+)\s*ساعت\s*پیش", norm)
    if hour_match:
        hours = int(hour_match.group(1))
        return _relative_window(
            ref,
            minutes=hours * 60,
            uncertainty_minutes=30,
            source=raw,
            accuracy="approx_hour",
        )
    if "یک ساعت پیش" in norm:
        return _relative_window(ref, minutes=60, uncertainty_minutes=30, source=raw, accuracy="approx_hour")

    if "امروز" in norm:
        local_ref = ref.astimezone(TEHRAN_TZ)
        start_local = local_ref.replace(hour=0, minute=0, second=0, microsecond=0)
        return PublicationWindow(
            estimated_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            earliest_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            latest_at=ref.replace(tzinfo=None),
            accuracy="day_range",
            source_text=raw,
        )

    if "دیروز" in norm or re.search(r"(?:^|\s)۱\s*روز\s*پیش", norm):
        local_ref = ref.astimezone(TEHRAN_TZ)
        yesterday = local_ref.date() - timedelta(days=1)
        start_local = datetime.combine(yesterday, datetime.min.time(), tzinfo=TEHRAN_TZ)
        end_local = datetime.combine(yesterday, datetime.max.time(), tzinfo=TEHRAN_TZ)
        return PublicationWindow(
            estimated_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            earliest_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            latest_at=end_local.astimezone(timezone.utc).replace(tzinfo=None),
            accuracy="day_range",
            source_text=raw,
        )

    day_match = re.search(r"(\d+)\s*روز\s*پیش", norm)
    if day_match:
        days = int(day_match.group(1))
        local_ref = ref.astimezone(TEHRAN_TZ)
        target_date = local_ref.date() - timedelta(days=days)
        start_local = datetime.combine(target_date, datetime.min.time(), tzinfo=TEHRAN_TZ)
        end_local = datetime.combine(target_date, datetime.max.time(), tzinfo=TEHRAN_TZ)
        return PublicationWindow(
            estimated_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            earliest_at=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            latest_at=end_local.astimezone(timezone.utc).replace(tzinfo=None),
            accuracy="day_range",
            source_text=raw,
        )

    return PublicationWindow(None, None, None, "unknown", raw)


def _relative_window(
    ref: datetime,
    *,
    minutes: int,
    uncertainty_minutes: int,
    source: str,
    accuracy: str,
) -> PublicationWindow:
    estimate = ref - timedelta(minutes=minutes)
    earliest = estimate - timedelta(minutes=uncertainty_minutes)
    latest = min(ref, estimate + timedelta(minutes=uncertainty_minutes))
    return PublicationWindow(
        estimated_at=estimate.replace(tzinfo=None),
        earliest_at=earliest.replace(tzinfo=None),
        latest_at=latest.replace(tzinfo=None),
        accuracy=accuracy,
        source_text=source,
    )


def _parse_structured_timestamp(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _aware_utc(parsed).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
