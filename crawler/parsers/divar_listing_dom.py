"""Nullable, source-faithful metadata from a rendered Divar property page."""
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from crawler.contact_extractor import ContactExtractor
from crawler.schemas import parse_price


def parse_listing_metadata(html):
    soup = BeautifulSoup(html, "html.parser")
    result = {"images": [], "features": []}
    descriptions = soup.select('[class^="description-"] .kt-description-row__text')
    if descriptions:
        result["description"] = " ".join(n.get_text(" ", strip=True) for n in descriptions)
    for image in soup.select("img[src]"):
        url = image.get("src", "")
        host = (urlsplit(url).hostname or "").lower()
        if urlsplit(url).scheme == "https" and (host == "divarcdn.com" or host.endswith(".divarcdn.com")) and url not in result["images"]:
            result["images"].append(url)
    for group in soup.select(".kt-group-row"):
        titles = group.select(".kt-group-row-item__title")
        values = group.select(".kt-group-row-item__value")
        if len(titles) != len(values):
            continue
        for title, value in zip(titles, values):
            label = title.get_text(" ", strip=True)
            raw = ContactExtractor.normalize_persian_digits(value.get_text(" ", strip=True))
            match = re.search(r"\d+(?:\.\d+)?", raw)
            if not match:
                continue
            if "متراژ" in label:
                result["area"] = float(match.group())
            elif "اتاق" in label:
                result["rooms"] = int(float(match.group()))
    for row in soup.select(".kt-unexpandable-row"):
        title = row.select_one(".kt-unexpandable-row__title")
        value = row.select_one(".kt-unexpandable-row__value")
        if not title or not value:
            continue
        label = title.get_text(" ", strip=True)
        raw = value.get_text(" ", strip=True)
        if not re.search(r"\d", ContactExtractor.normalize_persian_digits(raw)):
            continue
        amount = parse_price(raw)
        if "ودیعه" in label or "رهن" in label:
            result["deposit"] = amount
        elif "اجاره" in label:
            result["monthly_rent"] = amount
        elif "قیمت کل" in label:
            result["total_price"] = amount
    return result
