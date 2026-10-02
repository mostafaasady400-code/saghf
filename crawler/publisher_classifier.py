"""Evidence-based publisher classification for real-estate listings."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from crawler.owner_filter import clean_persian_text


EXPLICIT_AGENCY = "explicit_agency"
LIKELY_INTERMEDIARY = "likely_intermediary"
LIKELY_OWNER = "likely_owner"
UNKNOWN = "unknown"
CLASSIFIER_VERSION = "publisher-rules-2.1.0"


@dataclass
class PublisherDecision:
    category: str
    confidence: float
    reason: str
    evidence: List[str] = field(default_factory=list)
    classifier_version: str = CLASSIFIER_VERSION
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    model_status: str = "not_required"

    @property
    def is_main_result(self) -> bool:
        return self.category == LIKELY_OWNER

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PublisherClassifier:
    """Combine structured account facts, contextual rules and optional semantics."""

    SAFE_OWNER_DISCLAIMERS = (
        r"(?:لطفا\s+|خواهشا\s+|اکیدا\s+)?(?:از\s+)?(?:دفاتر\s+|دفتر\s+)?(?:مشاور|مشاوران|مشاورین|املاک|همکار|همکاران)(?:[^\.\n،,!؟?]*?)تماس\s*(?:حاصل\s*)?(?:نفرمایید|نگیر(?:د|ند|ید|ین|ه)?|ممنوع)",
        r"(?:همکاری\s+با\s+)?(?:دفاتر\s+|دفتر\s+)?(?:مشاور|مشاوران|مشاورین|املاک|همکار|همکاران)\s+(?:نداریم|ندارم|نمیکنیم|نمیکنم)",
        r"بدون\s+(?:واسطه|مشاور|کمیسیون)",
        r"مستقیم\s+و\s+بی\s*واسطه",
        r"فقط\s+(?:به\s+)?مصرف\s*کننده",
    )
    OWNER_MARKERS = (
        "مالک هستم",
        "من مالک",
        "خودم مالک",
        "مالک واحد",
        "مستقیم از مالک",
        "واگذاری توسط مالک",
        "شخصی و بی واسطه",
        "بدون واسطه",
        "سکونت خودم بوده",
    )
    STRONG_INTERMEDIARY_PHRASES = (
        "مشاور املاک",
        "مشاور فروش",
        "کارشناس منطقه",
        "کارشناس فروش",
        "دفتر املاک",
        "دفتر معاملات",
        "دپارتمان فروش",
        "دپارتمان اجاره",
        "فایل های دیگر",
        "فایل‌های دیگر",
        "فایل های مشابه",
        "فایل‌های مشابه",
        "موارد مشابه",
        "کلید نزد املاک",
        "بازدید با هماهنگی دفتر",
        "برای مشاوره",
        "تیم فروش",
        "واحد فایلینگ",
        "کارشناس ملکی",
        "کارشناس امور ملکی",
        "کارشناس تخصصی",
        "مشاور شما",
        "مشاور تخصصی",
        "مشاور امور ملکی",
        "مشاور شما در منطقه",
    )
    INTERMEDIARY_TERMS = (
        "آژانس",
        "بنگاه",
        "دپارتمان",
        "کارگزاری",
        "املاک",
        "مشاور",
        "کارشناس",
        "فایلینگ",
        "کمیسیون",
        "همکار همکاری نمی کنیم",
        "با همکار همکاری نمی کنیم",
    )
    PROMOTIONAL_MARKERS = (
        "اکازیون",
        "زیر قیمت منطقه",
        "فرصت استثنایی",
        "تک بازدید",
        "فوق العاده",
        "سرمایه گذاری",
        "پاسخگویی ۲۴ ساعته",
    )
    PERSONAL_TIME_MARKERS = (
        "لحظاتی پیش",
        "دقایقی پیش",
        "دقیقه پیش",
        "ساعت پیش",
        "امروز",
    )

    @classmethod
    def classify(
        cls,
        *,
        title: str,
        description: str = "",
        structured: Optional[Dict[str, Any]] = None,
        listing_context: str = "",
        behavioral: Optional[Dict[str, Any]] = None,
        semantic_label: Optional[str] = None,
        semantic_confidence: Optional[float] = None,
        model_available: bool = True,
    ) -> PublisherDecision:
        structured = structured or {}
        behavioral = behavioral or {}
        evidence: List[str] = []

        structured_facts = cls._structured_facts(structured)
        if structured_facts["explicit_agency"]:
            return PublisherDecision(
                category=EXPLICIT_AGENCY,
                confidence=0.99,
                reason="منبع، حساب یا پنل منتشرکننده را تجاری/املاکی معرفی کرده است.",
                evidence=structured_facts["evidence"],
            )

        text = clean_persian_text(f"{title} {description} {listing_context}")
        rule_text = text
        safe_disclaimers: List[str] = []
        for pattern in cls.SAFE_OWNER_DISCLAIMERS:
            for match in re.finditer(pattern, rule_text):
                safe_disclaimers.append(match.group(0))
            rule_text = re.sub(pattern, " __OWNER_DISCLAIMER__ ", rule_text)

        owner_score = 0
        intermediary_score = 0

        if structured_facts["explicit_personal"]:
            owner_score += 3
            evidence.append("structured:personal_account")

        owner_hits = [marker for marker in cls.OWNER_MARKERS if marker in text]
        if owner_hits:
            # «مالک هستم» به‌تنهایی اثبات مالکیت نیست. یک ادعای متنی منفرد تنها ۲ امتیاز دارد و
            # برای احراز قطعی مالک، شواهد هم‌راستا (حساب شخصی، رد مشاور، یا نشانه‌های متنی متعدد) الزامی است.
            if len(owner_hits) == 1 and owner_hits[0] in {"مالک هستم", "من مالک", "خودم مالک", "مالک واحد"}:
                owner_score += 2
                evidence.append(f"owner_claim:{owner_hits[0]}")
                evidence.append("unverified_single_owner_claim")
            else:
                owner_score += min(4, 2 + len(owner_hits))
                evidence.extend(f"owner_text:{item}" for item in owner_hits[:3])
        if safe_disclaimers:
            # A direct request that agents do not call is a contextual owner signal,
            # not an occurrence of the word «مشاور» to be rejected blindly.
            owner_score += 3
            evidence.extend(f"owner_disclaimer:{item}" for item in safe_disclaimers[:2])

        strong_hits = [phrase for phrase in cls.STRONG_INTERMEDIARY_PHRASES if phrase in rule_text]
        if strong_hits:
            intermediary_score += 3 + min(2, len(strong_hits) - 1)
            evidence.extend(f"intermediary_phrase:{item}" for item in strong_hits[:4])

        term_hits = cls._independent_term_hits(rule_text)
        if term_hits:
            intermediary_score += min(3, len(term_hits))
            evidence.extend(f"intermediary_term:{item}" for item in term_hits[:4])

        promo_hits = [marker for marker in cls.PROMOTIONAL_MARKERS if marker in rule_text]
        if len(promo_hits) >= 2:
            intermediary_score += 1
            evidence.append(f"promotional_style:{','.join(promo_hits[:3])}")

        repeated_ads = int(behavioral.get("recent_listing_count") or 0)
        repeated_texts = int(behavioral.get("repeated_text_count") or 0)
        if repeated_ads >= 8:
            intermediary_score += 2
            evidence.append(f"behavior:recent_listing_count={repeated_ads}")
        elif repeated_ads >= 3:
            intermediary_score += 1
            evidence.append(f"behavior:recent_listing_count={repeated_ads}")
        if repeated_texts >= 3:
            intermediary_score += 1
            evidence.append(f"behavior:repeated_text_count={repeated_texts}")

        if any(marker in listing_context for marker in cls.PERSONAL_TIME_MARKERS):
            owner_score += 1
            evidence.append("listing_context:fresh_personal_pattern")

        # Strong intermediary evidence wins over a self-asserted owner claim.
        if intermediary_score >= 3:
            confidence = min(0.95, 0.66 + intermediary_score * 0.06)
            if owner_score:
                evidence.append("contradiction:owner_claim_vs_intermediary_signals")
            return PublisherDecision(
                category=LIKELY_INTERMEDIARY,
                confidence=round(confidence, 2),
                reason="چند نشانهٔ مستقل از فعالیت واسطه‌ای/فایلینگ در متن یا رفتار دیده شد.",
                evidence=list(dict.fromkeys(evidence)),
            )

        # احراز مالک نیازمند شواهد معتبر و هم‌راستاست؛ ادعای منفرد «مالک هستم» به‌تنهایی اثبات نیست.
        has_corroborated_owner_evidence = (
            (structured_facts["explicit_personal"] and (owner_hits or safe_disclaimers))
            or (safe_disclaimers and owner_hits)
            or (len(owner_hits) >= 2)
            or (structured_facts["explicit_personal"] and owner_score >= 4)
        )

        if owner_score >= 4 and has_corroborated_owner_evidence and (
            intermediary_score == 0 or (owner_score >= 6 and intermediary_score <= 1)
        ):
            confidence = min(0.90, 0.65 + owner_score * 0.05)
            return PublisherDecision(
                category=LIKELY_OWNER,
                confidence=round(confidence, 2),
                reason="شواهد چندگانه و هم‌راستا با انتشار مستقیم مالک دیده شد و نشانهٔ واسطه‌ای مؤثری وجود نداشت.",
                evidence=list(dict.fromkeys(evidence)),
            )

        if semantic_label in {LIKELY_OWNER, LIKELY_INTERMEDIARY} and semantic_confidence:
            bounded = max(0.0, min(float(semantic_confidence), 0.89))
            return PublisherDecision(
                category=semantic_label,
                confidence=round(bounded, 2),
                reason="قواعد قطعی کافی نبود؛ نتیجهٔ تحلیل معنایی برای مورد مبهم ثبت شد.",
                evidence=list(dict.fromkeys(evidence + ["semantic_model:ambiguous_case"])),
                model_status="completed",
            )

        model_status = "pending" if not model_available else "not_requested"
        reason = (
            "ادعای «مالک هستم» به‌تنهایی اثبات مالکیت نیست و نیازمند شواهد تکمیلی یا حساب شخصی است."
            if "unverified_single_owner_claim" in evidence
            else "شواهد کافی و بدون تناقض برای تشخیص مالک یا واسطه وجود ندارد."
        )
        return PublisherDecision(
            category=UNKNOWN,
            confidence=0.50,
            reason=reason,
            evidence=list(dict.fromkeys(evidence)),
            model_status=model_status,
        )

    @classmethod
    def _structured_facts(cls, structured: Dict[str, Any]) -> Dict[str, Any]:
        evidence: List[str] = []
        explicit_agency = False
        explicit_personal = False

        def walk(value: Any) -> None:
            nonlocal explicit_agency, explicit_personal
            if isinstance(value, dict):
                for key, nested in value.items():
                    norm_key = str(key).lower().replace("-", "_")
                    if norm_key == "is_business":
                        if nested is True:
                            explicit_agency = True
                            evidence.append("structured:is_business=true")
                        elif nested is False:
                            explicit_personal = True
                            evidence.append("structured:is_business=false")
                    elif norm_key in {"agency_id", "business_id"} and nested:
                        explicit_agency = True
                        evidence.append(f"structured:{norm_key}")
                    elif norm_key in {"business_type", "post_business_type", "account_type", "publisher_type"}:
                        account_type = str(nested or "").strip().lower()
                        if account_type in {"personal", "private", "individual"}:
                            explicit_personal = True
                            evidence.append(f"structured:{norm_key}=personal")
                        elif account_type in {
                            "business", "agency", "consultant", "premium-panel",
                            "premium_panel", "real_estate_agency", "realtor",
                        }:
                            explicit_agency = True
                            evidence.append(f"structured:{norm_key}={account_type}")
                    if isinstance(nested, (dict, list)):
                        walk(nested)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(structured)
        return {
            "explicit_agency": explicit_agency,
            "explicit_personal": explicit_personal,
            "evidence": list(dict.fromkeys(evidence)),
        }

    @classmethod
    def _independent_term_hits(cls, text: str) -> List[str]:
        hits: List[str] = []
        for term in cls.INTERMEDIARY_TERMS:
            pattern = rf"(?<![آ-یa-zA-Z0-9_]){re.escape(term)}(?![آ-یa-zA-Z0-9_])"
            if re.search(pattern, text):
                hits.append(term)
        return hits
