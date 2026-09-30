"""Shared direct-owner contact lookup for Web, Telegram and Bale flows."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from database.db import db
from database.models import Owner, Property
from crawler.contact_extractor import ContactExtractor
from crawler.hybrid_divar import HybridDivarCrawler


logger = logging.getLogger(__name__)


class DivarContactService:
    """Fetch a verified owner phone through static DOM/HTTP and persist it once."""

    @staticmethod
    def extract_token(prop: Property) -> str:
        for source_value in (prop.source_url, prop.source_id):
            token = HybridDivarCrawler.normalize_post_token(source_value)
            if token:
                return token
        return ""

    @classmethod
    def fetch_for_property(
        cls,
        prop: Optional[Property],
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        if not prop:
            return {
                "success": False,
                "message": "فایل ملکی موردنظر پیدا نشد.",
            }

        if prop.owner and prop.owner.phone_number and not force_refresh:
            existing = ContactExtractor.validate_and_normalize(prop.owner.phone_number)
            if existing and existing.get("is_valid") and not existing.get("is_suspicious"):
                return {
                    "success": True,
                    "phone": existing["normalized"],
                    "source": "database",
                    "property_id": prop.id,
                    "message": f"شماره مالک ({existing['normalized']}) در پرونده موجود است.",
                }

        token = cls.extract_token(prop)
        is_divar = str(prop.source or "").lower() == "divar" or "divar.ir/v/" in str(
            prop.source_url or ""
        )
        if not token or not is_divar:
            return {
                "success": False,
                "property_id": prop.id,
                "message": "این فایل لینک معتبر آگهی دیوار برای استخراج DOM ندارد.",
            }

        crawler = HybridDivarCrawler(city="tehran")
        dom_result = crawler.fetch_post_dom_details(
            token,
            fallback_title=prop.title or "",
            fallback_description=prop.description or "",
        )

        if dom_result.get("is_agency_post"):
            return {
                "success": False,
                "property_id": prop.id,
                "rejected_as_agency": True,
                "message": "آگهی در بررسی DOM شخصی تشخیص داده نشد؛ شماره به پرونده مالک متصل نشد.",
            }

        phone = dom_result.get("phone")
        source = dom_result.get("phone_source") or "dom"
        confidence = int(dom_result.get("phone_confidence") or 0)

        # Existing authenticated HTTP endpoint remains a browser-free fallback.
        if not phone:
            try:
                from crawler.divar_session_manager import DivarSessionManager

                phone = DivarSessionManager.fetch_contact_phone(token)
                if phone:
                    source = "divar_authenticated_http_api"
                    confidence = 100
            except Exception as exc:
                logger.debug("Divar authenticated contact fallback failed: %s", exc)

        validation = ContactExtractor.validate_and_normalize(phone)
        if not validation or not validation.get("is_valid") or validation.get("is_suspicious"):
            try:
                from crawler.divar_session_manager import DivarSessionManager

                is_auth_needed = not DivarSessionManager.is_authenticated()
            except Exception:
                is_auth_needed = True
            return {
                "success": False,
                "property_id": prop.id,
                "is_auth_needed": is_auth_needed,
                "dom_checked": True,
                "message": (
                    "DOM آگهی بررسی شد اما شماره معتبر و عمومی مالک در HTML موجود نبود. "
                    "اگر شماره پشت دکمه محافظت‌شده دیوار است، نشست HTTP احراز هویت‌شده لازم است."
                ),
            }

        normalized_phone = validation["normalized"]
        try:
            if prop.owner:
                prop.owner.phone_number = normalized_phone
                if not prop.owner.full_name:
                    prop.owner.full_name = "مالک مستقیم"
            else:
                owner = Owner.query.filter_by(phone_number=normalized_phone).first()
                if not owner:
                    owner = Owner(
                        full_name="مالک استخراج‌شده از DOM دیوار",
                        phone_number=normalized_phone,
                        notes=f"منبع استخراج شماره: {source}",
                    )
                    db.session.add(owner)
                    db.session.flush()
                prop.owner_id = owner.id

            prop.is_personal_owner = True
            prop.owner_type = "personal"
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error("Could not persist DOM owner phone for property %s: %s", prop.id, exc)
            return {
                "success": False,
                "property_id": prop.id,
                "message": "شماره استخراج شد اما ثبت آن در پرونده با خطا روبه‌رو شد.",
            }

        source_label = "DOM صفحه آگهی" if source.startswith("dom") else "درخواست HTTP دیوار"
        return {
            "success": True,
            "phone": normalized_phone,
            "source": source,
            "confidence": confidence,
            "property_id": prop.id,
            "message": f"شماره واقعی مالک ({normalized_phone}) از {source_label} استخراج و ثبت شد.",
        }
