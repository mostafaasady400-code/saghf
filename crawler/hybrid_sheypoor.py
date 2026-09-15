import re
import random
from urllib.parse import unquote, quote
from typing import List, Dict, Any, Optional, Tuple, Callable
from bs4 import BeautifulSoup
from .network.impersonator import TLSImpersonatorClient
from .network.rate_limiter import TokenBucketRateLimiter
from .network.proxy_manager import ProxyManager
from .dedup import dedup_engine
from .fallback_solver import fallback_solver
from .schemas import NormalizedPropertySchema, OwnerSchema, parse_price, persian_to_english_numbers
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
    کراولر هیبریدی شیپور مجهز به استخراج زنده از HTML و صفحات وب
    با جعل اثر انگشت TLS کروم و استخراج آگهی‌های واقعی با لینک‌های مستقیم و فعال
    پشتیبانی از عمق جستجو (تا ۵ روز گذشته)، فیلتر سخت‌گیرانه مشاوران و استخراج شماره مالک
    """
    BASE_WEB_URL = "https://www.sheypoor.com/s"

    CATEGORIES = {
        'buy-apartment': {'slug': 'houses-apartments-for-sale', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'فروش آپارتمان'},
        'rent-apartment': {'slug': 'house-apartment-for-rent', 'deal_type': 'rent', 'property_type': 'apartment', 'name': 'اجاره آپارتمان'},
        'buy-villa': {'slug': 'villa-for-sale', 'deal_type': 'sale', 'property_type': 'villa', 'name': 'فروش ویلا و خانه'},
        'commercial-sell': {'slug': 'commercial-properties-for-sale', 'deal_type': 'sale', 'property_type': 'commercial', 'name': 'فروش تجاری و مغازه'},
        'commercial-rent': {'slug': 'commercial-properties-for-rent', 'deal_type': 'rent', 'property_type': 'commercial', 'name': 'اجاره اداری و تجاری'},
        'real-estate': {'slug': 'real-estate', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'املاک تهران'}
    }

    def __init__(self, city: str = 'tehran', proxy_manager: Optional[ProxyManager] = None):
        self.city = city
        self.proxy_manager = proxy_manager or ProxyManager()
        self.rate_limiter = TokenBucketRateLimiter(capacity=3, fill_rate=1.2)
        self.client = TLSImpersonatorClient(
            impersonate="chrome120",
            proxy=self.proxy_manager.get_proxy()
        )

    def fetch_listings(self, category_key: str = 'buy-apartment', limit: int = 30, query: Optional[str] = None, max_pages: int = 3, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> List[NormalizedPropertySchema]:
        category_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        slug = category_meta['slug']
        all_results: List[NormalizedPropertySchema] = []

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
                page_results, reached_time_limit = self._parse_html(response.text, category_meta, limit - len(all_results), on_item_found=on_item_found)
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
        دریافت بلادرنگ متن کامل توضیحات و کلیه عکس‌های ملک از صفحه اختصاصی شیپور
        """
        try:
            resp = self.client.get(url, timeout=8)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
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

                return {'description': desc_text, 'images': imgs}
        except Exception:
            pass
        return {'description': '', 'images': []}

    def _parse_html(self, html_text: str, category_meta: Dict[str, Any], limit: int, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> Tuple[List[NormalizedPropertySchema], bool]:
        soup = BeautifulSoup(html_text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'/v/'))
        results: List[NormalizedPropertySchema] = []
        deal_type = category_meta['deal_type']
        prop_type = category_meta['property_type']
        reached_time_limit = False

        for a in links:
            if len(results) >= limit:
                break

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

            # بررسی بازه زمانی ۵ روز
            if is_older_than_5_days(text):
                reached_time_limit = True
                continue

            # فیلتر مرحله ۱: بررسی عنوان و متن اولیه
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

            # استخراج بلادرنگ متن کامل توضیحات و کلیه عکس‌های ملک از شیپور
            detail_info = self._fetch_detail_page(full_url)
            real_desc = detail_info.get('description', '')
            all_images = detail_info.get('images', [])

            # فیلتر مرحله ۲: بررسی متن کامل توضیحات برای حذف قطعی مشاوران
            if real_desc:
                full_filter_res = OwnerFilter.evaluate(
                    platform='sheypoor',
                    title=text,
                    description=real_desc,
                    raw_text=f"{text} {real_desc}"
                )
                if not full_filter_res.is_personal:
                    continue

            if not all_images and img_url:
                all_images = [img_url]

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

            # قیمت
            price = parse_price(text)
            if 0 < price < 10_000_000:
                price *= 1_000_000

            total_price = price if deal_type == 'sale' else 0
            deposit = price if deal_type == 'rent' else 0
            monthly_rent = 0
            meter_price = int(total_price / area) if area > 0 and total_price > 0 else 0

            # استخراج شماره تماس واقعی مالک از متن یا توضیحات
            extracted_phone = extract_phone_number(f"{clean_title} {real_desc} {text}")
            owner_phone = extracted_phone if extracted_phone else ""

            # امکانات از متن
            has_elev = 'آسانسور' in f"{clean_title} {real_desc}" and 'بدون آسانسور' not in f"{clean_title} {real_desc}"
            has_park = 'پارکینگ' in f"{clean_title} {real_desc}" and 'بدون پارکینگ' not in f"{clean_title} {real_desc}"
            has_ware = 'انباری' in f"{clean_title} {real_desc}" and 'بدون انباری' not in f"{clean_title} {real_desc}"
            has_balc = 'بالکن' in f"{clean_title} {real_desc}" or 'تراس' in f"{clean_title} {real_desc}"

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
                'build_year': 1400,
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
                'filter_log': filter_res.reason,
                'owner_info': {
                    'name': f"مالک آگهی شیپور ({district})",
                    'phone': owner_phone,
                    'urgency': 'medium',
                    'flexibility': 'معمولی',
                    'notes': f"ثبت خودکار از کراولر شیپور برای منطقه {district}. {'(شماره تماس مستقیم از متن)' if extracted_phone else '(شماره در شیپور محفوظ است)'}"
                }
            }

            try:
                validated = NormalizedPropertySchema(**item_dict)
                results.append(validated)
                dedup_engine.mark_seen(source_id)
                if on_item_found:
                    try:
                        on_item_found(validated)
                    except Exception as cb_err:
                        print(f"[HybridSheypoor] خطا در کال‌بک آنلاین: {cb_err}")
            except Exception as err:
                print(f"[HybridSheypoor] رد رکورد نامعتبر: {err}")

        return results, reached_time_limit
