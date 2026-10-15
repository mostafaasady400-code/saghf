"""Shared 24-hour accessible search entry point for Telegram and Bale."""

from __future__ import annotations

import html
from typing import Any, Dict, List

from services.search_run_service import SearchRunService


def criteria_from_wizard(session: Dict[str, Any]) -> Dict[str, Any]:
    district = str(session.get("district") or "").strip()
    if district == "منطقه ۵":
        district = ""
    prop_type = session.get("prop_type")
    if prop_type in (None, "all", "residential"):
        prop_type = "apartment"
    criteria = {
        "city": "tehran",
        "districts": [district] if district else [],
        "deal_type": session.get("deal_type"),
        "property_type": prop_type,
        "window_hours": 24,
    }
    for key in (
        "min_price", "max_price", "min_deposit", "max_deposit",
        "min_rent", "max_rent", "min_area", "max_area", "rooms",
        "has_parking", "has_elevator", "has_warehouse", "has_balcony",
    ):
        value = session.get(key)
        if value not in (None, "", 0, "0", False):
            criteria[key] = value
    return criteria


def execute_wizard_search(session: Dict[str, Any], max_runtime_seconds: float = 120) -> Dict[str, Any]:
    """Run the same core used by web; caller must provide a Flask app context."""
    criteria = criteria_from_wizard(session)
    run = SearchRunService.create_run(criteria, query_text="جست‌وجوی ویزارد پیام‌رسان")
    run = SearchRunService.execute(run.run_id, max_runtime_seconds=max_runtime_seconds)
    page = SearchRunService.paginated_results(run.run_id, section="main", page=1, per_page=8)
    return {
        "run": run.to_dict(),
        "page": page,
        "messages": [format_listing(item) for item in page["items"]],
        "results_path": f"/crawler/search-runs/{run.run_id}/view",
    }


def format_listing(item: Dict[str, Any]) -> str:
    title = html.escape(str(item.get("title") or "آگهی بدون عنوان"))
    district = html.escape(str(item.get("district") or "نامشخص"))
    reason = html.escape(str(item.get("publisher_reason") or "شواهد مالک مستقیم"))
    source_url = html.escape(str(item.get("source_url") or ""), quote=True)
    area = item.get("area") if item.get("area") is not None else "نامشخص"
    rooms = item.get("rooms") if item.get("rooms") is not None else "نامشخص"
    publication = html.escape(str(item.get("publication_source_text") or item.get("published_at") or "نامشخص"))
    return (
        f"🏠 <b>{title}</b>\n"
        f"📍 {district} | 📐 {area} متر | 🛏 {rooms}\n"
        f"🕒 انتشار: {publication}\n"
        f"👤 دلیل احتمال مالک: {reason}\n"
        f"🔗 <a href=\"{source_url}\">لینک آگهی</a>"
    )


def format_summary(result: Dict[str, Any]) -> str:
    run = result["run"]
    pagination = result["page"]["pagination"]
    report = run.get("report") or {}
    return (
        "✅ <b>پیمایش محدود و قابل‌دسترسی پایان یافت.</b>\n"
        f"نتایج مالک احتمالی: <b>{pagination['total']}</b> | "
        f"یکتای دریافت‌شده: <b>{report.get('unique_received', 0)}</b>\n"
        f"پوشش: <code>{html.escape(str(run.get('coverage_status')))}</code>\n"
        f"علت توقف: {html.escape(str(run.get('stop_reason') or 'نامشخص'))}\n"
        f"همهٔ صفحات و بخش بررسی: <code>{result['results_path']}</code>\n"
        "این برچسب «احتمال بالای مالک» است، نه تأیید حقوقی مالکیت."
    )
