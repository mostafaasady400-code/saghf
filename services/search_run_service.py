"""Persistence, resume and pagination for auditable 24-hour searches."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, or_, func

from crawler.divar_accessible_search import AccessibleSearchCriteria, DivarAccessibleSearchCrawler
from crawler.publisher_classifier import (
    EXPLICIT_AGENCY,
    LIKELY_INTERMEDIARY,
    LIKELY_OWNER,
    UNKNOWN,
)
from database.db import db
from database.models import (
    AccessibleListing,
    ListingRevision,
    Property,
    PublisherClassificationCorrection,
    SearchRun,
    SearchRunItem,
)


class SearchRunService:
    VALID_CATEGORIES = {EXPLICIT_AGENCY, LIKELY_INTERMEDIARY, LIKELY_OWNER, UNKNOWN}

    @classmethod
    def create_run(
        cls,
        criteria: Dict[str, Any],
        query_text: str = "",
        reference_time: Optional[datetime] = None,
    ) -> SearchRun:
        parsed = AccessibleSearchCriteria.from_dict(criteria)
        if parsed.deal_type not in {"sale", "rent"}:
            raise ValueError("برای شروع جست‌وجو، نوع معامله (خرید یا رهن و اجاره) باید مشخص باشد.")
        ref = cls._naive_utc(reference_time or datetime.now(timezone.utc))
        run = SearchRun(
            run_id=uuid.uuid4().hex,
            query_text=(query_text or "").strip(),
            reference_time=ref,
            window_start=ref - timedelta(hours=parsed.window_hours),
            status="pending",
            coverage_status="unknown",
            source_status="not_started",
            classification_status="pending",
            can_resume=True,
        )
        run.criteria = parsed.to_dict()
        db.session.add(run)
        db.session.commit()
        return run

    @classmethod
    def execute(
        cls,
        run_id: str,
        crawler: Optional[DivarAccessibleSearchCrawler] = None,
        max_runtime_seconds: float = 180.0,
        chunk_runtime_seconds: Optional[float] = None,
        auto_continue: bool = False,
    ) -> SearchRun:
        if auto_continue and chunk_runtime_seconds and chunk_runtime_seconds < max_runtime_seconds:
            start_monotonic = time.monotonic()
            run = SearchRun.query.filter_by(run_id=run_id).first()
            while True:
                elapsed = time.monotonic() - start_monotonic
                remaining = max_runtime_seconds - elapsed
                if remaining <= 1.0:
                    break
                budget = min(remaining, chunk_runtime_seconds)
                run = cls._execute_single_leg(run_id, crawler=crawler, max_runtime_seconds=budget)
                if not (run.can_resume and run.source_status == "time_budget_reached"):
                    break
            return run
        return cls._execute_single_leg(run_id, crawler=crawler, max_runtime_seconds=max_runtime_seconds)

    @classmethod
    def _execute_single_leg(
        cls,
        run_id: str,
        crawler: Optional[DivarAccessibleSearchCrawler] = None,
        max_runtime_seconds: float = 180.0,
    ) -> SearchRun:
        run = SearchRun.query.filter_by(run_id=run_id).first()
        if not run:
            raise ValueError("اجرای جست‌وجو پیدا نشد.")
        if run.status == "running":
            return run

        run.status = "running"
        run.source_status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        run.completed_at = None
        db.session.commit()

        if crawler is not None:
            search_crawler = crawler
        else:
            from services.publisher_semantic_service import get_configured_publisher_classifier
            search_crawler = DivarAccessibleSearchCrawler(
                semantic_classifier=get_configured_publisher_classifier(),
            )
        criteria = AccessibleSearchCriteria.from_dict(run.criteria)

        # تجمیع رکوردهای پایدار قبلی در دیتابیس برای تضمین پیشگیری کامل از داده‌های تکراری
        checkpoint = dict(run.checkpoint or {})
        persisted_items = SearchRunItem.query.filter_by(run_id=run.run_id).all()
        if persisted_items:
            persisted_listing_ids = [item.listing_id for item in persisted_items]
            persisted_source_ids = {
                l.source_id for l in AccessibleListing.query.filter(AccessibleListing.id.in_(persisted_listing_ids)).all()
                if l.source_id
            }
            existing_seen = set(checkpoint.get("seen_source_ids") or [])
            checkpoint["seen_source_ids"] = sorted(existing_seen.union(persisted_source_ids))

        def persist_record(record: Dict[str, Any], meta: Dict[str, Any]) -> None:
            listing = cls._upsert_listing(record)
            link = SearchRunItem.query.filter_by(run_id=run.run_id, listing_id=listing.id).first()
            if not link:
                link = SearchRunItem(run_id=run.run_id, listing_id=listing.id)
                db.session.add(link)
            link.temporal_status = meta.get("temporal_status") or "uncertain"
            link.criteria_match = bool(meta.get("criteria_match"))
            link.discovered_after_reference = bool(meta.get("discovered_after_reference"))
            link.publisher_category_snapshot = record.get("publisher_category") or UNKNOWN

            if (
                link.temporal_status == "inside"
                and link.criteria_match
                and listing.effective_publisher_category == LIKELY_OWNER
            ):
                cls._sync_main_result_to_property(listing)
            db.session.commit()

        def persist_checkpoint(checkpoint: Dict[str, Any], partial_report: Dict[str, Any]) -> None:
            current = SearchRun.query.filter_by(run_id=run.run_id).first()
            current.checkpoint = checkpoint
            current.report = partial_report
            current.coverage_status = partial_report.get("coverage_status") or "unknown"
            current.source_status = partial_report.get("source_status") or "running"
            db.session.commit()

        try:
            report = search_crawler.crawl(
                criteria,
                reference_time=run.reference_time,
                checkpoint=checkpoint,
                max_runtime_seconds=max_runtime_seconds,
                on_record=persist_record,
                on_checkpoint=persist_checkpoint,
            )
            run = SearchRun.query.filter_by(run_id=run.run_id).first()
            cls._merge_persisted_counts(run.run_id, report)
            report["main_results"] = cls._count_section(run.run_id, "main")
            report["review_results"] = cls._count_section(run.run_id, "review")
            run.report = report
            run.checkpoint = report.get("checkpoint") or run.checkpoint
            run.coverage_status = report.get("coverage_status") or "unknown"
            run.source_status = report.get("source_status") or "unknown"
            run.classification_status = report.get("classification_status") or "pending"
            run.stop_reason = report.get("stop_reason")
            run.can_resume = bool(report.get("can_resume"))
            run.status = "completed" if not run.can_resume else "interrupted"
            run.completed_at = datetime.utcnow()
            db.session.commit()
            return run
        except Exception as exc:
            db.session.rollback()
            run = SearchRun.query.filter_by(run_id=run_id).first()
            run.status = "failed"
            run.coverage_status = "incomplete"
            run.source_status = "internal_error"
            run.stop_reason = f"خطای داخلی کنترل‌شده: {type(exc).__name__}"
            run.can_resume = True
            run.completed_at = datetime.utcnow()
            db.session.commit()
            raise

    @classmethod
    def execute_async(
        cls,
        app,
        run_id: str,
        max_runtime_seconds: float = 180.0,
        chunk_runtime_seconds: float = 20.0,
        auto_continue: bool = True,
    ) -> None:
        def worker():
            with app.app_context():
                start_monotonic = time.monotonic()
                try:
                    while True:
                        run = SearchRun.query.filter_by(run_id=run_id).first()
                        if not run or run.status == "failed":
                            break
                        elapsed = time.monotonic() - start_monotonic
                        remaining = max_runtime_seconds - elapsed
                        if remaining <= 1.0:
                            break
                        budget = min(remaining, chunk_runtime_seconds)
                        cls.execute(run_id, max_runtime_seconds=budget)

                        run = SearchRun.query.filter_by(run_id=run_id).first()
                        if not (auto_continue and run and run.can_resume and run.source_status == "time_budget_reached"):
                            break
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            name=f"SaghfSearchRun-{run_id[:8]}",
            daemon=True,
        ).start()

    @classmethod
    def paginated_results(
        cls,
        run_id: str,
        *,
        section: str = "main",
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        run = SearchRun.query.filter_by(run_id=run_id).first()
        if not run:
            raise ValueError("اجرای جست‌وجو پیدا نشد.")
        page = max(1, int(page or 1))
        per_page = min(100, max(1, int(per_page or 20)))
        query = cls._section_query(run_id, section)
        total = query.count()
        rows = (
            query.order_by(AccessibleListing.published_at.desc(), AccessibleListing.first_seen_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        items = []
        for listing, run_item in rows:
            item = listing.to_dict()
            item.update({
                "temporal_status": run_item.temporal_status,
                "criteria_match": run_item.criteria_match,
                "discovered_after_reference": run_item.discovered_after_reference,
            })
            items.append(item)
        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "run": run.to_dict(),
            "section": section,
            "items": items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_prev": page > 1,
                "has_next": page < total_pages,
            },
        }

    @classmethod
    def apply_manual_correction(
        cls,
        listing_id: int,
        corrected_category: str,
        reason: str,
        reviewer: Optional[str] = None,
    ) -> AccessibleListing:
        if corrected_category not in cls.VALID_CATEGORIES:
            raise ValueError("دستهٔ اصلاحی نامعتبر است.")
        if not (reason or "").strip():
            raise ValueError("دلیل اصلاح دستی الزامی است.")
        listing = db.session.get(AccessibleListing, listing_id)
        if not listing:
            raise ValueError("آگهی پیدا نشد.")
        previous = listing.effective_publisher_category
        correction = PublisherClassificationCorrection(
            listing_id=listing.id,
            previous_category=previous,
            corrected_category=corrected_category,
            reason=reason.strip(),
            reviewer=(reviewer or "").strip() or None,
        )
        listing.manual_publisher_category = corrected_category
        listing.manual_review_reason = reason.strip()
        listing.manual_reviewed_at = datetime.utcnow()
        db.session.add(correction)
        if corrected_category == LIKELY_OWNER:
            cls._sync_main_result_to_property(listing)
        else:
            legacy = Property.query.filter_by(source_id=listing.source_id).first()
            if legacy:
                legacy.is_personal_owner = False
                legacy.owner_type = "agency" if corrected_category == EXPLICIT_AGENCY else "unknown"
        db.session.commit()
        return listing

    @classmethod
    def process_pending_classifications(
        cls,
        run_id: Optional[str] = None,
        max_items: int = 50,
        classifier: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Process listings deferred in the pending queue without re-crawling."""
        from crawler.publisher_classifier import PublisherClassifier
        if classifier is None:
            from services.publisher_semantic_service import get_configured_publisher_classifier
            classifier = get_configured_publisher_classifier()
        if not classifier:
            return {
                "success": False,
                "processed": 0,
                "remaining": 0,
                "reason": "مدل معنایی یا کلید API تنظیم نشده است؛ موارد مبهم در صف باقی می‌مانند.",
            }

        query = AccessibleListing.query.filter_by(classification_model_status="pending")
        if run_id:
            query = query.join(SearchRunItem, SearchRunItem.listing_id == AccessibleListing.id).filter(
                SearchRunItem.run_id == run_id
            )

        total_pending = query.count()
        listings = query.limit(max_items).all()

        processed_count = 0
        converted_to_owner = 0
        errors = 0

        for listing in listings:
            try:
                payload = {
                    "title": listing.title,
                    "description": listing.description,
                    "structured_evidence": listing.publisher_evidence,
                }
                semantic = classifier(payload)
                if isinstance(semantic, dict) and semantic.get("category"):
                    decision = PublisherClassifier.classify(
                        title=listing.title,
                        description=listing.description or "",
                        structured={"is_business": listing.publisher_category == EXPLICIT_AGENCY},
                        listing_context=listing.publication_source_text or "",
                        semantic_label=semantic.get("category"),
                        semantic_confidence=semantic.get("confidence"),
                        model_available=True,
                    )
                    listing.publisher_category = decision.category
                    listing.publisher_confidence = decision.confidence
                    listing.publisher_reason = decision.reason
                    listing.classification_model_status = "completed"
                    listing.publisher_checked_at = datetime.utcnow()
                    evidence_list = list(listing.publisher_evidence)
                    evidence_list.extend(decision.evidence)
                    listing.publisher_evidence = list(dict.fromkeys(evidence_list))

                    if listing.effective_publisher_category == LIKELY_OWNER:
                        converted_to_owner += 1
                        cls._sync_main_result_to_property(listing)

                    for item in SearchRunItem.query.filter_by(listing_id=listing.id).all():
                        item.publisher_category_snapshot = decision.category
                    processed_count += 1
            except Exception as e:
                errors += 1
                evidence_list = list(listing.publisher_evidence)
                evidence_list.append(f"deferred_retry_error:{type(e).__name__}")
                listing.publisher_evidence = list(dict.fromkeys(evidence_list))
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "rate" in err_str:
                    break

        db.session.commit()

        if run_id:
            run = SearchRun.query.filter_by(run_id=run_id).first()
            if run:
                report = dict(run.report or {})
                cls._merge_persisted_counts(run.run_id, report)
                report["main_results"] = cls._count_section(run.run_id, "main")
                report["review_results"] = cls._count_section(run.run_id, "review")
                run.report = report
                if report.get("pending_model_review", 0) == 0:
                    run.classification_status = "completed"
                db.session.commit()

        return {
            "success": True,
            "processed": processed_count,
            "converted_to_owner": converted_to_owner,
            "errors": errors,
            "remaining": max(0, total_pending - processed_count),
        }

    @classmethod
    def _upsert_listing(cls, record: Dict[str, Any]) -> AccessibleListing:
        listing = AccessibleListing.query.filter_by(source_id=record["source_id"]).first()
        now = datetime.utcnow()
        tracked_fields = (
            "source", "source_url", "title", "description", "city", "district",
            "deal_type", "property_type", "area", "rooms", "total_price", "deposit",
            "monthly_rent", "has_parking", "has_elevator", "has_warehouse", "has_balcony",
            "published_at", "publication_earliest_at", "publication_latest_at",
            "publication_accuracy", "publication_source_text", "source_updated_at",
            "publisher_category", "publisher_confidence", "publisher_reason",
            "publisher_classifier_version", "publisher_checked_at", "classification_model_status",
        )
        new_hash = cls._content_hash(record)
        if not listing:
            listing = AccessibleListing(
                source_id=record["source_id"],
                first_seen_at=now,
            )
            db.session.add(listing)
        elif listing.content_hash and listing.content_hash != new_hash:
            changed = [
                field for field in tracked_fields
                if getattr(listing, field, None) != record.get(field)
            ]
            revision = ListingRevision(
                listing_id=listing.id,
                changed_fields_json=json.dumps(changed, ensure_ascii=False),
                snapshot_json=json.dumps(listing.to_dict(), ensure_ascii=False, default=str),
                observed_at=now,
            )
            db.session.add(revision)

        for field in tracked_fields:
            setattr(listing, field, record.get(field))
        listing.features = record.get("features") or []
        listing.images = record.get("images") or []
        listing.publisher_evidence = record.get("publisher_evidence") or []
        listing.last_seen_at = now
        listing.content_hash = new_hash
        db.session.flush()
        return listing

    @classmethod
    def _sync_main_result_to_property(cls, listing: AccessibleListing) -> None:
        if not listing.area or not listing.district:
            return
        prop = Property.query.filter_by(source_id=listing.source_id).first()
        if not prop:
            prop = Property(
                source="divar",
                source_id=listing.source_id,
                title=listing.title,
                deal_type=listing.deal_type,
                property_type=listing.property_type or "apartment",
                city=listing.city or "تهران",
                district=listing.district,
                area=listing.area,
            )
            db.session.add(prop)
        prop.source_url = listing.source_url
        prop.title = listing.title
        prop.description = listing.description
        prop.city = listing.city or "تهران"
        prop.district = listing.district
        prop.deal_type = listing.deal_type
        prop.property_type = listing.property_type or "apartment"
        prop.area = listing.area
        prop.rooms = listing.rooms
        prop.total_price = listing.total_price
        prop.deposit = listing.deposit
        prop.monthly_rent = listing.monthly_rent
        prop.has_parking = listing.has_parking
        prop.has_elevator = listing.has_elevator
        prop.has_warehouse = listing.has_warehouse
        prop.has_balcony = listing.has_balcony
        prop.status = "raw_crawled"
        prop.is_personal_owner = True
        # سازگاری با مصرف‌کننده‌های قدیمی وب/تلگرام/بله؛ دستهٔ دقیق در AccessibleListing می‌ماند.
        prop.owner_type = "personal"
        prop.filter_log = (listing.publisher_reason or "احتمال بالای مالک مستقیم")[:250]
        prop.features = listing.features
        prop.images = listing.images

    @classmethod
    def _section_query(cls, run_id: str, section: str):
        query = (
            db.session.query(AccessibleListing, SearchRunItem)
            .join(SearchRunItem, SearchRunItem.listing_id == AccessibleListing.id)
            .filter(SearchRunItem.run_id == run_id)
        )
        effective_owner = or_(
            AccessibleListing.manual_publisher_category == LIKELY_OWNER,
            and_(
                AccessibleListing.manual_publisher_category.is_(None),
                AccessibleListing.publisher_category == LIKELY_OWNER,
            ),
        )
        if section == "main":
            return query.filter(
                SearchRunItem.temporal_status == "inside",
                SearchRunItem.criteria_match.is_(True),
                effective_owner,
            )
        if section == "review":
            return query.filter(
                SearchRunItem.criteria_match.is_(True),
                SearchRunItem.temporal_status.in_(["inside", "uncertain"]),
                or_(
                    SearchRunItem.temporal_status == "uncertain",
                    AccessibleListing.classification_model_status == "pending",
                    and_(
                        AccessibleListing.manual_publisher_category.is_(None),
                        AccessibleListing.publisher_category == UNKNOWN,
                    ),
                ),
            )
        if section == "after_reference":
            return query.filter(SearchRunItem.discovered_after_reference.is_(True))
        if section == "intermediary":
            return query.filter(
                or_(
                    AccessibleListing.manual_publisher_category.in_([EXPLICIT_AGENCY, LIKELY_INTERMEDIARY]),
                    and_(
                        AccessibleListing.manual_publisher_category.is_(None),
                        AccessibleListing.publisher_category.in_([EXPLICIT_AGENCY, LIKELY_INTERMEDIARY]),
                    ),
                )
            )
        return query

    @classmethod
    def _merge_persisted_counts(cls, run_id: str, report: Dict[str, Any]) -> None:
        """Make resume reports reflect the whole persisted run, not only its last leg."""
        base = SearchRunItem.query.filter_by(run_id=run_id)
        report["unique_received"] = base.count()
        report["within_window"] = base.filter_by(temporal_status="inside").count()
        report["outside_window"] = base.filter_by(temporal_status="outside").count()
        report["uncertain_time"] = base.filter_by(temporal_status="uncertain").count()
        report["after_reference"] = base.filter_by(discovered_after_reference=True).count()
        report["criteria_matched"] = base.filter_by(criteria_match=True).count()
        grouped = dict(
            db.session.query(SearchRunItem.publisher_category_snapshot, func.count(SearchRunItem.id))
            .filter(SearchRunItem.run_id == run_id)
            .group_by(SearchRunItem.publisher_category_snapshot)
            .all()
        )
        for category in (LIKELY_OWNER, LIKELY_INTERMEDIARY, EXPLICIT_AGENCY, UNKNOWN):
            report[category] = int(grouped.get(category, 0))
        report["pending_model_review"] = (
            db.session.query(SearchRunItem.id)
            .join(AccessibleListing, AccessibleListing.id == SearchRunItem.listing_id)
            .filter(
                SearchRunItem.run_id == run_id,
                AccessibleListing.classification_model_status == "pending",
            )
            .count()
        )

    @classmethod
    def _count_section(cls, run_id: str, section: str) -> int:
        return cls._section_query(run_id, section).count()

    @staticmethod
    def _content_hash(record: Dict[str, Any]) -> str:
        stable = {
            key: record.get(key)
            for key in (
                "title", "description", "district", "area", "rooms", "total_price",
                "deposit", "monthly_rent", "published_at", "source_updated_at",
                "publisher_category", "publisher_confidence",
            )
        }
        payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _naive_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
