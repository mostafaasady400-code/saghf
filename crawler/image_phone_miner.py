"""
Image Phone Miner for Saghf Platform.
Extracts phone numbers written inside listing images, watermark notes, or photos.
Operates with zero quota consumption and pluggable OCR engine support.
"""

from __future__ import annotations

import io
import re
import logging
from typing import Dict, Any, List, Optional, Callable
from PIL import Image

from crawler.contact_extractor import ContactExtractor
from crawler.text_phone_miner import TextPhoneMiner

logger = logging.getLogger(__name__)


class ImagePhoneMiner:
    """
    موتور تصویرکاو استخراج شماره تلفن از عکس‌های آگهی.
    پشتیبانی از پردازش ابری، محلی، فیلتر عکس‌های فاقد متن و ادغام مستقیم با ContactExtractor.
    """

    _ocr_engine: Optional[Callable[[Image.Image], str]] = None

    @classmethod
    def register_ocr_engine(cls, engine: Callable[[Image.Image], str]):
        """ثبت موتور OCR سفارشی (مانند Tesseract، EasyOCR یا Cloud OCR)"""
        cls._ocr_engine = engine

    @classmethod
    def is_ocr_available(cls) -> bool:
        """بررسی فعال بودن موتور استخراج متن از تصویر"""
        if cls._ocr_engine is not None:
            return True
        try:
            import pytesseract
            return True
        except ImportError:
            return False

    @classmethod
    def extract_text_from_image(cls, image: Image.Image) -> str:
        """اجرای OCR روی شیء تصویر Pillow"""
        if cls._ocr_engine is not None:
            try:
                return cls._ocr_engine(image)
            except Exception as e:
                logger.warning(f"[ImagePhoneMiner] خطای موتور OCR سفارشی: {e}")
                return ""

        try:
            import pytesseract
            # پیش‌پردازش استاندارد: تبدیل به حالت سیاه‌وسفید و افزایش کنتراست
            gray = image.convert('L')
            text = pytesseract.image_to_string(gray, lang='fas+eng')
            return text
        except Exception as e:
            logger.debug(f"[ImagePhoneMiner] Tesseract در دسترس نیست یا با خطا مواجه شد: {e}")
            return ""

    @classmethod
    def process_image_bytes(cls, image_bytes: bytes) -> Optional[Dict[str, Any]]:
        """پردازش بایت‌های تصویر و استخراج شماره تلفن ایرانی در صورت وجود"""
        if not image_bytes or len(image_bytes) < 100:
            return None

        try:
            img = Image.open(io.BytesIO(image_bytes))
            raw_text = cls.extract_text_from_image(img)
            if not raw_text:
                return None

            # بهره‌گیری از هوش TextPhoneMiner برای کشف ارقام استتار شده
            mined = TextPhoneMiner.mine_phone(raw_text)
            if mined and mined.get('is_valid'):
                return {
                    'phone': mined['phone'],
                    'operator': mined.get('operator'),
                    'source': 'image_ocr',
                    'confidence': 90,
                    'is_valid': True
                }
        except Exception as e:
            logger.warning(f"[ImagePhoneMiner] خطا در پردازش تصویر: {e}")

        return None

    @classmethod
    def scan_image_urls(cls, urls: List[str], timeout: float = 4.0) -> Optional[Dict[str, Any]]:
        """
        اسکن لیست URLهای مستقیم CDN تصاویر یک ملک جهت یافتن شماره پنهان‌شده در عکس‌ها.
        """
        if not urls or not cls.is_ocr_available():
            return None

        import requests

        for idx, url in enumerate(urls[:5]):  # بررسی حداکثر ۵ تصویر اول جهت بهینه‌سازی سرعت
            if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
                continue
            try:
                resp = requests.get(url, timeout=timeout)
                if resp.status_code == 200:
                    found = cls.process_image_bytes(resp.content)
                    if found:
                        found['image_index'] = idx
                        found['image_url'] = url
                        return found
            except Exception as e:
                logger.debug(f"[ImagePhoneMiner] خطا در دانلود تصویر {url}: {e}")

        return None
