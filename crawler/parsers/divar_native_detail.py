"""Parse native detail widgets without inventing missing property values."""
import re
from datetime import timedelta, timezone
from urllib.parse import urlsplit

from crawler.contact_extractor import ContactExtractor
from crawler.schemas import parse_price


def parse_original_publication(text):
    """Only the source's explicit original-publication label, never ladder time."""
    text = ContactExtractor.normalize_persian_digits(str(text or ""))
    match = re.search(r"^\s*انتشار\s+آگهی\s*:\s*(\d{1,2})\s+([آ-ی]+)\s+(\d{4})[،,]\s*(\d{1,2}):(\d{2})\s*$", text, re.MULTILINE)
    if not match:
        return None
    months = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
    try:
        import jdatetime
        day, month, year, hour, minute = match.groups()
        published = jdatetime.datetime(int(year), months.index(month) + 1, int(day), int(hour), int(minute)).togregorian()
        # Iran's documented modern timezone; reject historic dates rather than
        # applying its current UTC offset to older DST regimes.
        if not 1402 <= int(year) <= 1500:
            return None
        earliest = published.replace(tzinfo=timezone(timedelta(hours=3, minutes=30))).astimezone(timezone.utc)
        latest = earliest + timedelta(minutes=1) - timedelta(microseconds=1)
        return {"earliest": earliest.isoformat(), "latest": latest.isoformat(),
                "accuracy": "source_minute", "source": "native_original_publication_label"}
    except (ImportError, ValueError, OverflowError):
        return None


def parse_native_detail(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
        raise ValueError("unverified_detail_payload")
    result = {"images": [], "features": [], "detail_source": "authenticated_native_api"}
    if payload.get("_saghf_cached_detail"):
        result["detail_source"] = "authenticated_native_api_cached"
    web = payload.get("webengage") or {}
    business = web.get("business_type") if isinstance(web, dict) else None
    if business:
        result["business_type"] = str(business)
        result["is_agency_post"] = str(business).lower() not in {"personal", "owner"}

    def image(url):
        if not isinstance(url, str):
            return
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and (host == "divarcdn.com" or host.endswith(".divarcdn.com")) and url not in result["images"]:
            result["images"].append(url)

    def number(value):
        raw = ContactExtractor.normalize_persian_digits(str(value or ""))
        match = re.search(r"\d+(?:\.\d+)?", raw.replace(",", "").replace("٬", ""))
        return float(match.group()) if match else None

    for section in payload["sections"]:
        if not isinstance(section, dict):
            continue
        for widget in section.get("widgets") or []:
            if not isinstance(widget, dict):
                continue
            kind = widget.get("widget_type", "")
            data = widget.get("data") or {}
            if not isinstance(data, dict):
                continue
            if kind == "EXPANDABLE_SECTION":
                # Native metadata is nested separately from the advertiser's
                # top-level description. Do not parse dates from user prose.
                for child in data.get("widget_list") or []:
                    if isinstance(child, dict) and child.get("widget_type") == "DESCRIPTION_ROW":
                        child_data = child.get("data") or {}
                        evidence = parse_original_publication(child_data.get("text")) if isinstance(child_data, dict) else None
                        if evidence:
                            if result.get("original_publication") and result["original_publication"] != evidence:
                                result["original_publication_conflict"] = True
                            result["original_publication"] = evidence
            if kind == "DESCRIPTION_ROW" and isinstance(data.get("text"), str):
                result["description"] = data["text"].strip()
            elif kind == "LAZY_SECTION":
                business = (data.get("request_data") or {}).get("post_business_type")
                if business and business not in {"personal", "owner"}:
                    result["is_agency_post"] = True
            elif "IMAGE" in kind:
                for item in data.get("items") or []:
                    if isinstance(item, dict):
                        image((item.get("image") or {}).get("url") or item.get("url"))
                    elif isinstance(item, str):
                        image(item)
            elif kind == "GROUP_INFO_ROW":
                for item in data.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    label = str(item.get("title") or "")
                    value = number(item.get("value"))
                    if value is None:
                        continue
                    if "متراژ" in label and value > 0:
                        result["area"] = value
                    elif "اتاق" in label:
                        result["rooms"] = int(value)
            elif kind in {"UNEXPANDABLE_ROW", "LIST_DATA_ROW"}:
                label = str(data.get("title") or "")
                raw = str(data.get("value") or "")
                if number(raw) is None:
                    continue
                amount = parse_price(raw)
                if "ودیعه" in label or "رهن" in label:
                    result["deposit"] = amount
                elif "اجاره" in label:
                    result["monthly_rent"] = amount
                elif "قیمت کل" in label:
                    result["total_price"] = amount
            elif kind == "GROUP_FEATURE_ROW":
                for item in data.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    label = str(item.get("title") or "")
                    available = item.get("available")
                    if not isinstance(available, bool):
                        continue
                    for text, key in [("پارکینگ", "has_parking"), ("آسانسور", "has_elevator"), ("انباری", "has_warehouse"), ("بالکن", "has_balcony"), ("تراس", "has_balcony")]:
                        if text in label:
                            result[key] = available and "ندارد" not in label
                    if available and label:
                        result["features"].append(label)
    for item in payload.get("web_images") or []:
        image((item.get("src") or item.get("url")) if isinstance(item, dict) else item)
    seo = payload.get("seo") or {}
    schema = seo.get("post_seo_schema") or {} if isinstance(seo, dict) else {}
    if isinstance(schema, dict):
        urls = schema.get("image") or []
        for url in urls if isinstance(urls, list) else [urls]:
            image(url)
    if result.get("original_publication_conflict"):
        result.pop("original_publication", None)
    return result
