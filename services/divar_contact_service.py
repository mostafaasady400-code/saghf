"""Shared direct-owner contact lookup for Web, Telegram and Bale flows."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from database.db import db
from database.models import Owner, Property
from crawler.contact_extractor import ContactExtractor
from crawler.text_phone_miner import TextPhoneMiner
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

        # ۱. رد زودهنگام آژانس‌ها و مشاورین - صفر مصرف سهمیه
        if getattr(prop, 'owner_type', None) == 'agency' or prop.is_personal_owner is False:
            from crawler.divar_quota_tracker import DivarQuotaTracker
            DivarQuotaTracker.record_attempt(token=str(prop.id), is_agency=True)
            return {
                "success": False,
                "property_id": prop.id,
                "rejected_as_agency": True,
                "message": "این آگهی متعلق به آژانس یا مشاور املاک است؛ سهمیه استخراج برای آن مصرف نمی‌شود.",
            }

        # ۲. بررسی کش دیتابیس - در صورت وجود شماره، صفر مصرف سهمیه
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
                "message": "این فایل لینک معتبر آگهی دیوار برای استخراج شماره ندارد.",
            }

        # ۲.۵. استخراج فوق‌سریع متن‌کاو محلی بدون مصرف سهمیه
        if not force_refresh:
            mined_local = TextPhoneMiner.mine_phone(prop.description, prop.title)
            if mined_local:
                phone = mined_local["phone"]
                source = "text_miner_local"
                confidence = mined_local.get("confidence", 95)
            else:
                phone = None
                source = "dom"
                confidence = 0
        else:
            phone = None
            source = "dom"
            confidence = 0

        # ۳. بررسی DOM صفحه برای یافتن شماره عمومی بدون مصرف سهمیه API
        if not phone:
            crawler = HybridDivarCrawler(city="tehran")
            dom_result = crawler.fetch_post_dom_details(
                token,
                fallback_title=prop.title or "",
                fallback_description=prop.description or "",
            )

            if dom_result.get("is_agency_post"):
                from crawler.divar_quota_tracker import DivarQuotaTracker
                DivarQuotaTracker.record_attempt(token=token, is_agency=True)
                return {
                    "success": False,
                    "property_id": prop.id,
                    "rejected_as_agency": True,
                    "message": "آگهی در بررسی متن، مشاور/آژانس تشخیص داده شد؛ سهمیه استخراج مصرف نشد.",
                }

            phone = dom_result.get("phone")
            source = dom_result.get("phone_source") or "dom"
            confidence = int(dom_result.get("phone_confidence") or 0)

            # ۳.۵. متن‌کاوی توضیحات جدید دریافتی از DOM
            if not phone:
                mined_dom = TextPhoneMiner.mine_phone(
                    dom_result.get("description") or prop.description,
                    dom_result.get("title") or prop.title
                )
                if mined_dom:
                    phone = mined_dom["phone"]
                    source = "text_miner_dom"
                    confidence = mined_dom.get("confidence", 95)

        # ۴. در صورت نبود شماره در DOM، استفاده از استخر نشست‌ها با کنترل سهمیه روزانه
        if not phone:
            try:
                from crawler.divar_session_pool import DivarSessionPool

                pool_result = DivarSessionPool.extract_owner_phone(token)
                if pool_result.get("success"):
                    phone = pool_result.get("phone")
                    source = pool_result.get("channel_used") or "divar_session_pool"
                    confidence = 100
                elif pool_result.get("is_chat_only"):
                    return {
                        "success": False,
                        "property_id": prop.id,
                        "is_chat_only": True,
                        "message": pool_result.get("message", "مالک این آگهی شماره تماس مستقیم درج نکرده و فقط چت دیوار را فعال نموده است; سهمیه مصرف نشد."),
                    }
                elif pool_result.get("quota_exceeded"):
                    return {
                        "success": False,
                        "property_id": prop.id,
                        "quota_exceeded": True,
                        "message": pool_result.get("message"),
                    }
            except Exception as exc:
                logger.debug("Divar session pool fallback failed: %s", exc)

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
                "message": (
                    "شماره مالک در این لحظه در دسترس نیست (ممکن است آگهی چت‌محور باشد یا سشن نیاز به ورود داشته باشد)."
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

    @classmethod
    def fetch_for_token(
        cls,
        token: str,
        fallback_title: str = "",
        fallback_description: str = "",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """استخراج و اعتبارسنجی شماره تماس بر اساس توکن آگهی دیوار با اولویت کش دیتابیس"""
        clean_token = HybridDivarCrawler.normalize_post_token(token)
        if not clean_token:
            return {
                "success": False,
                "message": "شناسه یا لینک آگهی نامعتبر است.",
            }

        # بررسی وجود ملک مرتبط در پایگاه داده
        prop = Property.query.filter(
            (Property.source_id == f"divar_{clean_token}") |
            (Property.source_id == clean_token) |
            (Property.source_url.contains(clean_token))
        ).first()

        if prop:
            return cls.fetch_for_property(prop, force_refresh=force_refresh)

        # استخراج مستقیم از طریق DivarSessionPool با مدیریت سهمیه
        try:
            from crawler.divar_session_pool import DivarSessionPool
            pool_res = DivarSessionPool.extract_owner_phone(clean_token)
            if pool_res.get('success'):
                phone = pool_res.get('phone')
            elif pool_res.get('is_chat_only'):
                return {
                    "success": False,
                    "token": clean_token,
                    "is_chat_only": True,
                    "message": pool_res.get("message"),
                }
            elif pool_res.get('quota_exceeded'):
                return {
                    "success": False,
                    "token": clean_token,
                    "quota_exceeded": True,
                    "message": pool_res.get("message"),
                }
            else:
                phone = None
        except Exception as exc:
            logger.debug("Divar direct contact fetch failed for token %s: %s", clean_token, exc)
            phone = None

        validation = ContactExtractor.validate_and_normalize(phone)
        if not validation or not validation.get("is_valid") or validation.get("is_suspicious"):
            return {
                "success": False,
                "token": clean_token,
                "message": "شماره تماس از دیوار دریافت نشد (ممکن است نیازمند حل چالش امنیتی یا ورود باشد).",
            }

        normalized_phone = validation["normalized"]
        try:
            owner = Owner.query.filter_by(phone_number=normalized_phone).first()
            if not owner:
                owner = Owner(
                    full_name=fallback_title[:50] if fallback_title else "مالک استخراج‌شده دیوار",
                    phone_number=normalized_phone,
                    notes=f"توکن آگهی: {clean_token}",
                )
                db.session.add(owner)
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error("Could not persist owner for token %s: %s", clean_token, exc)

        return {
            "success": True,
            "phone": normalized_phone,
            "token": clean_token,
            "source": "divar_session_manager",
            "message": f"شماره واقعی مالک ({normalized_phone}) با موفقیت استخراج و اعتبارسنجی شد.",
        }
