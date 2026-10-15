"""
Static DOM contact extraction for Divar ads.

This module deliberately parses the HTML returned by an ordinary HTTP client.  It
does not start a browser, execute JavaScript, or depend on Playwright/Selenium.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

from crawler.contact_extractor import ContactExtractor
from crawler.owner_filter import OwnerFilter


class DivarDOMContactParser:
    """Extract and verify a direct-owner phone number from server-rendered HTML."""

    CONTACT_KEYS = {
        "phone",
        "phone_number",
        "phonenumber",
        "mobile",
        "mobile_number",
        "mobilenumber",
        "telephone",
        "tel",
        "call_number",
        "contact_number",
        "contact_phone",
    }
    TITLE_KEYS = {"title", "post_title", "name", "headline"}
    DESCRIPTION_KEYS = {"description", "post_description", "body", "caption"}
    CONTACT_CONTEXT_WORDS = (
        "شماره تماس",
        "شماره تلفن",
        "شماره مالک",
        "تماس با مالک",
        "تماس مستقیم",
        "موبایل",
        "واتساپ",
        "تلفن",
    )
    JSON_ASSIGNMENTS = (
        "window.__PRELOADED_STATE__",
        "window.__INITIAL_STATE__",
        "window.__NEXT_DATA__",
    )
    BUSINESS_TYPES = {
        "business",
        "agency",
        "consultant",
        "premium-panel",
        "premium_panel",
        "real_estate_agency",
        "real-estate-agency",
        "realtor",
    }

    @classmethod
    def parse(
        cls,
        html: str,
        fallback_title: str = "",
        fallback_description: str = "",
    ) -> Dict[str, Any]:
        """Parse HTML and return a phone only when the advertiser remains personal."""
        result: Dict[str, Any] = {
            "phone": None,
            "phone_source": None,
            "phone_confidence": 0,
            "title": fallback_title or "",
            "description": fallback_description or "",
            "is_personal_owner": False,
            "is_agency_post": False,
            "owner_filter_status": "dom_unavailable",
            "owner_filter_reason": "DOM آگهی در دسترس نیست.",
            "agency_evidence": [],
        }
        if not html or not isinstance(html, str):
            return result

        soup = BeautifulSoup(html, "html.parser")
        structured_objects = cls._extract_structured_objects(soup)

        title = cls._extract_title(soup, structured_objects) or fallback_title or ""
        description = (
            cls._extract_description(soup, structured_objects)
            or fallback_description
            or ""
        )
        account_meta, agency_evidence = cls._extract_account_metadata(
            soup, structured_objects
        )

        seller_context = cls._seller_context(soup)
        filter_result = OwnerFilter.evaluate(
            platform="divar",
            title=title,
            description=description,
            widget_data=account_meta,
            raw_text=seller_context,
        )
        is_agency = bool(agency_evidence) or filter_result.owner_type == "agency" or filter_result.status in {"rejected_account_type", "rejected_forbidden_words"}
        is_personal_owner = filter_result.is_personal and not bool(agency_evidence) and not is_agency

        result.update(
            {
                "title": title,
                "description": description,
                "is_personal_owner": is_personal_owner,
                "is_agency_post": is_agency,
                "owner_filter_status": filter_result.status,
                "owner_filter_reason": filter_result.reason,
                "agency_evidence": agency_evidence,
            }
        )

        # Never attach a contact number to a post rejected by the owner gate.
        if is_agency or not is_personal_owner:
            return result

        candidates: List[Tuple[int, str, str]] = []
        cls._collect_dom_candidates(soup, candidates)
        cls._collect_structured_candidates(structured_objects, candidates)
        cls._collect_inline_script_candidates(soup, candidates)

        normalized: Dict[str, Tuple[int, str]] = {}
        for confidence, source, raw_value in candidates:
            phone = ContactExtractor.extract_primary_phone(
                str(raw_value), filter_dummy=True
            )
            if not phone:
                validation = ContactExtractor.validate_and_normalize(str(raw_value))
                if (
                    validation
                    and validation.get("is_valid")
                    and not validation.get("is_suspicious")
                ):
                    phone = validation["normalized"]
            if not phone:
                continue

            validation = ContactExtractor.validate_and_normalize(phone)
            mobile_bonus = 2 if validation and validation.get("type") == "mobile" else 0
            ranked_confidence = min(100, confidence + mobile_bonus)
            previous = normalized.get(phone)
            if previous is None or ranked_confidence > previous[0]:
                normalized[phone] = (ranked_confidence, source)

        if normalized:
            phone, (confidence, source) = max(
                normalized.items(), key=lambda item: item[1][0]
            )
            result.update(
                {
                    "phone": phone,
                    "phone_source": source,
                    "phone_confidence": confidence,
                }
            )
        return result

    @classmethod
    def _collect_dom_candidates(
        cls, soup: BeautifulSoup, candidates: List[Tuple[int, str, str]]
    ) -> None:
        for anchor in soup.select('a[href^="tel:"]'):
            candidates.append((98, "dom_tel_href", anchor.get("href", "")[4:]))

        for node in soup.select('[itemprop="telephone"]'):
            value = node.get("content") or node.get("href") or node.get_text(" ", strip=True)
            if value:
                candidates.append((95, "dom_itemprop_telephone", value))

        contact_attrs = {
            "data-phone",
            "data-phone-number",
            "data-mobile",
            "data-telephone",
            "data-tel",
            "data-contact",
            "data-contact-phone",
        }
        for node in soup.find_all(True):
            for attr_name, attr_value in node.attrs.items():
                if attr_name.lower() in contact_attrs and attr_value:
                    value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                    candidates.append((94, f"dom_{attr_name}", value))

        for meta in soup.find_all("meta"):
            marker = " ".join(
                str(meta.get(key, "")) for key in ("name", "property", "itemprop")
            ).lower()
            if any(key in marker for key in ("phone", "mobile", "telephone", "contact")):
                content = meta.get("content")
                if content:
                    candidates.append((92, "dom_meta_contact", content))

        # Restrict free-text extraction to nodes explicitly labelled as contact data.
        for node in soup.find_all(True):
            label = " ".join(
                str(node.get(key, "")) for key in ("aria-label", "title")
            )
            text = node.get_text(" ", strip=True)
            combined = f"{label} {text}".strip()
            if combined and any(word in combined for word in cls.CONTACT_CONTEXT_WORDS):
                candidates.append((78, "dom_contact_context", combined))

    @classmethod
    def _collect_structured_candidates(
        cls,
        objects: Iterable[Any],
        candidates: List[Tuple[int, str, str]],
    ) -> None:
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized_key = re.sub(r"[^a-z0-9_]", "", str(key).lower())
                    if normalized_key in cls.CONTACT_KEYS and nested not in (None, ""):
                        candidates.append((90, f"dom_json_{normalized_key}", str(nested)))
                    if isinstance(nested, (dict, list)):
                        walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        for obj in objects:
            walk(obj)

    @classmethod
    def _collect_inline_script_candidates(
        cls, soup: BeautifulSoup, candidates: List[Tuple[int, str, str]]
    ) -> None:
        key_pattern = "|".join(re.escape(key) for key in sorted(cls.CONTACT_KEYS))
        pattern = re.compile(
            rf'["\'](?:{key_pattern})["\']\s*:\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        for script in soup.find_all("script"):
            script_text = script.string or script.get_text(" ", strip=False)
            if not script_text:
                continue
            for match in pattern.finditer(script_text):
                candidates.append((86, "dom_inline_contact_json", match.group(1)))

    @classmethod
    def _extract_structured_objects(cls, soup: BeautifulSoup) -> List[Any]:
        objects: List[Any] = []
        for script in soup.find_all("script"):
            text = (script.string or script.get_text(" ", strip=False) or "").strip()
            if not text:
                continue
            script_type = str(script.get("type", "")).lower()
            script_id = str(script.get("id", ""))
            if "json" in script_type or script_id == "__NEXT_DATA__":
                try:
                    objects.append(json.loads(text))
                    continue
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

            for assignment in cls.JSON_ASSIGNMENTS:
                marker_pos = text.find(assignment)
                if marker_pos < 0:
                    continue
                equals_pos = text.find("=", marker_pos + len(assignment))
                if equals_pos < 0:
                    continue
                payload = cls._balanced_json(text, equals_pos + 1)
                if payload:
                    try:
                        objects.append(json.loads(payload))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
        return objects

    @staticmethod
    def _balanced_json(text: str, start: int) -> Optional[str]:
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text) or text[start] not in "[{":
            return None

        opening = text[start]
        closing = "}" if opening == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    @classmethod
    def _extract_title(cls, soup: BeautifulSoup, objects: Iterable[Any]) -> str:
        h1 = soup.find("h1")
        if h1 and h1.get_text(" ", strip=True):
            return h1.get_text(" ", strip=True)
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            return str(meta["content"]).strip()
        return cls._first_structured_text(objects, cls.TITLE_KEYS)

    @classmethod
    def _extract_description(cls, soup: BeautifulSoup, objects: Iterable[Any]) -> str:
        selectors = (
            '[itemprop="description"]',
            ".kt-description-row__text",
            '[data-testid="description"]',
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if node and node.get_text(" ", strip=True):
                return node.get_text(" ", strip=True)
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return str(meta["content"]).strip()
        return cls._first_structured_text(objects, cls.DESCRIPTION_KEYS)

    @classmethod
    def _first_structured_text(cls, objects: Iterable[Any], keys: set[str]) -> str:
        def walk(value: Any) -> str:
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized_key = re.sub(r"[^a-z0-9_]", "", str(key).lower())
                    if normalized_key in keys and isinstance(nested, str) and nested.strip():
                        return nested.strip()
                for nested in value.values():
                    found = walk(nested)
                    if found:
                        return found
            elif isinstance(value, list):
                for nested in value:
                    found = walk(nested)
                    if found:
                        return found
            return ""

        for obj in objects:
            found = walk(obj)
            if found:
                return found
        return ""

    @classmethod
    def _extract_account_metadata(
        cls, soup: BeautifulSoup, objects: Iterable[Any]
    ) -> Tuple[Dict[str, Any], List[str]]:
        evidence: List[str] = []
        server_info: Dict[str, Any] = {}

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    norm_key = str(key).lower().replace("-", "_")
                    if norm_key == "is_business" and nested is True:
                        server_info["is_business"] = True
                        evidence.append("dom:is_business=true")
                    elif norm_key in {"agency_id", "business_id"} and nested:
                        server_info[norm_key] = nested
                        evidence.append(f"dom:{norm_key}")
                    elif norm_key in {"business_type", "post_business_type", "account_type"}:
                        business_type = str(nested or "").strip().lower()
                        if business_type:
                            server_info["business_type"] = business_type
                        if business_type in cls.BUSINESS_TYPES:
                            evidence.append(f"dom:{norm_key}={business_type}")
                    if isinstance(nested, (dict, list)):
                        walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        for obj in objects:
            walk(obj)

        for node in soup.find_all(True):
            for attr_name, attr_value in node.attrs.items():
                normalized_attr = attr_name.lower().replace("-", "_")
                if normalized_attr in {
                    "data_business_type",
                    "data_account_type",
                    "data_post_business_type",
                }:
                    raw_value = " ".join(attr_value) if isinstance(attr_value, list) else str(attr_value)
                    business_type = raw_value.strip().lower()
                    if business_type in cls.BUSINESS_TYPES:
                        evidence.append(f"dom:{normalized_attr}={business_type}")

        metadata = {
            "action_log": {"server_side_info": {"info": server_info}},
            "has_business_widget": bool(evidence),
        }
        return metadata, list(dict.fromkeys(evidence))

    @staticmethod
    def _seller_context(soup: BeautifulSoup) -> str:
        texts: List[str] = []
        marker = re.compile(r"seller|advertiser|business|agency|consultant", re.IGNORECASE)
        for node in soup.find_all(True):
            classes = " ".join(node.get("class", []))
            identity = f"{node.get('id', '')} {classes}"
            if marker.search(identity):
                text = node.get_text(" ", strip=True)
                if text and text not in texts:
                    texts.append(text[:500])
            if len(texts) >= 8:
                break
        return " ".join(texts)
