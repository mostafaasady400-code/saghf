"""
تست جامع اعتبارسنجی موتور استخراج چندترده سلنیوم و بیوتیفول‌سوپ
بررسی فیلتر اصالت مالک، پارس HTML، مدیریت تردها و یکپارچگی با سیستم سقف
"""

import unittest
from bs4 import BeautifulSoup

from crawler.selenium_scraper.parser import BeautifulSoupDivarParser
from crawler.selenium_scraper.browser import find_optimal_thread_count, get_chrome_binary_path
from crawler.selenium_scraper.scraper import MultiThreadedDivarScraper
from crawler.schemas import NormalizedPropertySchema


class TestSeleniumDivarScraper(unittest.TestCase):

    def setUp(self):
        # نمونه HTML واقعی از آگهی مالک شخصی دیوار
        self.owner_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="فروش آپارتمان ۱۰۰ متری نوساز پونک" />
            <meta property="og:description" content="فروش آپارتمان ۱۰۰ متری نوساز در پونک. مالک هستم. سند تک برگ شخصی. دسترسی عالی." />
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Apartment",
                "name": "فروش آپارتمان ۱۰۰ متری نوساز پونک",
                "description": "فروش آپارتمان ۱۰۰ متری نوساز در پونک. مالک هستم. سند تک برگ شخصی. دسترسی عالی.",
                "floorSize": {"@type": "QuantitativeValue", "value": "100", "unitCode": "MTK"},
                "numberOfRooms": "دو",
                "url": "https://divar.ir/v/test12345"
            }
            </script>
        </head>
        <body>
            <h1 class="kt-page-title__title kt-page-title__title--responsive-sized">فروش آپارتمان ۱۰۰ متری نوساز پونک</h1>
            <p class="kt-description-row__text">فروش آپارتمان ۱۰۰ متری نوساز در پونک. مالک هستم. سند تک برگ شخصی. دسترسی عالی. 09123456789</p>
            <table>
                <tr class="kt-group-row__data-row">
                    <td><span class="kt-group-row-item__title">متراژ</span><td class="kt-group-row-item">۱۰۰</td></td>
                    <td><span class="kt-group-row-item__title">ساخت</span><td class="kt-group-row-item">۱۴۰۲</td></td>
                    <td><span class="kt-group-row-item__title">اتاق</span><td class="kt-group-row-item">۲</td></td>
                </tr>
            </table>
            <div class="kt-unexpandable-row">
                <p class="kt-unexpandable-row__title">قیمت کل</p>
                <p class="kt-unexpandable-row__value">۱۰٬۰۰۰٬۰۰۰٬۰۰۰ تومان</p>
            </div>
            <div class="kt-unexpandable-row">
                <p class="kt-unexpandable-row__title">قیمت هر متر</p>
                <p class="kt-unexpandable-row__value">۱۰۰٬۰۰۰٬۰۰۰ تومان</p>
            </div>
            <div class="kt-unexpandable-row">
                <p class="kt-unexpandable-row__title">طبقه</p>
                <p class="kt-unexpandable-row__value">۳ از ۵</p>
            </div>
            <div class="kt-group-feature-row__item">آسانسور</div>
            <div class="kt-group-feature-row__item">پارکینگ</div>
            <div class="kt-group-feature-row__item">انباری</div>
        </body>
        </html>
        """

        # نمونه HTML از آگهی مشاور املاک (که باید ۱۰۰٪ رد شود)
        self.agency_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="فروش آپارتمان ۸۵ متری در صادقیه دپارتمان املاک بزرگ" />
        </head>
        <body>
            <h1 class="kt-page-title__title">فروش آپارتمان ۸۵ متری در صادقیه دپارتمان املاک بزرگ</h1>
            <p class="kt-description-row__text">مشاور شما مهندس راد. فایلینگ قوی منطقه ۵. املاک پاسارگاد با بیش از ۱۰ سال سابقه. کمیسیون طبق تعرفه.</p>
            <div class="seller-agency">آژانس املاک پاسارگاد</div>
        </body>
        </html>
        """

    def test_chrome_binary_detection(self):
        """تست یافتن باینری کروم در ویندوز"""
        path = get_chrome_binary_path()
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(".exe"))

    def test_optimal_thread_count(self):
        """تست محاسبه تعداد بهینه تردها با psutil"""
        threads = find_optimal_thread_count()
        self.assertGreaterEqual(threads, 1)
        self.assertLessEqual(threads, 8)

    def test_owner_listing_parsing(self):
        """تست پارس موفق آگهی مالک شخصی و تولید اسکیما با تگ لینک آگهی"""
        schema = BeautifulSoupDivarParser.parse_listing_page(
            html_content=self.owner_html,
            page_url="https://divar.ir/v/test12345",
            city="tehran",
            default_deal_type="sale"
        )
        self.assertIsNotNone(schema)
        self.assertIsInstance(schema, NormalizedPropertySchema)
        self.assertEqual(schema.area, 100)
        self.assertEqual(schema.rooms, 2)
        self.assertEqual(schema.build_year, 1402)
        self.assertEqual(schema.floor, 3)
        self.assertTrue(schema.has_elevator)
        self.assertTrue(schema.has_parking)
        self.assertTrue(schema.has_warehouse)
        self.assertTrue(schema.is_personal_owner)
        self.assertEqual(schema.owner_type, "personal")
        self.assertIn("09123456789", schema.owner_info.phone)
        self.assertIn("لینک آگهی", schema.owner_info.notes)
        self.assertIn("https://divar.ir/v/test12345", schema.source_url)

    def test_agency_listing_rejection(self):
        """تست گیت رد قطعی آگهی‌های دارای کلیدواژه‌های املاکی و مشاور"""
        schema = BeautifulSoupDivarParser.parse_listing_page(
            html_content=self.agency_html,
            page_url="https://divar.ir/v/agency_ad_123",
            city="tehran",
            default_deal_type="sale"
        )
        # باید به عنوان املاکی/غیرشخصی رد شده و None برگرداند
        self.assertIsNone(schema)

    def test_scraper_search_url_builder(self):
        """تست تولید URLهای فیلترشده جستجوی دیوار"""
        scraper = MultiThreadedDivarScraper(city="tehran", thread_count=2)
        url = scraper.build_search_url(
            category_key="buy-apartment",
            district_slug="punak",
            min_price=5000000000,
            max_price=12000000000,
            min_area=80,
            max_area=120,
            rooms=2,
            has_parking=True,
            has_elevator=True
        )
        self.assertIn("https://divar.ir/s/tehran/buy-apartment/punak", url)
        self.assertIn("price=5000000000-12000000000", url)
        self.assertIn("size=80-120", url)
        self.assertIn("rooms=2-", url)
        self.assertIn("has-parking=true", url)
        self.assertIn("has-elevator=true", url)

    def test_extract_links_from_soup(self):
        """تست استخراج لینک‌های /v/ با BeautifulSoup"""
        scraper = MultiThreadedDivarScraper(city="tehran", thread_count=2)
        sample_page = """
        <div>
            <a href="/v/ad1/abc123">آگهی ۱</a>
            <a href="/s/tehran/buy-apartment">دسته‌بندی</a>
            <a href="/v/ad2/def456">آگهی ۲</a>
            <a href="https://divar.ir/v/ad3/ghi789">آگهی ۳</a>
        </div>
        """
        links, count = scraper.extract_links_from_soup(sample_page, set())
        self.assertEqual(count, 3)
        self.assertIn("https://divar.ir/v/ad1/abc123", links)
        self.assertIn("https://divar.ir/v/ad2/def456", links)
        self.assertIn("https://divar.ir/v/ad3/ghi789", links)


if __name__ == "__main__":
    unittest.main()
