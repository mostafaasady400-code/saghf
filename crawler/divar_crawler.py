"""
کراولر پیشرفته و منعطف پلتفرم دیوار برای استخراج فایل‌های ملکی سقف
پشتیبانی از دو موتور قدرتمند:
۱. موتور استخراج چندترده با سلنیوم و بیوتیفول‌سوپ (Selenium Multi-Threaded Engine)
۲. موتور هیبریدی فینگرپرینتینگ TLS (HybridDivarCrawler)
بدون هرگونه دیتای ماک/فیک و با رعایت ۱۰۰٪ فیلتر مالک مستقیم
"""

import re
import json
import time
import random
from typing import List, Dict, Any, Optional

from .schemas import (
    NormalizedPropertySchema,
    persian_to_english_numbers,
    parse_price,
    parse_area
)
from .selenium_scraper.scraper import MultiThreadedDivarScraper
from .selenium_scraper.browser import find_optimal_thread_count


def clean_number(text: Any) -> int:
    if not text:
        return 0
    text = persian_to_english_numbers(str(text))
    nums = re.findall(r'\d+', text.replace(',', '').replace('،', ''))
    if nums:
        return int(''.join(nums))
    return 0


class DivarCrawler:
    """
    کراولر مدرن دیوار با استخراج چندترده و فیلتر ۱۰۰٪ مالک شخصی
    """

    CATEGORIES = {
        'buy-apartment': {'slug': 'buy-apartment', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'فروش آپارتمان'},
        'rent-apartment': {'slug': 'rent-apartment', 'deal_type': 'rent', 'property_type': 'apartment', 'name': 'اجاره آپارتمان'},
        'buy-residential': {'slug': 'buy-residential', 'deal_type': 'sale', 'property_type': 'villa', 'name': 'فروش مسکونی و ویلایی'},
        'rent-residential': {'slug': 'rent-residential', 'deal_type': 'rent', 'property_type': 'villa', 'name': 'اجاره مسکونی و ویلایی'},
        'commercial-sell': {'slug': 'commercial-sell', 'deal_type': 'sale', 'property_type': 'commercial', 'name': 'فروش تجاری و مغازه'},
        'commercial-rent': {'slug': 'commercial-rent', 'deal_type': 'rent', 'property_type': 'commercial', 'name': 'اجاره اداری و تجاری'}
    }

    def __init__(self, city: str = 'tehran'):
        self.city = city

    def fetch_listings(
        self,
        category_key: str = 'buy-apartment',
        limit: int = 25,
        use_selenium: bool = False,
        threads: Optional[int] = None,
        district_slug: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        on_item_found: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        استخراج آگهی‌های واقعی دیوار
        در صورت انتخاب use_selenium=True، خط لوله چندترده سلنیوم و BeautifulSoup فعال می‌شود.
        در غیر این صورت، از موتور هیبریدی TLS سقف استفاده می‌گردد.
        """
        if use_selenium:
            return self.fetch_with_selenium(
                category_key=category_key,
                limit=limit,
                threads=threads,
                district_slug=district_slug,
                filters=filters,
                on_item_found=on_item_found
            )

        # استخراج از موتور هیبریدی TLS سقف
        try:
            from .hybrid_divar import HybridDivarCrawler
            hybrid = HybridDivarCrawler(city=self.city)
            schemas = hybrid.fetch_listings(
                category_key=category_key,
                limit=limit,
                districts=[district_slug] if district_slug else None,
                on_item_found=on_item_found
            )
            return [s.model_dump() for s in schemas]
        except Exception as e:
            print(f"[DivarCrawler] خطای استخراج هیبریدی ({e})، فعال‌سازی خودکار موتور چندترده سلنیوم...")
            return self.fetch_with_selenium(
                category_key=category_key,
                limit=limit,
                threads=threads,
                district_slug=district_slug,
                filters=filters,
                on_item_found=on_item_found
            )

    def fetch_with_selenium(
        self,
        category_key: str = 'buy-apartment',
        limit: int = 25,
        threads: Optional[int] = None,
        district_slug: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        on_item_found: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        استخراج صددرصد زنده و خودکار با موتور چندترده Selenium و BeautifulSoup
        بدون دیتای فیک و با تضمین مالک شخصی
        """
        thread_num = threads or find_optimal_thread_count()
        scraper = MultiThreadedDivarScraper(
            city=self.city,
            thread_count=thread_num
        )

        schemas: List[NormalizedPropertySchema] = scraper.run_multi_threaded_extraction(
            category_key=category_key,
            district_slug=district_slug,
            target_count=limit,
            filters=filters,
            on_item_found=on_item_found
        )

        return [s.model_dump() for s in schemas]
