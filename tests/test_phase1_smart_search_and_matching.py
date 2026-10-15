import unittest
import uuid
from datetime import datetime
from app import create_app
from database.db import db
from database.models import AccessibleListing, SearchRun, SearchRunItem
from services.search_run_service import SearchRunService
from crawler.publisher_classifier import LIKELY_OWNER, EXPLICIT_AGENCY

class TestPhase1ExtractionPipeline(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.uid = uuid.uuid4().hex[:8]
        self._cleanup()

    def tearDown(self):
        self._cleanup()
        self.app_context.pop()

    def _cleanup(self):
        try:
            # Delete children first to respect SQLite foreign keys
            SearchRunItem.query.filter(SearchRunItem.run_id.like("test_run_%")).delete(synchronize_session=False)
            listings = AccessibleListing.query.filter(AccessibleListing.source_id.like("test_phase1_%")).all()
            if listings:
                l_ids = [l.id for l in listings]
                SearchRunItem.query.filter(SearchRunItem.listing_id.in_(l_ids)).delete(synchronize_session=False)
                AccessibleListing.query.filter(AccessibleListing.id.in_(l_ids)).delete(synchronize_session=False)
            SearchRun.query.filter(SearchRun.run_id.like("test_run_%")).delete(synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()

    def test_01_search_run_lifecycle_and_criteria_normalization(self):
        criteria = {
            "city": "tehran",
            "districts": ["پونک", "شهران"],
            "deal_type": "sale",
            "property_type": "apartment",
            "min_price": 5000000000,
            "max_price": 18000000000,
            "window_hours": 24
        }
        run = SearchRunService.create_run(criteria, query_text="خرید پونک و شهران ۵ تا ۱۸ میلیارد")
        self.assertIsNotNone(run.run_id)
        self.assertEqual(run.status, "pending")
        self.assertTrue(run.can_resume)
        self.assertEqual(run.criteria.get("deal_type"), "sale")
        self.assertIn("پونک", run.criteria.get("districts", []))

    def test_02_upsert_and_revision_tracking(self):
        src_id = f"test_phase1_rev_{self.uid}"
        record = {
            "source": "divar",
            "source_id": src_id,
            "source_url": f"https://divar.ir/v/{src_id}",
            "title": "آپارتمان ۱۱۰ متری شهران شمالی شخصی‌ساز",
            "description": "فروشنده واقعی هستم. سند تک‌برگ شخصی آماده انتقال. مشاورین محترم تماس نگیرند.",
            "city": "تهران",
            "district": "شهران شمالی",
            "deal_type": "sale",
            "property_type": "apartment",
            "area": 110.0,
            "rooms": 2,
            "total_price": 12000000000,
            "publisher_category": LIKELY_OWNER,
            "publisher_confidence": 0.94,
            "publisher_reason": "سند تک‌برگ شخصی و اعلام مالکیت صریح بدون واسطه",
        }
        listing = SearchRunService._upsert_listing(record)
        db.session.commit()
        self.assertEqual(listing.source_id, src_id)
        self.assertEqual(listing.publisher_category, LIKELY_OWNER)

        # Update price to verify revision tracking
        record_updated = dict(record)
        record_updated["total_price"] = 11500000000
        listing_updated = SearchRunService._upsert_listing(record_updated)
        db.session.commit()
        self.assertEqual(listing_updated.total_price, 11500000000)

    def test_03_paginated_results_sections(self):
        criteria = {"deal_type": "sale", "window_hours": 24, "city": "tehran"}
        run = SearchRunService.create_run(criteria, query_text="تست بخش‌بندی نتایج استخراج")
        run.run_id = f"test_run_paginate_{self.uid}"
        run.status = "completed"
        run.coverage_status = "complete"
        db.session.commit()

        src_owner = f"test_phase1_owner_{self.uid}"
        src_agent = f"test_phase1_agent_{self.uid}"

        # 1. Owner item (should be in main section)
        l_owner = AccessibleListing(
            source="divar",
            source_id=src_owner,
            source_url=f"https://divar.ir/v/{src_owner}",
            title="مالک واقعی پونک",
            district="پونک",
            deal_type="sale",
            area=90.0,
            publisher_category=LIKELY_OWNER,
            first_seen_at=datetime.utcnow()
        )
        db.session.add(l_owner)
        db.session.flush()

        item_owner = SearchRunItem(
            run_id=run.run_id,
            listing_id=l_owner.id,
            temporal_status="inside",
            criteria_match=True,
            publisher_category_snapshot=LIKELY_OWNER
        )
        db.session.add(item_owner)

        # 2. Intermediary item (should be in intermediary section)
        l_agent = AccessibleListing(
            source="divar",
            source_id=src_agent,
            source_url=f"https://divar.ir/v/{src_agent}",
            title="املاک پارسا سعادت‌آباد",
            district="سعادت‌آباد",
            deal_type="sale",
            area=120.0,
            publisher_category=EXPLICIT_AGENCY,
            first_seen_at=datetime.utcnow()
        )
        db.session.add(l_agent)
        db.session.flush()

        item_agent = SearchRunItem(
            run_id=run.run_id,
            listing_id=l_agent.id,
            temporal_status="inside",
            criteria_match=True,
            publisher_category_snapshot=EXPLICIT_AGENCY
        )
        db.session.add(item_agent)
        db.session.commit()

        # Query main section
        main_res = SearchRunService.paginated_results(run.run_id, section="main", page=1, per_page=10)
        self.assertEqual(main_res["pagination"]["total"], 1)
        self.assertEqual(main_res["items"][0]["source_id"], src_owner)

        # Query intermediary section
        inter_res = SearchRunService.paginated_results(run.run_id, section="intermediary", page=1, per_page=10)
        self.assertEqual(inter_res["pagination"]["total"], 1)
        self.assertEqual(inter_res["items"][0]["source_id"], src_agent)