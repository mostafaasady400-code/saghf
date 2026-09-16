import re
import random
import json
import time
from typing import List, Dict, Any, Optional, Tuple, Callable
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
    older_markers = ['۶ روز پیش', '۷ روز پیش', 'هفته پیش', 'هفتهٔ پیش', '۲ هفته پیش', '۳ هفته پیش', 'ماه پیش']
    for m in older_markers:
        if m in text:
            return True
    return False

class HybridDivarCrawler:
    """
    کراولر هیبریدی دیوار مجهز به استخراج زنده از HTML/State با جعل اثر انگشت TLS کروم
    استخراج واقعی آگهی‌ها با لینک‌های مستقیم، معتبر و قابل کلیک: https://divar.ir/v/{token}
    مجهز به فیلتر هوشمند دومرحله‌ای جهت حذف قطعی مشاوران و ثبت اختصاصی آگهی‌های مالک/شخصی
    پوشش زمانی تا ۵ روز گذشته با مرتب‌سازی زمانی
    """
    BASE_WEB_URL = "https://divar.ir/s"
    OPEN_PLATFORM_POST_URL = "https://open-api.divar.ir/v2/open-platform/finder/post"

    CATEGORIES = {
        'buy-apartment': {'slug': 'buy-apartment', 'deal_type': 'sale', 'property_type': 'apartment', 'name': 'فروش آپارتمان'},
        'rent-apartment': {'slug': 'rent-apartment', 'deal_type': 'rent', 'property_type': 'apartment', 'name': 'اجاره آپارتمان'},
        'buy-residential': {'slug': 'buy-residential', 'deal_type': 'sale', 'property_type': 'villa', 'name': 'فروش مسکونی و ویلایی'},
        'rent-residential': {'slug': 'rent-residential', 'deal_type': 'rent', 'property_type': 'villa', 'name': 'اجاره مسکونی و ویلایی'},
        'commercial-sell': {'slug': 'commercial-sell', 'deal_type': 'sale', 'property_type': 'commercial', 'name': 'فروش تجاری و مغازه'},
        'commercial-rent': {'slug': 'commercial-rent', 'deal_type': 'rent', 'property_type': 'commercial', 'name': 'اجاره اداری و تجاری'},
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

    def fetch_listings(self, category_key: str = 'buy-apartment', limit: int = 30, query: Optional[str] = None, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> List[NormalizedPropertySchema]:
        category_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        slug = category_meta['slug']
        results: List[NormalizedPropertySchema] = []

        # ۱. تلاش در وهله نخست از اندپوینت رسمی OpenAPI پلتفرم باز دیوار:
        # https://open-api.divar.ir/v2/open-platform/finder/post
        try:
            from .divar_session_manager import DivarSessionManager
            op_res = DivarSessionManager.fetch_finder_posts(
                endpoint=self.OPEN_PLATFORM_POST_URL,
                category=slug,
                city=self.city,
                limit=limit
            )
            if op_res.get('success') and op_res.get('data'):
                print(f"[HybridDivar] ✅ دریافت موفقیت‌آمیز آگهی‌ها از اندپوینت پلتفرم باز: {self.OPEN_PLATFORM_POST_URL}")
                parsed_op = self._parse_open_platform_response(op_res['data'], category_meta, limit, on_item_found=on_item_found)
                if parsed_op:
                    results.extend(parsed_op)
                    if len(results) >= limit:
                        results.sort(key=lambda x: x.score, reverse=True)
                        return results
            else:
                status_code = op_res.get('status_code', 'unknown')
                print(f"[HybridDivar] ℹ️ استعلام از اندپوینت OpenAPI Finder ({self.OPEN_PLATFORM_POST_URL}) وضعیت {status_code}: سوئیچ خودکار به موتور هیبریدی زنده...")
        except Exception as e:
            print(f"[HybridDivar] هشدار فراخوانی OpenAPI Finder: {e}")

        # ۲. پیمایش صفحات جهت استخراج عمیق تا سقف ۵ روز گذشته از موتور هیبریدی زنده
        for page in range(1, 4):
            if len(results) >= limit:
                break

            self.rate_limiter.acquire(1)
            url = f"{self.BASE_WEB_URL}/{self.city}/{slug}"
            if query:
                from urllib.parse import quote
                url = f"{url}?q={quote(query)}"
                if page > 1:
                    url += f"&page={page}"
            elif page > 1:
                url += f"?page={page}"

            def _do_request():
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'fa,en;q=0.9',
                    'Referer': f"https://divar.ir/s/{self.city}/real-estate"
                }
                return self.client.get(url, headers=headers, timeout=15)

            response = fallback_solver.execute_with_resilience(f"DivarSearchLive_P{page}", _do_request)
            if response and response.status_code == 200:
                page_items, reached_limit = self._parse_html_state(response.text, category_meta, limit - len(results), on_item_found=on_item_found)
                results.extend(page_items)
                print(f"[HybridDivar] صفحه {page}: تعداد {len(page_items)} آگهی واجد شرایط دریافت شد.")
                if reached_limit or len(page_items) == 0:
                    break
            else:
                break

        # مرتب‌سازی نهایی بر اساس تاریخ/امتیاز (از جدیدترین به قدیمی‌ترین)
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def _parse_open_platform_response(self, data: Dict[str, Any], category_meta: Dict[str, Any], limit: int, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> List[NormalizedPropertySchema]:
        """پارس ساختار داده بازگشتی از اندپوینت OpenAPI Finder دیوار"""
        items: List[NormalizedPropertySchema] = []
        posts = data.get('posts') or data.get('items') or data.get('data') or []
        if isinstance(posts, dict):
            posts = posts.get('items') or posts.get('posts') or []

        for p in posts:
            if len(items) >= limit:
                break
            try:
                token = p.get('token') or p.get('id')
                title = p.get('title') or ''
                if not token or not title:
                    continue

                source_id = f"divar_{token}"
                if dedup_engine.is_duplicate(source_id):
                    continue

                # واکشی جزئیات عمیق و شماره تماس
                post_details = self._fetch_post_details(token)
                contact_phone = p.get('contact', {}).get('phone') or p.get('phone_number') or post_details.get('phone')
                real_desc = post_details.get('description') or p.get('description') or title

                all_images = post_details.get('images') or p.get('images') or []
                item_dict = {
                    'source': 'divar',
                    'source_id': source_id,
                    'source_url': f"https://divar.ir/v/{token}",
                    'title': title,
                    'deal_type': category_meta['deal_type'],
                    'property_type': category_meta['property_type'],
                    'city': self.city,
                    'district': p.get('district') or 'تهران',
                    'address': f"تهران، {p.get('district') or 'تهران'}",
                    'total_price': post_details.get('total_price') or p.get('total_price') or 0,
                    'meter_price': post_details.get('meter_price') or p.get('meter_price') or 0,
                    'deposit': post_details.get('deposit') or p.get('deposit') or 0,
                    'monthly_rent': post_details.get('monthly_rent') or p.get('monthly_rent') or 0,
                    'area': post_details.get('area') or p.get('area') or 85,
                    'rooms': post_details.get('rooms') or p.get('rooms') or 2,
                    'floor': post_details.get('floor') or 1,
                    'total_floors': post_details.get('total_floors'),
                    'build_year': post_details.get('build_year') or 1400,
                    'has_elevator': post_details.get('has_elevator', False),
                    'has_parking': post_details.get('has_parking', False),
                    'has_warehouse': post_details.get('has_warehouse', False),
                    'has_balcony': post_details.get('has_balcony', False),
                    'features': post_details.get('features', []),
                    'description': real_desc,
                    'images': all_images,
                    'status': 'raw_crawled',
                    'score': 85,
                    'is_personal_owner': True,
                    'owner_type': 'personal',
                    'filter_log': 'OpenAPI Finder Post (شخصی)',
                    'owner_info': {
                        'name': f"مالک آگهی دیوار ({p.get('district') or 'تهران'})",
                        'phone': contact_phone or '',
                        'urgency': 'high',
                        'flexibility': 'معمولی',
                        'notes': 'استخراج از اندپوینت رسمی OpenAPI پلتفرم باز دیوار'
                    }
                }
                schema = NormalizedPropertySchema(**item_dict)
                items.append(schema)
                if on_item_found:
                    on_item_found(schema)
            except Exception as ex:
                print(f"[HybridDivar] خطا در پردازش پست OpenAPI: {ex}")
        return items

    def _fetch_post_details(self, token: str) -> Dict[str, Any]:
        """
        دریافت بلادرنگ و عمیق کلیه جزئیات واقعی آگهی از API رسمی دیوار:
        متن کامل توضیحات، تمام تصاویر اصلی CDN دیوار، متراژ، سال ساخت، تعداد اتاق،
        طبقه و کل طبقات، وضعیت آسانسور/پارکینگ/انباری/بالکن، قیمت‌های تفکیک‌شده و ویژگی‌های سندی
        """
        url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
        details: Dict[str, Any] = {
            'description': '',
            'images': [],
            'area': None,
            'build_year': None,
            'rooms': None,
            'floor': None,
            'total_floors': None,
            'has_elevator': False,
            'has_parking': False,
            'has_warehouse': False,
            'has_balcony': False,
            'total_price': None,
            'meter_price': None,
            'deposit': None,
            'monthly_rent': None,
            'features': [],
            'verified_photos': False,
            'phone': None
        }
        try:
            resp = self.client.get(url, timeout=8)
            if resp and resp.status_code == 200:
                data = resp.json()
                sections = data.get('sections', [])
                images: List[str] = []
                features: List[str] = []

                for sec in sections:
                    for w in sec.get('widgets', []):
                        wt = w.get('widget_type', '')
                        wd = w.get('data', {})

                        # ۰. بررسی و رد ویجت‌های اختصاصی پنل‌های املاک و اکانت‌های تجاری دیوار
                        if wt == 'LAZY_SECTION':
                            req_data = wd.get('request_data', {})
                            biz_type = str(req_data.get('post_business_type', '')).lower()
                            if biz_type in ['premium-panel', 'business', 'agency', 'consultant', 'real_estate_agency']:
                                details['is_agency_post'] = True
                        elif any(x in wt.lower() for x in ['agency_info', 'business_section', 'seller_profile']):
                            details['is_agency_post'] = True

                        # ۱. متن کامل توضیحات
                        elif wt == 'DESCRIPTION_ROW':
                            text = wd.get('text', '')
                            if text:
                                details['description'] = text.strip()

                        # ۲. استخراج تمامی تصاویر واقعی خود آگهی از CDN دیوار
                        elif wt in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER', 'IMAGES_ROW']:
                            for it in wd.get('items', []):
                                u = it.get('image', {}).get('url') or it.get('url')
                                if u and u not in images and 'divarcdn.com' in u:
                                    images.append(u)

                        # ۳. اطلاعات ساختاری پایه (متراژ، ساخت، اتاق)
                        elif wt == 'GROUP_INFO_ROW':
                            for item in wd.get('items', []):
                                t = item.get('title', '')
                                v = item.get('value', '')
                                if 'متراژ' in t:
                                    m = re.search(r'\d+', persian_to_english_numbers(v))
                                    if m:
                                        details['area'] = int(m.group(0))
                                elif 'ساخت' in t:
                                    m = re.search(r'\d+', persian_to_english_numbers(v))
                                    if m:
                                        details['build_year'] = int(m.group(0))
                                elif 'اتاق' in t:
                                    if 'بدون' in v:
                                        details['rooms'] = 0
                                    else:
                                        m = re.search(r'\d+', persian_to_english_numbers(v))
                                        if m:
                                            details['rooms'] = int(m.group(0))

                        # ۴. اطلاعات قیمتی، طبقه و ویژگی‌های تفصیلی
                        elif wt == 'UNEXPANDABLE_ROW':
                            t = wd.get('title', '')
                            v = wd.get('value', '')
                            if 'قیمت کل' in t:
                                p = parse_price(v)
                                if p > 0:
                                    details['total_price'] = p
                            elif 'قیمت هر متر' in t:
                                mp = parse_price(v)
                                if mp > 0:
                                    details['meter_price'] = mp
                            elif 'ودیعه' in t:
                                dep = parse_price(v)
                                if dep > 0:
                                    details['deposit'] = dep
                            elif 'اجاره' in t:
                                rnt = parse_price(v)
                                if rnt > 0:
                                    details['monthly_rent'] = rnt
                            elif 'طبقه' in t:
                                v_en = persian_to_english_numbers(v)
                                m_floors = re.search(r'(\d+)\s*از\s*(\d+)', v_en)
                                if m_floors:
                                    details['floor'] = int(m_floors.group(1))
                                    details['total_floors'] = int(m_floors.group(2))
                                elif 'همکف' in v:
                                    details['floor'] = 0
                                elif 'زیر' in v:
                                    details['floor'] = -1
                                else:
                                    m_f = re.search(r'\d+', v_en)
                                    if m_f:
                                        details['floor'] = int(m_f.group(0))
                            elif 'تصویر' in t and 'همین ملک' in t and 'بله' in v:
                                details['verified_photos'] = True
                                features.append("تصاویر متعلق به همین ملک (تأییدشده در دیوار)")
                            elif t and v and t not in ['گزارش آگهی', 'شناسه آگهی']:
                                features.append(f"{t}: {v}")

                        # ۵. اسلایدر تبدیل ودیعه و اجاره
                        elif wt == 'RENT_SLIDER':
                            c_val = wd.get('credit', {}).get('value')
                            r_val = wd.get('rent', {}).get('value')
                            if c_val:
                                p_c = parse_price(c_val)
                                if p_c > 0:
                                    details['deposit'] = p_c
                            if r_val:
                                p_r = parse_price(r_val)
                                if p_r > 0:
                                    details['monthly_rent'] = p_r

                        # ۶. امکانات و مشاعات اصلی (آسانسور، پارکینگ، انباری)
                        elif wt == 'GROUP_FEATURE_ROW':
                            for fit in wd.get('items', []):
                                ftitle = fit.get('title', '')
                                avail = fit.get('available', True)
                                if 'آسانسور' in ftitle:
                                    details['has_elevator'] = avail and ('ندارد' not in ftitle)
                                elif 'پارکینگ' in ftitle:
                                    details['has_parking'] = avail and ('ندارد' not in ftitle)
                                elif 'انباری' in ftitle:
                                    details['has_warehouse'] = avail and ('ندارد' not in ftitle)
                                features.append(ftitle)

                # تصاویر تکمیلی از web_images و seo در صورت وجود
                if not images:
                    for wimg in data.get('web_images', []):
                        u = wimg.get('src') or wimg.get('url')
                        if u and u not in images and 'divarcdn.com' in u:
                            images.append(u)

                seo_img = data.get('seo', {}).get('post_seo_schema', {}).get('image') or data.get('seo', {}).get('image_url')
                if seo_img and seo_img not in images and 'divarcdn.com' in seo_img:
                    images.insert(0, seo_img)

                # بالکن از متن یا ویژگی‌ها
                desc_text = details['description'] or ''
                if 'بالکن' in desc_text or any('بالکن' in f for f in features):
                    details['has_balcony'] = True

                details['images'] = images
                details['features'] = features

                # ۱. استخراج شماره واقعی از API رسمی اطلاعات تماس دیوار با سشن کاربر
                try:
                    from crawler.divar_session_manager import DivarSessionManager
                    direct_phone = DivarSessionManager.fetch_contact_phone(token)
                    if direct_phone:
                        details['phone'] = direct_phone
                except Exception as ex:
                    pass

                # ۲. در صورت نبود سشن، استخراج شماره تلفن از متن با رگکس و دیکودر اعداد حروفی
                if not details.get('phone'):
                    ph = extract_phone_number(desc_text)
                    if ph:
                        details['phone'] = ph

                return details
        except Exception as e:
            print(f"[HybridDivar] خطا در خواندن جزئیات پست {token}: {e}")
        return details

    def _parse_html_state(self, html_text: str, category_meta: Dict[str, Any], limit: int, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> Tuple[List[NormalizedPropertySchema], bool]:
        results: List[NormalizedPropertySchema] = []
        deal_type = category_meta['deal_type']
        prop_type = category_meta['property_type']
        reached_limit = False

        # روش اول: استخراج از window.__PRELOADED_STATE__
        match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', html_text)
        if match:
            try:
                state_data = json.loads(match.group(1))
                widgets = state_data.get('nb', {}).get('listWidgets', [])
                for w in widgets:
                    if len(results) >= limit:
                        break

                    dto = w.get('data', {}).get('dto', {})
                    if dto.get('widget_type') != 'POST_ROW':
                        continue

                    d = dto.get('data', {})
                    token = d.get('token') or d.get('action', {}).get('payload', {}).get('token')
                    title = d.get('title', '')
                    if not token or not title:
                        continue

                    source_id = f"divar_{token}"
                    if dedup_engine.is_duplicate(source_id):
                        continue

                    district = d.get('action', {}).get('payload', {}).get('web_info', {}).get('district_persian', '')
                    if not district:
                        bottom = d.get('bottom_description_text', '')
                        district = bottom.replace('در ', '').strip() or 'تهران'

                    middle_desc = d.get('middle_description_text', '')
                    bottom_desc = d.get('bottom_description_text', '')

                    # بررسی بازه زمانی: توقف در صورت قدیمی‌تر بودن از ۵ روز گذشته
                    if is_older_than_5_days(bottom_desc) or is_older_than_5_days(middle_desc):
                        reached_limit = True
                        continue

                    # فیلتر مرحله اول: بررسی متادیتای اولیه
                    filter_res = OwnerFilter.evaluate(
                        platform='divar',
                        title=title,
                        description=middle_desc,
                        widget_data=d,
                        raw_text=bottom_desc
                    )
                    if not filter_res.is_personal:
                        continue

                    # استخراج عمیق و بلادرنگ کلیه جزئیات واقعی فایل از API دیوار
                    post_details = self._fetch_post_details(token)
                    if post_details.get('is_agency_post'):
                        # رد قطعی آگهی‌های دارای ویجت‌های تجاری و پنل املاک
                        continue
                    real_desc = post_details.get('description', '')
                    all_images = post_details.get('images', [])
                    raw_img = d.get('image_url')
                    if raw_img and raw_img not in all_images and 'divarcdn.com' in raw_img:
                        all_images.insert(0, raw_img)

                    final_desc = real_desc if (real_desc and len(real_desc) > 10) else f"فایل استخراج شده از دیوار. {title}. در منطقه {district}. {middle_desc} {bottom_desc}."

                    # فیلتر مرحله دوم: بررسی سخت‌گیرانه روی متن کامل آگهی جهت حذف واسطه‌ها
                    full_filter_res = OwnerFilter.evaluate(
                        platform='divar',
                        title=title,
                        description=final_desc,
                        widget_data=d,
                        raw_text=f"{middle_desc} {bottom_desc}"
                    )
                    if not full_filter_res.is_personal:
                        continue

                    # مالی
                    total_price = 0
                    meter_price = 0
                    deposit = 0
                    monthly_rent = 0

                    if deal_type == 'sale':
                        total_price = post_details.get('total_price') or parse_price(middle_desc) or parse_price(bottom_desc)
                        if 0 < total_price < 10_000_000:
                            total_price *= 1_000_000
                        meter_price = post_details.get('meter_price') or 0
                    else:
                        deposit = post_details.get('deposit') or parse_price(middle_desc)
                        monthly_rent = post_details.get('monthly_rent') or parse_price(bottom_desc)
                        if 0 < deposit < 10_000_000:
                            deposit *= 1_000_000
                        if 0 < monthly_rent < 10_000_000:
                            monthly_rent *= 1_000_000

                    # ابعاد و مشخصات
                    combined_text = f"{title} {middle_desc} {bottom_desc} {final_desc}"
                    area = post_details.get('area') or self._extract_area(combined_text) or 90
                    rooms = post_details.get('rooms')
                    if rooms is None:
                        rooms = self._extract_rooms(combined_text) or (1 if area < 70 else (2 if area < 130 else 3))

                    if area > 0 and total_price > 0 and not meter_price:
                        meter_price = int(total_price / area)

                    floor = post_details.get('floor')
                    if floor is None:
                        floor = 1
                    total_floors = post_details.get('total_floors')
                    build_year = post_details.get('build_year') or 1400

                    has_elevator = post_details.get('has_elevator', False)
                    has_parking = post_details.get('has_parking', False)
                    has_warehouse = post_details.get('has_warehouse', False)
                    has_balcony = post_details.get('has_balcony', False)

                    features = post_details.get('features', [])

                    # استخراج شماره تماس واقعی
                    extracted_phone = post_details.get('phone') or extract_phone_number(f"{final_desc} {title}")
                    owner_phone = extracted_phone if extracted_phone else ""

                    source_url = f"https://divar.ir/v/{token}"

                    # محاسبه امتیاز واقعی فایل بر اساس کامل بودن اطلاعات
                    score = 70
                    if all_images:
                        score += 15
                    if len(all_images) >= 5:
                        score += 5
                    if post_details.get('verified_photos'):
                        score += 5
                    if len(final_desc) > 80:
                        score += 5

                    item_dict = {
                        'source': 'divar',
                        'source_id': source_id,
                        'source_url': source_url,
                        'title': title,
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
                        'floor': floor,
                        'total_floors': total_floors,
                        'build_year': build_year,
                        'has_elevator': has_elevator,
                        'has_parking': has_parking,
                        'has_warehouse': has_warehouse,
                        'has_balcony': has_balcony,
                        'features': features,
                        'description': final_desc,
                        'images': all_images,
                        'status': 'raw_crawled',
                        'score': min(score, 99),
                        'is_personal_owner': True,
                        'owner_type': 'personal',
                        'filter_log': full_filter_res.reason,
                        'owner_info': {
                            'name': f"مالک آگهی دیوار ({district})",
                            'phone': owner_phone,
                            'urgency': 'high',
                            'flexibility': 'معمولی',
                            'notes': f"ثبت خودکار از کراولر دیوار برای منطقه {district}. {'(شماره تماس مستقیم از متن)' if extracted_phone else '(شماره در دیوار محفوظ است)'}"
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
                                print(f"[HybridDivar] خطا در کال‌بک آنلاین: {cb_err}")
                    except Exception as err:
                        print(f"[HybridDivar] خطا در اعتبارسنجی schema: {err}")
            except Exception as e:
                print(f"[HybridDivar] خطا در دیکود JSON پریلود دیوار: {e}")

        return results, reached_limit

    def _extract_area(self, text: str) -> int:
        match = re.search(r'(\d+)\s*(?:متر|متری|مترمربع)', persian_to_english_numbers(text))
        if match:
            return int(match.group(1))
        return 0

    def _extract_rooms(self, text: str) -> int:
        match = re.search(r'(\d+)\s*(?:خواب|خوابه|اتاق)', persian_to_english_numbers(text))
        if match:
            return int(match.group(1))
        if 'یک خواب' in text or 'تک خواب' in text:
            return 1
        if 'دو خواب' in text:
            return 2
        if 'سه خواب' in text:
            return 3
        if 'چهار خواب' in text:
            return 4
        return 0
