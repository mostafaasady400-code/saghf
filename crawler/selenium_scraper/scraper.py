"""
موتور اصلی استخراج چندترده دیوار با سلنیوم و بیوتیفول‌سوپ
(Multi-Threaded Divar Property Scraper)
ترکیب اسکرول خودکار هوشمند، توزیع بار در صف Thread-safe، پارس پرسرعت HTML و گیت اعتبارسنجی سقف
"""

import os
import sys
import time
import random
import queue
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Set, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup
import csv

from .browser import create_headless_driver, find_optimal_thread_count
from .parser import BeautifulSoupDivarParser
from crawler.schemas import NormalizedPropertySchema
from crawler.dedup import dedup_engine

logger = logging.getLogger("DivarSeleniumScraper")
logger.setLevel(logging.INFO)


class MultiThreadedDivarScraper:
    """
    موتور استخراج هم‌روند و چندترده آگهی‌های دیوار با Selenium و BeautifulSoup
    """

    CATEGORIES = {
        'buy-apartment': {'slug': 'buy-apartment', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'فروش آپارتمان'},
        'rent-apartment': {'slug': 'rent-apartment', 'deal_type': 'rent', 'property_type': 'apartment', 'name': 'اجاره آپارتمان'},
        'buy-residential': {'slug': 'buy-residential', 'deal_type': 'sale', 'property_type': 'villa', 'name': 'فروش مسکونی و ویلایی'},
        'rent-residential': {'slug': 'rent-residential', 'deal_type': 'rent', 'property_type': 'villa', 'name': 'اجاره مسکونی و ویلایی'},
    }

    def __init__(
        self,
        city: str = "tehran",
        thread_count: Optional[int] = None,
        csv_output_path: Optional[str] = None
    ):
        self.city = city
        self.thread_count = thread_count or find_optimal_thread_count(max_cap=6)
        self.csv_output_path = csv_output_path or "divar_properties.csv"
        self.link_queue: queue.Queue = queue.Queue()
        self.results: List[NormalizedPropertySchema] = []
        self.results_lock = threading.Lock()
        self.processed_count = 0
        self.process_lock = threading.Lock()
        self.stop_signal = threading.Event()

    def build_search_url(
        self,
        category_key: str = 'buy-apartment',
        district_slug: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        rooms: Optional[int] = None,
        has_parking: Optional[bool] = None,
        has_elevator: Optional[bool] = None
    ) -> str:
        """ساخت آدرس جستجوی پیشرفته در دیوار با فیلترها"""
        cat_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        slug = cat_meta['slug']

        path = f"https://divar.ir/s/{self.city}/{slug}"
        if district_slug:
            path += f"/{district_slug}"

        query_params = []
        deal_type = cat_meta['deal_type']

        if deal_type == 'rent':
            if min_price or max_price:
                query_params.append(f"credit={min_price or 0}-{max_price or ''}")
        else:
            if min_price or max_price:
                query_params.append(f"price={min_price or 0}-{max_price or ''}")

        if min_area or max_area:
            query_params.append(f"size={min_area or 0}-{max_area or ''}")

        if rooms:
            query_params.append(f"rooms={rooms}-")
        if has_parking:
            query_params.append("has-parking=true")
        if has_elevator:
            query_params.append("has-elevator=true")

        if query_params:
            path += "?" + "&".join(query_params)
        return path

    def extract_links_from_soup(self, html_source: str, existing_links: Set[str]) -> Tuple[Set[str], int]:
        """استخراج سریع لینک‌های آگهی (/v/) و توکن‌های آبجکت __PRELOADED_STATE__ با بیوتیفول‌سوپ"""
        new_links_count = 0

        # ۱. استخراج از __PRELOADED_STATE__ با فیلتر اولیه آژانس‌های املاک
        try:
            m = re.search(r'(?:window\.)?__PRELOADED_STATE__\s*=\s*(\{.+?\});?(?:\s*</script>|\s*$)', html_source)
            if m:
                state_data = json.loads(m.group(1))
                widgets = state_data.get('nb', {}).get('listWidgets', [])
                if not widgets:
                    browse = state_data.get('browse', {}) or {}
                    widgets = browse.get('postList') or browse.get('items') or []

                for w in widgets:
                    dto = w.get('data', {}).get('dto', {}) if isinstance(w, dict) else {}
                    d = dto.get('data', {}) if dto else (w.get('data', {}) if isinstance(w, dict) else {})
                    action = d.get('action', {}) or {}
                    token = d.get('token') or action.get('payload', {}).get('token')
                    bottom_desc = d.get('bottom_description_text') or d.get('bottom_description_sub_title') or ''

                    # پیش‌فیلتر آگهی‌های دارای بج مشاور و آژانس
                    is_agency_badge = any(k in bottom_desc for k in ['املاک', 'آژانس', 'دپارتمان', 'مسکن', 'مشاور', 'بنگاه'])
                    if token and not is_agency_badge:
                        full_url = f"https://divar.ir/v/{token}"
                        if full_url not in existing_links:
                            existing_links.add(full_url)
                            new_links_count += 1
        except Exception:
            pass

        # ۲. استخراج تگ‌های <a> از ساختار DOM با BeautifulSoup
        soup = BeautifulSoup(html_source, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/v/" in href:
                full_url = f"https://divar.ir{href}" if href.startswith("/") else href
                token = full_url.rstrip("/").split("/")[-1]
                if len(token) >= 6 and full_url not in existing_links:
                    existing_links.add(full_url)
                    new_links_count += 1

        return existing_links, new_links_count

    def scroll_and_collect_links(
        self,
        target_url: str,
        target_count: int = 50,
        max_scrolls: int = 30
    ) -> List[str]:
        """
        اسکرول چندمرحله‌ای هوشمند با سلنیوم برای جمع‌آوری لینک‌های آگهی
        همراه با بستن خودکار پاپ‌آپ‌ها، اسکرول کانتینرهای مجازی و استخراج چندمنطقه‌ای
        """
        driver = None
        collected_links: Set[str] = set()

        # اولویت‌بندی جستجو با کوئری‌های مالک مستقیم و توزیع محله‌ای
        base_category = target_url.split('?')[0].rstrip('/')
        target_urls = [
            f"{base_category}?q=مالک",
            f"{base_category}?q=بی+واسطه",
            f"{base_category}?q=شخصی",
            target_url
        ]

        if not any(d in target_url for d in ['punak', 'saadat-abad', 'ferdows', 'tehranpars', 'shahrak-e-gharb']):
            districts = ['tehranpars', 'saadat-abad', 'punak', 'ferdows', 'shahrak-e-gharb', 'gisha', 'marzdaran']
            for d in districts:
                target_urls.append(f"{base_category}/{d}")

        try:
            driver = create_headless_driver(page_load_timeout=25, block_media=True)
            driver.set_window_size(1920, 1080)

            for cur_url in target_urls:
                if len(collected_links) >= target_count or self.stop_signal.is_set():
                    break

                print(f"\n[Selenium] در حال باز کردن صفحه جستجو: {cur_url}")
                try:
                    driver.get(cur_url)
                except TimeoutException:
                    try:
                        driver.execute_script("window.stop();")
                    except Exception:
                        pass
                except Exception as ex:
                    logger.warning(f"Error loading {cur_url}: {ex}")
                    continue

                # بستن هرگونه مدال یا پاپ‌آپ انتخاب محله با ESC
                time.sleep(1.5)
                try:
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                except Exception:
                    pass

                # استخراج اولیه
                collected_links, new_found = self.extract_links_from_soup(driver.page_source, collected_links)
                print(f"[Selenium] لینک‌های اولیه این صفحه: {new_found} | کل جمع‌آوری‌شده: {len(collected_links)}/{target_count}")

                # اسکرول هوشمند در صفحه جاری
                consecutive_zero = 0
                for scroll_idx in range(max_scrolls):
                    if len(collected_links) >= target_count or self.stop_signal.is_set():
                        break

                    # اسکرول همزمان بادی، پنجره و کانتینر محتوا
                    try:
                        driver.execute_script("""
                            window.scrollTo(0, document.body.scrollHeight);
                            document.querySelectorAll('div[class*="content"]').forEach(el => el.scrollTop += 3000);
                        """)
                        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
                    except Exception:
                        pass

                    time.sleep(random.uniform(0.8, 1.4))

                    collected_links, new_found = self.extract_links_from_soup(driver.page_source, collected_links)
                    print(
                        f"\r[Selenium] استخراج لینک‌ها: {len(collected_links)}/{target_count} | "
                        f"جدید: +{new_found} | اسکرول: {scroll_idx + 1}/{max_scrolls}",
                        end="",
                        flush=True
                    )

                    if new_found == 0:
                        consecutive_zero += 1
                        if consecutive_zero >= 4:
                            break
                    else:
                        consecutive_zero = 0

            print(f"\n[Selenium] جمع‌آوری لینک‌ها به پایان رسید: {len(collected_links)} لینک استخراج شد.")
            return list(collected_links)[:target_count]

        except Exception as e:
            print(f"\n[Selenium] خطای جمع‌آوری لینک‌ها: {e}")
            return list(collected_links)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    def _worker_task(
        self,
        deal_type: str,
        property_type: str,
        on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None
    ):
        """وظیفه هر ترد در پردازش موازی لینک‌های آگهی دیوار با سرعت بالا و فیلتر ۱۰۰٪ مالک"""
        import requests
        from crawler.parsers.divar_parser import DivarStructuredParser
        from crawler.owner_filter import OwnerFilter

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'fa-IR,fa;q=0.9,en-US;q=0.8'
        }

        while not self.stop_signal.is_set():
            try:
                link = self.link_queue.get(timeout=2)
            except queue.Empty:
                break

            try:
                token = link.rstrip("/").split("/")[-1]
                source_id = f"divar_{token}"

                # فیلتر تکراری‌ها
                if dedup_engine.is_duplicate(source_id):
                    with self.process_lock:
                        self.processed_count += 1
                    self.link_queue.task_done()
                    continue

                schema = None
                api_url = f"https://api.divar.ir/v8/posts-v2/web/{token}"

                try:
                    r = requests.get(api_url, headers=headers, timeout=6)
                    if r.status_code == 200:
                        post_json = r.json()

                        # ۱. بررسی اولیه نوع حساب در وب‌انگیج دیوار
                        we = post_json.get('webengage', {}) or {}
                        biz_type = str(we.get('business_type', '')).lower()
                        if biz_type in ['premium-panel', 'business', 'agency', 'consultant']:
                            # رد آنی مشاوران و پنل‌های املاکی
                            with self.process_lock:
                                self.processed_count += 1
                            self.link_queue.task_done()
                            continue

                        # ۲. پارس درخت ویجت‌ها با DivarStructuredParser
                        parsed = DivarStructuredParser.parse_widget_tree(post_json)
                        if parsed.get('is_agency') or parsed.get('is_agency_post'):
                            with self.process_lock:
                                self.processed_count += 1
                            self.link_queue.task_done()
                            continue

                        title = parsed.get('title') or post_json.get('seo', {}).get('title', '')
                        desc = parsed.get('description') or post_json.get('seo', {}).get('description', '')

                        # ۳. فیلتر قاطع مالک شخصی با OwnerFilter طبق اساسنامه سقف
                        eval_res = OwnerFilter.evaluate(
                            platform='divar',
                            title=title,
                            description=desc
                        )

                        if not eval_res.is_personal:
                            with self.process_lock:
                                self.processed_count += 1
                            self.link_queue.task_done()
                            continue

                        # گیت نهایی بررسی واژه‌های مشاور و بنگاه در عنوان و توضیحات
                        combined = f"{title} {desc}"
                        has_broker_word = any(w in combined for w in [
                            'املاک', 'املاکی', 'املاك', 'مسکن', 'مسكن', 'مشاور', 'مشاوران',
                            'مشاورین', 'آژانس', 'دپارتمان', 'بنگاه', 'کارشناس', 'کمیسیون', 'حق الزحمه'
                        ])
                        if has_broker_word:
                            with self.process_lock:
                                self.processed_count += 1
                            self.link_queue.task_done()
                            continue

                        # ۴. استخراج تلفن و شهر/محله
                        district_name = post_json.get('district') or self.city
                        from crawler.owner_filter import extract_phone_number
                        phone = extract_phone_number(combined)

                        # ساخت اسکیما با لینک مستقیم و تگ <a> الزامی
                        schema = NormalizedPropertySchema(
                            source="divar",
                            source_id=source_id,
                            source_url=link,
                            title=title,
                            deal_type=deal_type,
                            property_type=property_type,
                            city=self.city,
                            district=district_name,
                            address=f"{self.city}، {district_name}",
                            total_price=parsed.get('total_price', 0),
                            meter_price=parsed.get('meter_price', 0),
                            deposit=parsed.get('deposit', 0),
                            monthly_rent=parsed.get('monthly_rent', 0),
                            area=parsed.get('area', 80),
                            rooms=parsed.get('rooms', 1),
                            floor=parsed.get('floor', 1),
                            total_floors=parsed.get('total_floors'),
                            build_year=parsed.get('build_year', 1400),
                            has_elevator=parsed.get('has_elevator', False),
                            has_parking=parsed.get('has_parking', False),
                            has_warehouse=parsed.get('has_warehouse', False),
                            has_balcony=parsed.get('has_balcony', False),
                            features=parsed.get('features', []),
                            description=desc,
                            images=parsed.get('images', [])[:8],
                            status="raw_crawled",
                            score=95 if phone else 85,
                            is_personal_owner=True,
                            owner_type="personal",
                            filter_log="استخراج چندترده و فیلتر ۱۰۰٪ مالک شخصی دیوار",
                            owner_info={
                                "name": f"مالک آگهی ({district_name})",
                                "phone": phone or "",
                                "urgency": "high",
                                "flexibility": "moderate",
                                "notes": f'<a href="{link}" target="_blank">لینک آگهی</a>'
                            }
                        )
                except Exception as req_ex:
                    logger.debug(f"HTTP parse failed for {link}: {req_ex}")

                # در صورت موفقیت، ذخیره و اعلان به متد فراخواننده
                if schema:
                    with self.results_lock:
                        self.results.append(schema)
                    if on_item_found:
                        try:
                            on_item_found(schema)
                        except Exception as ex:
                            logger.error(f"Error in on_item_found callback: {ex}")

                with self.process_lock:
                    self.processed_count += 1

                time.sleep(random.uniform(0.1, 0.25))

            except Exception as ex:
                logger.warning(f"Error processing {link}: {ex}")
                with self.process_lock:
                    self.processed_count += 1
            finally:
                try:
                    self.link_queue.task_done()
                except Exception:
                    pass

    def run_multi_threaded_extraction(
        self,
        category_key: str = 'buy-apartment',
        district_slug: Optional[str] = None,
        target_count: int = 30,
        filters: Optional[Dict[str, Any]] = None,
        on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None
    ) -> List[NormalizedPropertySchema]:
        """
        اجرای خط لوله کامل استخراج چندترده (End-to-End Multi-Threaded Pipeline):
        ۱. اسکرول و جمع‌آوری لینک‌ها
        ۲. صف کار و راه‌اندازی استخر تردهای همزمان
        ۳. ذخیره نهایی و گزارش آماری
        """
        filters = filters or {}
        cat_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        deal_type = cat_meta['deal_type']
        property_type = cat_meta['property_type']

        target_url = self.build_search_url(
            category_key=category_key,
            district_slug=district_slug,
            min_price=filters.get('min_price'),
            max_price=filters.get('max_price'),
            min_area=filters.get('min_area'),
            max_area=filters.get('max_area'),
            rooms=filters.get('rooms'),
            has_parking=filters.get('has_parking'),
            has_elevator=filters.get('has_elevator')
        )

        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"🚀 شروع استخراج چندترده دیوار با سلنیوم و BeautifulSoup")
        print(f"شهر: {self.city} | دسته‌بندی: {cat_meta['name']} | هدف: {target_count} فایل مالک شخصی")
        print(f"تعداد تردهای موازی: {self.thread_count}")
        print(f"{'='*60}")

        # مرحله ۱: جمع‌آوری لینک‌ها
        # برای رسیدن به target_count آگهی مالک شخصی، به تعداد کافی لینک نیاز داریم تا فیلتر سخت‌گیرانه مشاوران اعمال شود
        needed_links = max(target_count * 4, 120)
        links = self.scroll_and_collect_links(target_url, target_count=needed_links)

        if not links:
            print("[MultiThreadedDivarScraper] هیچ لینکی یافت نشد.")
            return []

        # پر کردن صف کارها
        for l in links:
            self.link_queue.put(l)

        total_links = self.link_queue.qsize()
        print(f"[MultiThreadedDivarScraper] {total_links} لینک در صف پردازش تردهای موازی قرار گرفت.")

        # مرحله ۲: راه‌اندازی تردهای موازی
        threads = []
        for i in range(self.thread_count):
            t = threading.Thread(
                target=self._worker_task,
                args=(deal_type, property_type, on_item_found),
                name=f"SeleniumWorker-{i+1}",
                daemon=True
            )
            t.start()
            threads.append(t)

        # نظارت زنده بر پیشرفت کار
        while not self.link_queue.empty() and any(t.is_alive() for t in threads):
            with self.process_lock:
                curr = self.processed_count
            with self.results_lock:
                approved = len(self.results)

            elapsed = max(1.0, time.time() - start_time)
            speed = curr / elapsed
            print(
                f"\r[پردازش چندترده] پردازش: {curr}/{total_links} | "
                f"فایل‌های شخصی تأییدشده: {approved}/{target_count} | "
                f"سرعت: {speed:.1f} آگهی/ثانیه",
                end="",
                flush=True
            )

            if approved >= target_count:
                print(f"\n[MultiThreadedDivarScraper] به سقف درخواستی ({target_count} فایل شخصی) رسیدیم!")
                self.stop_signal.set()
                break

            time.sleep(1.0)

        # اتمام صف
        self.link_queue.join()
        for t in threads:
            t.join(timeout=2)

        # مرتب‌سازی زمانی و امتیازی
        with self.results_lock:
            self.results.sort(key=lambda x: x.score, reverse=True)
            final_res = list(self.results)[:target_count]

        total_time = time.time() - start_time
        print(f"\n{'-'*60}")
        print(f"✅ فرآیند استخراج چندترده تکمیل شد:")
        print(f"کل آگهی‌های بررسی‌شده: {self.processed_count}")
        print(f"تعداد آگهی‌های شخصی و مالک مستقیم: {len(final_res)}")
        print(f"مدت زمان: {total_time:.2f} ثانیه")
        print(f"{'-'*60}")

        # ذخیره در CSV در صورت مشخص بودن مسیر
        if self.csv_output_path and final_res:
            self.save_to_csv(final_res, self.csv_output_path)

        return final_res

    def save_to_csv(self, items: List[NormalizedPropertySchema], filepath: str):
        """ذخیره نتایج تمیز در قالب CSV استاندارد مطابق ریپازیتوری مرجع بدون وابستگی به پکیج‌های سنگین"""
        if not items:
            return
        fieldnames = [
            "Title", "Area", "Total Price", "Price per Meter", "Deposit", "Monthly Rent",
            "Room Count", "Build Year", "Floor Number", "District", "Description",
            "URL", "Owner Phone", "Timestamp"
        ]
        try:
            file_exists = os.path.exists(filepath) and os.path.getsize(filepath) > 0
            with open(filepath, mode="a" if file_exists else "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                for item in items:
                    writer.writerow({
                        "Title": item.title,
                        "Area": item.area,
                        "Total Price": item.total_price,
                        "Price per Meter": item.meter_price,
                        "Deposit": item.deposit,
                        "Monthly Rent": item.monthly_rent,
                        "Room Count": item.rooms,
                        "Build Year": item.build_year,
                        "Floor Number": item.floor,
                        "District": item.district,
                        "Description": item.description,
                        "URL": item.source_url,
                        "Owner Phone": item.owner_info.phone if item.owner_info else "",
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
            print(f"[CSV] نتایج با موفقیت در {filepath} ذخیره شد.")
        except Exception as e:
            logger.error(f"Error saving to CSV: {e}")
