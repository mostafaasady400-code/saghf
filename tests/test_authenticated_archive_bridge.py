from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import Flask

from database.db import db
from database.models import AccessibleListing
from services.assistant.crawler_bridge import CrawlerBridge


def test_old_likely_owner_labels_cannot_bypass_current_owner_guard():
    assert not CrawlerBridge._is_clean_personal_listing(SimpleNamespace(title="آپارتمان نورگیر", description="واحد آماده تحویل"))
    assert not CrawlerBridge._is_clean_personal_listing(SimpleNamespace(title="آپارتمان", description="مالک هستم، فایل شخصی، کلید در اختیار"))
    assert CrawlerBridge._is_clean_personal_listing(SimpleNamespace(title="آپارتمان", description="مالک هستم، بدون واسطه"))
    assert CrawlerBridge._is_clean_personal_listing(SimpleNamespace(title="آپارتمان با آشپزخانه بزرگ", description="صاحبخانه هستم، بدون واسطه"))


def test_archive_uses_publication_window_not_first_seen():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    now = datetime.utcnow()
    with app.app_context():
        db.create_all()
        for token, published in [("recent", now - timedelta(days=6)), ("old", now - timedelta(days=8)), ("unknown", None)]:
            db.session.add(AccessibleListing(source_id=token, source_url="https://divar.ir/v/" + token, title="واحد شخصی", publisher_category="likely_owner", deal_type="rent", deposit=100, published_at=published, publication_earliest_at=published, publication_latest_at=published, first_seen_at=now))
        db.session.commit()
        rows = CrawlerBridge._base_owner_query("rent", now - timedelta(days=7)).all()
        assert [row.source_id for row in rows] == ["recent"]
        assert CrawlerBridge._is_clean_personal_listing(rows[0]) is False
        result = CrawlerBridge.search_live_listings("rent", refresh_live=False)
        assert result["meta"]["is_live"] is False
        assert result["meta"]["data_source"] == "persisted_archive"
        result["meta"]["live_refresh"] = {"status": "failed"}
        answer = CrawlerBridge.format_assistant_response(result)
        assert "تازه‌سازی زنده ناموفق" in answer["chat_markdown"]
        assert "168" in answer["chat_markdown"]
        db.session.remove()
        db.drop_all()
def test_guard_hides_legacy_agency_from_real_assistant_contract_without_deleting():
    from crawler.strict_owner_guard import install_strict_owner_guard
    install_strict_owner_guard()
    app = Flask("strict_archive_test")
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    now = datetime.utcnow()
    with app.app_context():
        db.create_all()
        for token, description in [("guard-test-agency", "املاک ارغوان لطفا همکاران تماس نگیرن"), ("guard-test-owner", "مالک هستم؛ مشاوران تماس نگیرند")]:
            db.session.add(AccessibleListing(source_id=token, source_url="https://divar.ir/v/" + token, title="آپارتمان ۹۵ متری", description=description, city="tehran", area=95, rooms=2, publisher_category="likely_owner", deal_type="rent", deposit=100, published_at=now, publication_earliest_at=now, publication_latest_at=now, first_seen_at=now))
        db.session.commit()
        before = AccessibleListing.query.count()
        result = CrawlerBridge.search_live_listings("rent", min_area=70, max_area=100, refresh_live=False)
        answer = CrawlerBridge.format_assistant_response(result)
        assert result["meta"]["total_listings"] == 1
        assert "guard-test-agency" not in answer["chat_markdown"]
        assert "guard-test-owner" in answer["chat_markdown"]
        assert AccessibleListing.query.count() == before == 2
        assert AccessibleListing.query.filter_by(source_id="guard-test-agency").first().publisher_category == "likely_owner"
        db.session.remove()
        db.drop_all()
