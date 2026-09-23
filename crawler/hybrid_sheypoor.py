import re
import random
import time
from urllib.parse import unquote, quote
from typing import List, Dict, Any, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
from .network.impersonator import TLSImpersonatorClient
from .network.rate_limiter import TokenBucketRateLimiter
from .network.proxy_manager import ProxyManager
from .dedup import dedup_engine
from .fallback_solver import fallback_solver
from .schemas import NormalizedPropertySchema, OwnerSchema, parse_price, persian_to_english_numbers, sanitize_property_financials
from .owner_filter import OwnerFilter, extract_phone_number

def is_older_than_5_days(text: str) -> bool:
    """بررسی اینکه آگهی متعلق به بیش از ۵ روز گذشته است یا خیر"""
    if not text:
        return False
    older_markers = ['۶ روز پیش', '۷ روز پیش', 'هفته پیش', 'هفتهٔ پیش', '۲ هفته پیش', '۳ هفته پیش', 'ماه پیش', '۱ ماه پیش', '۲ ماه پیش']
    for m in older_markers:
        if m in text:
            return True
    return False

class HybridSheypoorCrawler:
    """
    کراولر هیبریدی شیپور با فیلتر هوشمند دومرحله‌ای و استخراج عمیق اختصاصی آگهی‌های شخصی
    مجهز به استخراج بلادرنگ متن کامل آگهی، تمام تصاویر با کیفیت اصلی و حذف قطعی مشاورین و واسطه‌ها
    پایپلاین همروند غیرهمزمان جهت سرعت فوق‌العاده
    """
    BASE_WEB_URL = "https://www.sheypoor.com/s"

    CATEGORIES = {
        'buy-apartment': {'slug': 'iran/tehran/real-estate/apartments-for-sale', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'خرید آپارتمان'},
        'rent-apartment': {'slug': 'iran/tehran/real-estate/apartments-for-rent', 'deal_type': 'rent', 'property_type': 'apartment', 'name': 'رهن و اجاره آپارتمان'},
        'buy-residential': {'slug': 'iran/tehran/real-estate/houses-villas-for-sale', 'deal_type': 'sale', 'property_type': 'villa', 'name': 'خرید ویلا و کلنگی'},
        'rent-residential': {'slug': 'iran/tehran/real-estate/houses-villas-for-rent', 'deal_type': 'rent', 'property_type': 'villa', 'name': 'اجاره خانه و ویلا'},
        'commercial-sell': {'slug': 'iran/tehran/real-estate/commercial-properties-for-sale', 'deal_type': 'sale', 'property_type': 'commercial', 'name': 'خرید اداری و تجاری'},
        'commercial-rent': {'slug': 'iran/tehran/real-estate/commercial-properties-for-rent', 'deal_type': 'rent', 'property_type': 'commercial', 'name': 'اجاره اداری و تجاری'}
    }

    MAX_CRAWL_DURATION = 16
    CONCURRENCY_WORKERS = 5

    def __init__(self, city: str = 'tehran', proxy_manager: Optional[ProxyManager] = None):
        self.city = city
        self.proxy_manager = proxy_manager or ProxyManager()
        self.rate_limiter = TokenBucketRateLimiter(capacity=3, fill_rate=1.5)
        self.client = TLSImpersonatorClient(
            impersonate="chrome120",
            proxy=self.proxy_manager.get_proxy()
        )

    def fetch_listings(
        self,
        category_key: str = 'buy-apartment',
        limit: int = 50,
        query: Optional[str] = None,
        max_pages: int = 15,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        min_deposit: Optional[int] = None,
        max_deposit: Optional[int] = None,
        min_rent: Optional[int] = None,
        max_rent: Optional[int] = None,
        min_area: Optional[int] = None,
        max_area: Optional[int] = None,
        min_year: Optional[int] = None,
        max_year: Optional[int] = None,
        min_age: Optional[int] = None,
        max_age: Optional[int] = None,
        rooms: Optional[int] = None,
        has_parking: Optional[bool] = None,
        has_elevator: Optional[bool] = None,
        has_warehouse: Optional[bool] = None,
        has_balcony: Optional[bool] = None,
        on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None
    ) -> List[NormalizedPropertySchema]:
        category_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        slug = category_meta['slug']
        all_results: List[NormalizedPropertySchema] = []

        current_shamsi = 1403
        if max_age is not None:
            calc_min_y = current_shamsi - int(max_age)
            min_year = max(min_year or 0, calc_min_y)
        if min_age is not None:
            calc_max_y = current_shamsi - int(min_age)
            max_year = min(max_year or 9999, calc_max_y) if max_year else calc_max_y

        filters = {
            'min_price': min_price,
            'max_price': max_price,
            'min_deposit': min_deposit,
            'max_deposit': max_deposit,
            'min_rent': min_rent,
            'max_rent': max_rent,
            'min_area': min_area,
            'max_area': max_area,
            'min_year': min_year,
            'max_year': max_year,
            'min_age': min_age,
            'max_age': max_age,
            'rooms': rooms,
            'has_parking': has_parking,
            'has_elevator': has_elevator,
            'has_warehouse': has_warehouse,
            'has_balcony': has_balcony,
        }

        for page in range(1, max_pages + 1):
            if len(all_results) >= limit:
                break

            params = []
            if page > 1:
                params.append(f"p={page}")
            if query:
                params.append(f"q={quote(query)}")

            query_string = f"?{'&'.join(params)}" if params else ""
            url = f"{self.BASE_WEB_URL}/{self.city}/{slug}{query_string}"

            self.rate_limiter.acquire(1)

            def _do_request():
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'fa,en;q=0.9',
                    'Referer': f"https://www.sheypoor.com/s/{self.city}/real-estate"
                }
                return self.client.get(url, headers=headers, timeout=15)

            response = fallback_solver.execute_with_resilience("SheypoorSearchLive", _do_request)

            if response and response.status_code == 200:
                page_results, reached_time_limit = self._parse_html(
                    response.text, 
                    category_meta, 
                    limit - len(all_results), 
                    filters=filters,
                    on_item_found=on_item_found
                )
                all_results.extend(page_results)
                print(f"[HybridSheypoor] صفحه {page}: تعداد {len(page_results)} آگهی شخصی استخراج شد (مجموع: {len(all_results)})")
                if reached_time_limit:
                    print("[HybridSheypoor] رسیدن به مرز زمانی ۵ روز پیش در شیپور؛ توقف صفحه‌بندی.")
                    break
            else:
                status = response.status_code if response else "No Response"
                print(f"[HybridSheypoor] پاسخ ناموفق از شیپور صفحه {page}: {status}")
                break

        return all_results

    def _fetch_detail_page(self, url: str) -> Dict[str, Any]:
        """
        دریافت بلادرنگ متن کامل، اعتبارسنجی هویت فروشنده و استخراج کلیه عکس‌های ملک از شیپور
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'fa,en;q=0.9',
            }
            resp = requests.get(url, headers=headers, timeout=6)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                html_raw = resp.text

                is_agency = False
                agency_reasons = []

                # ۱. بررسی پیوندهای تجاری/مشاوران در کل صفحه
                if soup.find('a', href=re.compile(r'/shops/|/consultant/|/real-estate-agencies/')):
                    is_agency = True
                    agency_reasons.append("لینک فروشگاه یا مشاور در صفحه")

                # ۲. بررسی کلیدواژه‌های معرف مشاور یا آژانس در کل صفحه
                page_text = soup.get_text(' ', strip=True)
                for term in ['مشاور این آگهی', 'همه مشاوران', 'عضو شیپور از', 'آژانس املاک', 'دفتر املاک', 'دپارتمان املاک', 'بانک اطلاعات مسکن']:
                    if term in page_text:
                        is_agency = True
                        agency_reasons.append(f"کلیدواژه صنفی '{term}'")

                # ۳. بررسی نام املاک یا مسکن در سراسر صفحه
                agency_match = re.search(r'(?:املاک|مسکن|دپارتمان|آژانس|بنگاه)\s+([آ-ی]{3,})', page_text)
                if agency_match:
                    name_found = agency_match.group(1)
                    if name_found not in ['خرید', 'فروش', 'رهن', 'اجاره', 'مسکونی', 'تجاری', 'اداری', 'تهران', 'ایران']:
                        is_agency = True
                        agency_reasons.append(f"نام صنف املاک '{agency_match.group(0)}'")

                # ۴. بررسی تگ‌های بخش فروشنده/مشاور در سورس HTML
                if any(x in html_raw.lower() for x in ['shop-info', 'consultant-info', 'seller-profile', 'realestate-agency']):
                    is_agency = True
                    agency_reasons.append("ویجت اختصاصی پنل املاک شیپور")

                desc_elem = soup.find('p', class_=re.compile(r'description|desc', re.I)) or soup.find('div', id='description') or soup.find('section', id='description')
                desc_text = desc_elem.get_text(separator='\n', strip=True) if desc_elem else ""

                if not desc_text:
                    meta = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'og:description'})
                    if meta and meta.get('content'):
                        desc_text = meta.get('content').strip()

                imgs = []
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src and ('img.sheypoor.com' in src or 'sheypoor' in src):
                        src_large = src.replace('/small/', '/large/').replace('/thumb/', '/large/')
                        if src_large not in imgs and not any(ic in src_large for ic in ['logo', 'icon', 'banner', 'avatar']):
                            imgs.append(src_large)

                return {
                    'description': desc_text, 
                    'images': imgs,
                    'is_agency': is_agency,
                    'agency_reason': " / ".join(agency_reasons) if agency_reasons else ""
                }
        except Exception:
            pass
        return {'description': '', 'images': [], 'is_agency': False, 'agency_reason': ''}

    def _build_item_from_sheypoor(
        self,
        c: Dict[str, Any],
        detail_info: Dict[str, Any],
        category_meta: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None
    ) -> Optional[NormalizedPropertySchema]:
        """اعتبارسنجی و تبدیل آگهی شیپور به مدل نرمالایز شده"""
        if detail_info.get('is_agency'):
            return None

        text = c['text']
        full_url = c['full_url']
        source_id = c['source_id']
        real_desc = detail_info.get('description', '')
        all_images = list(detail_info.get('images', []))
        if c.get('img_url') and c['img_url'] not in all_images:
            all_images.insert(0, c['img_url'])

        # حذف آگهی‌های همخونه در توضیحات
        if any(sh_kw in real_desc for sh_kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS):
            return None

        if real_desc:
            full_filter_res = OwnerFilter.evaluate(
                platform='sheypoor',
                title=text,
                description=real_desc,
                raw_text=f"{text} {real_desc}"
            )
            if not full_filter_res.is_personal:
                return None
        else:
            full_filter_res = c.get('filter_res')

        # محله
        dist_m = re.search(r'تهران[،\s]+([^\s\|،]+)', text)
        district = dist_m.group(1).strip() if dist_m else 'تهران'

        # متراژ
        area_m = re.search(r'\b(\d{2,4})\s*(?:متر|متی)', persian_to_english_numbers(text))
        area = min(int(area_m.group(1)), 5000) if area_m else 95

        # خواب
        rooms_m = re.search(r'\b([1-9])\s*(?:خواب|خوابه)', persian_to_english_numbers(text))
        rooms = int(rooms_m.group(1)) if rooms_m else (1 if area < 70 else (2 if area < 130 else 3))

        # تمیز کردن عنوان
        clean_title = text
        for token in ['تومان', 'تهران', 'Ad']:
            if token in clean_title:
                clean_title = clean_title.split(token)[0]
        clean_title = re.sub(r'^(?:فوری\s*\d*\s*|\d+\s*)', '', clean_title.strip()).strip()[:120]
        if not clean_title or len(clean_title) < 6:
            clean_title = f"{category_meta['name']} {area} متری در {district}"

        final_desc = real_desc if (real_desc and len(real_desc) > 10) else f"فایل شخصی استخراج شده از شیپور. {clean_title} واقع در منطقه {district}."

        deal_type = category_meta['deal_type']
        prop_type = category_meta['property_type']

        total_price = 0
        deposit = 0
        monthly_rent = 0

        combined_financial_text = f"{text} {real_desc}"
        if deal_type == 'sale':
            total_price = parse_price(text) or parse_price(real_desc)
        else:
            dep_m = re.search(r'(?:رهن|ودیعه)\s*[:؛-]?\s*([^\n\|،]+)', combined_financial_text)
            rent_m = re.search(r'(?:اجاره|کرایه)\s*[:؛-]?\s*([^\n\|،]+)', combined_financial_text)
            if dep_m:
                deposit = parse_price(dep_m.group(1))
            if rent_m:
                monthly_rent = parse_price(rent_m.group(1))
            if not deposit and not monthly_rent:
                deposit = parse_price(text)

        total_price, deposit, monthly_rent = sanitize_property_financials(
            deal_type=deal_type,
            total_price=total_price,
            deposit=deposit,
            monthly_rent=monthly_rent,
            property_type=prop_type
        )
        meter_price = int(total_price / area) if area > 0 and total_price > 0 else 0

        # سال ساخت پیش‌فرض یا استخراج
        build_year = 1400
        year_m = re.search(r'(?:سال\s*ساخت|ساخت)\s*[:؛-]?\s*(\d{4})', persian_to_english_numbers(f"{clean_title} {real_desc}"))
        if year_m:
            try:
                build_year = int(year_m.group(1))
            except Exception:
                pass

        extracted_phone = extract_phone_number(f"{clean_title} {real_desc} {text}")
        owner_phone = extracted_phone if extracted_phone else ""

        has_elev = 'آسانسور' in f"{clean_title} {real_desc}" and 'بدون آسانسور' not in f"{clean_title} {real_desc}"
        has_park = 'پارکینگ' in f"{clean_title} {real_desc}" and 'بدون پارکینگ' not in f"{clean_title} {real_desc}"
        has_ware = 'انباری' in f"{clean_title} {real_desc}" and 'بدون انباری' not in f"{clean_title} {real_desc}"
        has_balc = 'بالکن' in f"{clean_title} {real_desc}" or 'تراس' in f"{clean_title} {real_desc}"

        # اعمال فیلترها
        if filters:
            min_a = filters.get('min_area')
            max_a = filters.get('max_area')
            if min_a and area < min_a:
                return None
            if max_a and area > max_a:
                return None

            f_rooms = filters.get('rooms')
            if f_rooms and rooms < f_rooms:
                return None

            # فیلتر سن بنا و سال ساخت
            min_y = filters.get('min_year')
            max_y = filters.get('max_year')
            min_age = filters.get('min_age')
            max_age = filters.get('max_age')
            if min_age is not None and build_year > (1403 - int(min_age)):
                return None
            if max_age is not None and build_year < (1403 - int(max_age)):
                return None
            if min_y and build_year < int(min_y):
                return None
            if max_y and build_year > int(max_y):
                return None

            if filters.get('has_parking') and not has_park:
                return None
            if filters.get('has_elevator') and not has_elev:
                return None
            if filters.get('has_warehouse') and not has_ware:
                return None
            if filters.get('has_balcony') and not has_balc:
                return None

            min_p = filters.get('min_price')
            max_p = filters.get('max_price')
            if min_p and total_price > 0 and total_price < min_p:
                return None
            if max_p and total_price > 0 and total_price > max_p:
                return None

            min_dep = filters.get('min_deposit')
            max_dep = filters.get('max_deposit')
            if min_dep and deposit > 0 and deposit < min_dep:
                return None
            if max_dep and deposit > 0 and deposit > max_dep:
                return None

            min_r = filters.get('min_rent')
            max_r = filters.get('max_rent')
            if min_r and monthly_rent > 0 and monthly_rent < min_r:
                return None
            if max_r and monthly_rent > 0 and monthly_rent > max_r:
                return None

        reason = full_filter_res.reason if hasattr(full_filter_res, 'reason') else 'مالک شخصی شیپور'
        item_dict = {
            'source': 'sheypoor',
            'source_id': source_id,
            'source_url': full_url,
            'title': clean_title,
            'deal_type': deal_type,
            'property_type': prop_type,
            'city': self.city,
            'district': district,
            'address': f"تهران، {district}",
            'total_price': total_price,
            'meter_price': meter_price,
            'deposit': deposit,
            'monthly_rent': monthly_rent,
            'area': area,
            'rooms': rooms,
            'floor': 1,
            'build_year': build_year,
            'has_elevator': has_elev,
            'has_parking': has_park,
            'has_warehouse': has_ware,
            'has_balcony': has_balc,
            'features': ['فایل شخصی شیپور', 'تأییدشده بدون واسطه'],
            'description': final_desc,
            'images': all_images,
            'status': 'raw_crawled',
            'score': 75 + (10 if all_images else 0) + (10 if extracted_phone else 0),
            'is_personal_owner': True,
            'owner_type': 'personal',
            'filter_log': reason,
            'owner_info': {
                'name': f"مالک آگهی شیپور ({district})",
                'phone': owner_phone,
                'urgency': 'medium',
                'flexibility': 'معمولی',
                'notes': f"ثبت خودکار از کراولر شیپور برای منطقه {district}. {'(شماره تماس مستقیم از متن)' if extracted_phone else '(شماره در شیپور محفوظ است)'}"
            }
        }

        try:
            return NormalizedPropertySchema(**item_dict)
        except Exception:
            return None

    def _parse_html(self, html_text: str, category_meta: Dict[str, Any], limit: int, filters: Optional[Dict[str, Any]] = None, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> Tuple[List[NormalizedPropertySchema], bool]:
        soup = BeautifulSoup(html_text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'/v/'))
        results: List[NormalizedPropertySchema] = []
        reached_time_limit = False
        candidates: List[Dict[str, Any]] = []

        for a in links:
            href = a.get('href', '')
            if not href:
                continue

            full_url = href if href.startswith('http') else f"https://www.sheypoor.com{href}"
            id_m = re.search(r'-(\d+)\.html', href)
            item_id = id_m.group(1) if id_m else str(abs(hash(href)))
            source_id = f"sheypoor_{item_id}"

            if dedup_engine.is_duplicate(source_id):
                continue

            text = a.get_text(separator=' ', strip=True)

            if is_older_than_5_days(text):
                reached_time_limit = True
                continue

            if any(sh_kw in text for sh_kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS):
                continue

            filter_res = OwnerFilter.evaluate(
                platform='sheypoor',
                title=text,
                description=text,
                raw_text=text
            )
            if not filter_res.is_personal:
                continue

            img_elem = a.find('img')
            img_url = (img_elem.get('src') or img_elem.get('data-src')) if img_elem else None

            candidates.append({
                'full_url': full_url,
                'source_id': source_id,
                'text': text,
                'img_url': img_url,
                'filter_res': filter_res
            })

            if len(candidates) >= max(limit * 2, 10):
                break

        # پردازش همروند جزئیات آگهی‌های شیپور با ThreadPoolExecutor
        if candidates:
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_cand = {executor.submit(self._fetch_detail_page, c['full_url']): c for c in candidates}
                for future in as_completed(future_to_cand):
                    c = future_to_cand[future]
                    try:
                        detail_info = future.result()
                        validated = self._build_item_from_sheypoor(c, detail_info, category_meta, filters)
                        if validated:
                            results.append(validated)
                            dedup_engine.mark_seen(c['source_id'])
                            if on_item_found:
                                try:
                                    on_item_found(validated)
                                except Exception:
                                    pass
                            if len(results) >= limit:
                                break
                    except Exception:
                        pass

        return results, reached_time_limit
