"""Independent pre-guard for Divar; shared source is never edited.

The explicit runtime adapter preserves the original evaluator and result type.
An account marked personal cannot bypass content/owner-claim checks.
"""
import re
import unicodedata
from dataclasses import dataclass
from functools import wraps

VERSION = "strict-owner-v1"


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = "".join(" " if c == "\u200c" else c for c in text if (unicodedata.category(c) != "Cf" or c == "\u200c") and c != "ـ")
    text = text.translate(str.maketrans({"ي": "ی", "ك": "ک"})).lower()
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    status: str
    terms: tuple = ()


HARD_PATTERNS = (
    (r"مناسب\s+سکونت\s+خانواده[\s،,.؛:و()«»\-]*مشتریان[\s()«»]*سخت[\s\-]*پسند", "سکونت خانواده و مشتریان سخت‌پسند"),
    (r"مالک\s*مستقیم", "مالک مستقیم"),
    (r"همکار(?:ان|ی)?", "همکار"),
    (r"فایل\s*(?:کاملا\s*|کاملاً\s*|۱۰۰٪\s*|100%\s*)?شخصی", "فایل شخصی"),
    (r"کلید\s*در\s*اختیار", "کلید در اختیار"),
    (r"(?:عکس|تصویر|تصاویر)(?:\s*(?:ها|های))?\s*مشابه", "عکس مشابه"),
    (r"(?:عکس|تصویر|تصاویر)(?:\s*(?:ها|های))?\s*(?:تزیینی|تزئینی|آرشیوی)", "عکس تزیینی"),
)
OWNER_CLAIMS = (
    r"مالک\s+(?:(?:مستقیم|اصلی)\s+)?(?:هستم|هستیم|می\s*باشم|واحد\s+هستم)",
    r"(?:خودم|من)\s+مالک\s+(?:هستم|این\s+(?:واحد|ملک|آپارتمان)\s+هستم)",
    r"صاحب\s*خانه\s+(?:هستم|هستیم)",
    r"مالکم", r"واگذاری\s+توسط\s+مالک", r"فروشنده\s+واقعی\s+هستم",
)
# Only the exact neutral no-call sentence is exempted, never arbitrary words
# between an agency term and "تماس". A separate owner claim is still required.
NEUTRAL_DISCLAIMER = re.compile(
    r"(?:(?:لطفا\s+|خواهشا\s+|اکیدا\s+)?"
    r"(?:مشاور(?:ان|ین)?(?:\s+(?:محترم\s+)?املاک)?|(?:دفاتر\s+|دفتر\s+)?املاک|بنگاه(?:ها)?)"
    r"\s+تماس\s*(?:حاصل\s*)?(?:نگیر(?:ند|ید|ین|د|ه|ن)?|نفرمایید)(?![\w]))"
    r"|(?:(?:بدون|فاقد|عدم\s+پرداخت)\s+(?:واسطه\s+و\s+)?(?:هیچ\s+گونه\s+)?(?:یک\s+ریال\s+)?کم[یِ]?سیون(?![\w]))"
)
AGENCY_WORDS = ("املاک", "مسکن", "مشاور", "مشاوران", "مشاورین", "کارشناس", "کارشناسان", "کمیسیون", "کمسیون", "بنگاه", "دپارتمان", "آژانس", "نماینده", "دفتر فروش")


def strict_decision(title, description="", metadata=None, raw_text=""):
    metadata = metadata if isinstance(metadata, dict) else {}
    nodes = [metadata]
    for key in ("publisher", "advertiser", "seller", "business"):
        if isinstance(metadata.get(key), dict):
            nodes.append(metadata[key])
    action = metadata.get("action_log")
    server = action.get("server_side_info") if isinstance(action, dict) else None
    info = server.get("info") if isinstance(server, dict) else None
    if isinstance(info, dict):
        nodes.append(info)
    for node in nodes:
        if node.get("is_business") is True or node.get("is_agency_post") is True or node.get("agency_id") or node.get("business_id"):
            return GuardDecision(False, "rejected_agency_metadata", ("agency_metadata",))
        for key in ("business_type", "account_type", "publisher_type"):
            value = normalize(node.get(key))
            if value and value not in {"personal", "owner", "none", "unknown"}:
                return GuardDecision(False, "rejected_agency_metadata", (key,))
    text = normalize(f"{title or ''} {description or ''} {raw_text or ''}")
    terms = tuple(label for pattern, label in HARD_PATTERNS if re.search(pattern, text))
    if terms:
        return GuardDecision(False, "rejected_forbidden_words", terms)
    remaining = NEUTRAL_DISCLAIMER.sub(" ", text)
    terms = tuple(word for word in AGENCY_WORDS if re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", remaining))
    if terms:
        return GuardDecision(False, "rejected_forbidden_words", terms)
    if not any(re.search(r"(?<![\w])" + pattern + r"(?![\w])", text) for pattern in OWNER_CLAIMS):
        return GuardDecision(False, "rejected_unverified_owner")
    return GuardDecision(True, "owner_claim_present")


def install_strict_owner_guard():
    """Install once per process, before either crawler or assistant API use."""
    from crawler.owner_filter import OwnerFilter, FilterResult
    if getattr(OwnerFilter.evaluate, "_strict_owner_version", None) == VERSION:
        return
    original = OwnerFilter.evaluate

    @wraps(original.__func__)
    def evaluate(cls, platform, title, description="", widget_data=None, raw_text=""):
        if str(platform).lower() == "divar":
            decision = strict_decision(title, description, widget_data, raw_text)
            baseline = original(platform=platform, title=title, description=description, widget_data=widget_data, raw_text=raw_text)
            # Preserve existing rejection/account/shared-housing contracts.
            # The independent decision can veto approval, never weaken it.
            if not baseline.is_personal:
                return baseline
            if not decision.allowed:
                return FilterResult(
                    is_personal=False, status=decision.status,
                    reason="محافظ مستقل: " + ("نشانهٔ واسطه‌گری در آگهی" if decision.terms else "اظهار مستقل مالکیت مستقیم موجود نیست"),
                    detected_terms=list(decision.terms),
                    owner_type="agency" if decision.terms else "unknown",
                    confidence_score=0, risk_level="high",
                    metadata={"stage": "strict_owner_guard", "version": VERSION},
                )
            return baseline
        return original(platform=platform, title=title, description=description, widget_data=widget_data, raw_text=raw_text)

    evaluate._strict_owner_version = VERSION
    OwnerFilter.evaluate = classmethod(evaluate)
