import sys
import re
import random
import json
import time
from typing import List, Dict, Any, Optional, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests


def _console(message: Any) -> None:
    """Print without letting a legacy Windows console kill crawler threads."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        safe_message = str(message).encode(encoding, errors="replace").decode(encoding)
        print(safe_message)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from .network.impersonator import TLSImpersonatorClient
from .network.rate_limiter import TokenBucketRateLimiter
from .network.proxy_manager import ProxyManager
from .dedup import dedup_engine
from .fallback_solver import fallback_solver
from .schemas import NormalizedPropertySchema, OwnerSchema, parse_price, parse_area, persian_to_english_numbers, sanitize_property_financials

from .owner_filter import OwnerFilter, extract_phone_number, is_stale_ad, is_fresh_personal_time
from .parsers.divar_dom_contact import DivarDOMContactParser
from data.tehran_districts import DISTRICTS_2_AND_5_NAMES, DISTRICTS_2_AND_5_SLUGS, is_in_region_2_or_5, get_divar_slug_for_district


class HybridDivarCrawler:
    """
    کراولر هیبریدی دیوار مجهز به استخراج زنده از HTML/State با جعل اثر انگشت TLS کروم
    استخراج واقعی آگهی‌ها با لینک‌های مستقیم، معتبر و قابل کلیک: https://divar.ir/v/{token}
    مجهز به فیلتر هوشمند دومرحله‌ای جهت حذف قطعی مشاوران و ثبت اختصاصی آگهی‌های مالک/شخصی
    پوشش زمانی تا ۵ روز گذشته با مرتب‌سازی زمانی و پایپلاین همروند غیرهمزمان
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

    MAX_CRAWL_DURATION = 18
    CONCURRENCY_WORKERS = 6

    def __init__(
        self,
        city: str = 'tehran',
        proxy_manager: Optional[ProxyManager] = None,
        use_proxy: bool = False,
    ):
        self.city = city
        self.proxy_manager = proxy_manager or ProxyManager()
        self.use_proxy = bool(use_proxy)
        self.rate_limiter = TokenBucketRateLimiter(capacity=4, fill_rate=2.0)
        self.client = TLSImpersonatorClient(
            impersonate="chrome120",
            proxy=self.proxy_manager.get_proxy() if self.use_proxy else None
        )

    def fetch_listings(
        self,
        category_key: str = 'buy-apartment',
        limit: int = 50,
        query: Optional[str] = None,
        districts: Optional[List[str]] = None,
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
        property_type: Optional[str] = None,
        max_pages: int = 20,
        on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None
    ) -> List[NormalizedPropertySchema]:
        category_meta = self.CATEGORIES.get(category_key, self.CATEGORIES['buy-apartment'])
        slug = category_meta['slug']
        results: List[NormalizedPropertySchema] = []

        # محاسبه بازه سال ساخت بر مبنای سن بنا در صورت ارائه (سال جاری شمسی: ۱۴۰۳)
        current_shamsi_year = 1403
        if max_age is not None:
            calc_min_year = current_shamsi_year - int(max_age)
            min_year = max(min_year or 0, calc_min_year)
        if min_age is not None:
            calc_max_year = current_shamsi_year - int(min_age)
            max_year = min(max_year or 9999, calc_max_year) if max_year else calc_max_year

        filters_dict = {
            'districts': districts or [],
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
            'property_type': property_type
        }

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
                _console(f"[HybridDivar] ✅ دریافت موفقیت‌آمیز آگهی‌ها از اندپوینت پلتفرم باز: {self.OPEN_PLATFORM_POST_URL}")
                parsed_op = self._parse_open_platform_response(op_res['data'], category_meta, limit, on_item_found=on_item_found)
                if parsed_op:
                    results.extend(parsed_op)
                    if len(results) >= limit:
                        results.sort(key=lambda x: x.score, reverse=True)
                        return results
            else:
                status_code = op_res.get('status_code', 'unknown')
                _console(f"[HybridDivar] ℹ️ استعلام از اندپوینت OpenAPI Finder ({self.OPEN_PLATFORM_POST_URL}) وضعیت {status_code}: سوئیچ خودکار به موتور هیبریدی زنده...")
        except Exception as e:
            _console(f"[HybridDivar] هشدار فراخوانی OpenAPI Finder: {e}")

        # آماده‌سازی کوئری پارامترهای فیلترینگ URL دیوار
        url_query_parts = []
        if query:
            from urllib.parse import quote
            url_query_parts.append(f"q={quote(query)}")

        # فیلترهای مشخصات مالی و فیزیکی در کوئری پارامتر (محله‌ها مستقیماً در مسیر URL قرار می‌گیرند)

        if category_meta['deal_type'] == 'rent':
            if min_deposit or max_deposit:
                url_query_parts.append(f"credit={min_deposit or 0}-{max_deposit or ''}")
            if min_rent or max_rent:
                url_query_parts.append(f"rent={min_rent or 0}-{max_rent or ''}")
        else:
            if min_price or max_price:
                url_query_parts.append(f"price={min_price or 0}-{max_price or ''}")

        if min_area or max_area:
            url_query_parts.append(f"size={min_area or 0}-{max_area or ''}")

        if min_year or max_year:
            url_query_parts.append(f"production-year={min_year or ''}-{max_year or ''}")

        if rooms:
            url_query_parts.append(f"rooms={rooms}-")
        if has_parking:
            url_query_parts.append("has-parking=true")
        if has_elevator:
            url_query_parts.append("has-elevator=true")
        if has_warehouse:
            url_query_parts.append("has-warehouse=true")

        # ۲. ایجاد لیست اهداف پیمایش زنده برای دستیابی به حجم درخواستی فایل‌های شخصی
        target_urls = []
        
        # استخراج اسلاگ محله‌های درخواستی با مرجع tehran_districts.json
        specific_d_slugs = []
        has_region_5_request = False
        if districts:
            from data.tehran_districts import get_divar_slug_for_district
            for d_name in districts:
                dn = (d_name or '').strip()
                if not dn or dn in ['all', 'تهران', 'کل شهر', 'همه']:
                    continue
                if any(x in dn for x in ['منطقه ۵', 'منطقه 5']):
                    has_region_5_request = True
                    continue
                s = get_divar_slug_for_district(dn)
                if s and s not in specific_d_slugs:
                    specific_d_slugs.append(s)

        # اگر کاربر محله مشخصی (مانند پونک) را خواسته، مسیر استاندارد محله در دیوار را پیمایش کن
        if specific_d_slugs:
            q_str = f"?{'&'.join(url_query_parts)}" if url_query_parts else ""
            for ds in specific_d_slugs:
                target_u_path = f"{self.BASE_WEB_URL}/{self.city}/{slug}/{ds}{q_str}"
                if target_u_path not in target_urls:
                    target_urls.append(target_u_path)

        elif has_region_5_request:
            # پیمایش اختصاصی کانون‌های منطقه ۵ با اسلاگ‌های تفکیکی در مسیر
            r5_slugs = ['punak', 'central-jannat-abad', 'bagh-e-feyz', 'shahran', 'sadeghiyeh', 'ferdows']
            q_str = f"?{'&'.join(url_query_parts)}" if url_query_parts else ""
            for r5 in r5_slugs:
                r5_u = f"{self.BASE_WEB_URL}/{self.city}/{slug}/{r5}{q_str}"
                if r5_u not in target_urls:
                    target_urls.append(r5_u)
        else:
            # جستجوی عمومی کل تهران (فقط در صورت عدم تعیین محله یا منطقه)
            primary_url = f"{self.BASE_WEB_URL}/{self.city}/{slug}"
            if url_query_parts:
                primary_url += f"?{'&'.join(url_query_parts)}"
            target_urls.append(primary_url)
            q_str = f"?{'&'.join(url_query_parts)}" if url_query_parts else ""
            for kd in ['punak', 'saadat-abad', 'shahrak-e-gharb', 'marzdaran', 'ferdows', 'gisha']:
                kd_query_url = f"{self.BASE_WEB_URL}/{self.city}/{slug}/{kd}{q_str}"
                if kd_query_url not in target_urls:
                    target_urls.append(kd_query_url)

        crawl_start_time = time.time()
        max_duration = getattr(self, 'MAX_CRAWL_DURATION', 65)
        pages_per_target = max(1, min(max_pages or 5, 5))

        for idx, base_target_url in enumerate(target_urls, 1):
            if len(results) >= limit:
                break
            if time.time() - crawl_start_time >= max_duration:
                _console(f"[HybridDivar] سقف زمانی {max_duration} ثانیه فرارسید؛ تحویل {len(results)} فایل شخصی استخراج‌شده.")
                break

            current_url = base_target_url
            for p_num in range(1, pages_per_target + 1):
                if len(results) >= limit:
                    break
                if time.time() - crawl_start_time >= max_duration:
                    break

                self.rate_limiter.acquire(1)

                def _do_request(*args, **kwargs):
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                        'Accept-Language': 'fa,en;q=0.9',
                        'Referer': f"https://divar.ir/s/{self.city}/real-estate"
                    }
                    return self.client.get(current_url, headers=headers, timeout=12)

                response = fallback_solver.execute_with_resilience(
                    f"DivarSearch_{idx}_p{p_num}",
                    _do_request,
                    fallback_url=current_url
                )
                if response and response.status_code == 200:
                    page_items, reached_limit, total_raw, next_lpd = self._parse_html_state(
                        response.text,
                        category_meta,
                        limit - len(results),
                        filters=filters_dict,
                        on_item_found=on_item_found
                    )
                    results.extend(page_items)
                    target_label = base_target_url.split('?')[0].split('/')[-1]
                    _console(f"[HybridDivar] هدف {idx}/{len(target_urls)} ({target_label} ص{p_num}): دریافت {len(page_items)} فایل شخصی معتبر از {total_raw} آگهی (مجموع: {len(results)}/{limit}).")
                    if not next_lpd or total_raw == 0:
                        break
                    sep = '&' if '?' in base_target_url else '?'
                    current_url = f"{base_target_url}{sep}last-post-date={next_lpd}&page={p_num + 1}"
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
                real_desc = post_details.get('description') or p.get('description') or title
                if post_details.get('is_agency_post') or post_details.get('is_non_real_estate'):
                    continue

                owner_check = OwnerFilter.evaluate(
                    platform='divar',
                    title=title,
                    description=real_desc,
                    widget_data=p,
                    raw_text=str(p.get('subtitle') or ''),
                )
                if not owner_check.is_personal:
                    continue

                area = post_details.get('area') or p.get('area')
                if not area or parse_area(area) < 5:
                    continue

                raw_contact = (
                    post_details.get('phone')
                    or (p.get('contact') or {}).get('phone')
                    or p.get('phone_number')
                )
                contact_phone = extract_phone_number(raw_contact, filter_dummy=True)

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
                    'area': area,
                    'rooms': post_details.get('rooms') if post_details.get('rooms') is not None else p.get('rooms', 0),
                    'floor': post_details.get('floor') if post_details.get('floor') is not None else p.get('floor'),
                    'total_floors': post_details.get('total_floors'),
                    'build_year': post_details.get('build_year'),
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
                    'filter_log': f'OpenAPI Finder + DOM ({owner_check.status})',
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
                _console(f"[HybridDivar] خطا در پردازش پست OpenAPI: {ex}")
        return items

    @staticmethod
    def normalize_post_token(token: Optional[str]) -> str:
        """Normalize database/source URL forms to Divar's raw post token."""
        raw = str(token or "").strip().rstrip("/").split("/")[-1]
        raw = raw.split("?", 1)[0].split("#", 1)[0]
        if raw.startswith("divar_"):
            raw = raw[len("divar_") :]
        return raw if re.fullmatch(r"[A-Za-z0-9_-]+", raw or "") else ""

    def fetch_post_dom_details(
        self,
        token: str,
        fallback_title: str = "",
        fallback_description: str = "",
        include_contact: bool = True,
    ) -> Dict[str, Any]:
        """
        Fetch and parse the server-returned post DOM without Playwright/Chromium.

        A dedicated TLS HTTP session is used because detail requests run concurrently;
        JavaScript is never executed and browser fallback_solver is intentionally bypassed.
        """
        normalized_token = self.normalize_post_token(token)
        if not normalized_token:
            return DivarDOMContactParser.parse(
                "",
                fallback_title=fallback_title,
                fallback_description=fallback_description,
            )

        try:
            dom_client = TLSImpersonatorClient(
                impersonate=self.client.target_key,
                proxy=self.client.proxy,
                max_requests_per_session=4,
            )
            response = dom_client.get(
                f"https://divar.ir/v/{normalized_token}",
                timeout=7,
                allow_redirects=True,
            )
            if response is not None and response.status_code == 200:
                html = response.text or ""
                if len(html) <= 8_000_000:
                    parsed = DivarDOMContactParser.parse(
                        html,
                        fallback_title=fallback_title,
                        fallback_description=fallback_description,
                    )
                    if not include_contact:
                        parsed['phone'] = None
                        parsed['phone_source'] = None
                        parsed['phone_confidence'] = 0
                    return parsed
        except Exception:
            pass

        return DivarDOMContactParser.parse(
            "",
            fallback_title=fallback_title,
            fallback_description=fallback_description,
        )

    def _fetch_post_details(self, token: str, include_contact: bool = True) -> Dict[str, Any]:
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
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'fa-IR,fa;q=0.9,en-US;q=0.8',
            }
            resp = requests.get(url, headers=headers, timeout=3)
            if resp and resp.status_code == 200:
                data = resp.json()

                # ممیزی ساختاری با متادیتای رسمی webengage دیوار
                webengage = data.get('webengage', {})
                if isinstance(webengage, dict):
                    # ۱. گاردریل عدم پذیرش کالاهای غیرملکی (فرش، لوازم، خدمات و...)
                    cat_1 = str(webengage.get('cat_1', '')).lower()
                    if cat_1 and cat_1 != 'real-estate':
                        details['is_non_real_estate'] = True
                        return details

                    # ۲. بررسی پرچم رسمی نوع حساب دیوار (personal vs business)
                    biz_type = str(webengage.get('business_type', '')).lower()
                    if biz_type and biz_type != 'personal':
                        details['is_agency_post'] = True

                    # ۳. استخراج مستقیم مقادیر مالی در صورت وجود
                    if webengage.get('price'):
                        details['total_price'] = int(webengage['price'])
                    if webengage.get('credit'):
                        details['deposit'] = int(webengage['credit'])
                    if webengage.get('rent'):
                        details['monthly_rent'] = int(webengage['rent'])

                sections = data.get('sections', [])
                images: List[str] = []
                features: List[str] = []

                for sec in sections:
                    sec_name = str(sec.get('section_name', '')).upper()
                    if any(bs in sec_name for bs in ['BUSINESS_SECTION', 'AGENCY_SECTION', 'SELLER_PROFILE', 'BUSINESS']):
                        details['is_agency_post'] = True

                    for w in sec.get('widgets', []):
                        wt = w.get('widget_type', '')
                        wd = w.get('data', {})

                        # ۰. بررسی و رد ویجت‌های اختصاصی پنل‌های املاک و اکانت‌های تجاری دیوار
                        if wt == 'LAZY_SECTION':
                            req_data = wd.get('request_data', {})
                            biz_type = str(req_data.get('post_business_type', '')).lower()
                            if biz_type in ['premium-panel', 'business', 'agency', 'consultant', 'real_estate_agency']:
                                details['is_agency_post'] = True
                        elif any(x in wt.lower() for x in ['agency_info', 'business_section', 'seller_profile', 'consultant', 'agent_info']):
                            details['is_agency_post'] = True

                        # بررسی تاریخ و عنوان در EXPANDABLE_SECTION (مثل: ۶ روز پیش در سعادت آباد)
                        if wt == 'EXPANDABLE_SECTION':
                            exp_title = wd.get('title', '')
                            details['time_title'] = exp_title
                            if is_stale_ad(exp_title):
                                details['is_stale_post'] = True

                        # ممیزی ویجت‌های تبلیغ‌کننده برای اصطلاحات دپارتمان، هلدینگ، مشاور و املاک (به استثنای ویجت‌های سیستمی دیوار)
                        if wt not in ['SELECTOR_ROW', 'FEEDBACK_ROW', 'REPORT_ROW', 'SHARE_ROW', 'SAFETY_ROW', 'BREADCRUMB_ROW', 'TAG_ROW', 'DESCRIPTION_ROW', 'UNEXPANDABLE_ROW', 'GROUP_INFO_ROW', 'GROUP_FEATURE_ROW', 'IMAGE_CAROUSEL']:
                            w_text = f"{wd.get('title', '')} {wd.get('subtitle', '')} {wd.get('text', '')}"
                            if any(term in w_text for term in OwnerFilter.NON_PERSONAL_ACCOUNT_TERMS):
                                details['is_agency_post'] = True

                        # ۱. شرح کامل آگهی
                        if wt == 'DESCRIPTION_ROW':
                            details['description'] = wd.get('text', '')

                        # ۲. گالری تصاویر اصلی CDN با تضمین بالاترین وضوح (ارتقا به webp_post باکیفیت)
                        elif wt in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER_ROW', 'IMAGES_ROW', 'IMAGE_SLIDER', 'IMAGE_ROW'] or 'IMAGE' in wt:
                            for item in wd.get('items', []):
                                if isinstance(item, dict):
                                    img_url = (
                                        item.get('image', {}).get('url') or 
                                        item.get('image', {}).get('thumbnail_url') or 
                                        item.get('url') or 
                                        item.get('src')
                                    )
                                elif isinstance(item, str) and item.startswith(('http://', 'https://')):
                                    img_url = item
                                else:
                                    img_url = None

                                if img_url:
                                    # ارتقای خودکار تامبنیل‌ها به رزولوشن اصلی دیوار (Full HD)
                                    hi_res = (
                                        img_url.replace('/webp_thumbnail/', '/webp_post/')
                                               .replace('/thumbnail/', '/post/')
                                               .replace('/webp_medium/', '/webp_post/')
                                               .replace('/medium/', '/post/')
                                    )
                                    if hi_res not in images:
                                        images.append(hi_res)

                        # ۳. اطلاعات سه‌گانه کلیدی بالای صفحه (متراژ، سال ساخت، تعداد اتاق)
                        if wt in ['GROUP_INFO_ROW', 'UNEXPANDABLE_ROW'] and wd.get('items'):
                            for item in wd.get('items', []):
                                title = item.get('title', '')
                                val = item.get('value', '')
                                val_en = persian_to_english_numbers(val)
                                if 'متراژ' in title:
                                    details['area'] = parse_area(val_en)
                                elif 'ساخت' in title:
                                    m_y = re.search(r'\d+', val_en)
                                    if m_y:
                                        details['build_year'] = int(m_y.group(0))
                                elif 'اتاق' in title:
                                    if 'بدون' in val:
                                        details['rooms'] = 0
                                    else:
                                        m_r = re.search(r'\d+', val_en)
                                        if m_r:
                                            details['rooms'] = int(m_r.group(0))

                        # ۴. ردیف‌های مقداری ساختاریافته دیوار (ودیعه، اجاره، قیمت کل، قیمت هر متر، طبقه و قابلیت تبدیل)
                        if wt in ['UNEXPANDABLE_ROW', 'LIST_DATA_ROW'] and (wd.get('title') or wd.get('value')):
                            t = wd.get('title', '')
                            v = wd.get('value', '')
                            v_en = persian_to_english_numbers(v)

                            if 'ودیعه و اجاره' in t or 'تبدیل' in t:
                                details['conversion_note'] = v
                                if 'قابل تبدیل' in v and 'غیر' not in v:
                                    details['is_convertible'] = True
                                features.append(f"ودیعه و اجاره: {v}")
                            elif 'ودیعه' in t or 'رهن' in t:
                                details['deposit'] = parse_price(v)
                            elif 'اجاره' in t:
                                details['monthly_rent'] = parse_price(v)
                            elif 'قیمت هر متر' in t:
                                details['meter_price'] = parse_price(v)
                            elif 'قیمت کل' in t or 'قیمت' in t:
                                details['total_price'] = parse_price(v)
                            elif 'طبقه' in t:
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

                # تصاویر تکمیلی از web_images و seo و share در صورت وجود
                for wimg in data.get('web_images', []):
                    if isinstance(wimg, dict):
                        u = wimg.get('src') or wimg.get('url')
                    elif isinstance(wimg, str):
                        u = wimg
                    else:
                        u = None
                    if u and u not in images and 'divarcdn.com' in u:
                        images.append(u)

                seo_obj = data.get('seo', {})
                seo_schema = seo_obj.get('post_seo_schema', {}) if isinstance(seo_obj, dict) else {}
                seo_img = (
                    (seo_schema.get('image') if isinstance(seo_schema, dict) else None) or 
                    (seo_obj.get('image_url') if isinstance(seo_obj, dict) else None)
                )
                if seo_img and isinstance(seo_img, str) and seo_img not in images and 'divarcdn.com' in seo_img:
                    images.insert(0, seo_img)

                share_img = data.get('share', {}).get('image_url')
                if share_img and isinstance(share_img, str) and share_img not in images and 'divarcdn.com' in share_img:
                    images.append(share_img)

                # بالکن از متن یا ویژگی‌ها
                desc_text = details['description'] or ''
                if 'بالکن' in desc_text or any('بالکن' in f for f in features):
                    details['has_balcony'] = True

                details['images'] = images
                details['features'] = features

        except Exception:
            pass

        # اولویت نخست: DOM واقعی صفحه آگهی، بدون اجرای مرورگر یا جاوااسکریپت.
        dom_details = self.fetch_post_dom_details(
            token,
            fallback_description=details.get('description') or '',
            include_contact=include_contact,
        )
        if dom_details.get('description') and not details.get('description'):
            details['description'] = dom_details['description']
        if dom_details.get('is_agency_post'):
            details['is_agency_post'] = True
        details['dom_owner_filter_status'] = dom_details.get('owner_filter_status')
        details['dom_owner_filter_reason'] = dom_details.get('owner_filter_reason')

        if (
            include_contact
            and not details.get('is_agency_post')
            and dom_details.get('is_personal_owner')
            and dom_details.get('phone')
        ):
            details['phone'] = dom_details['phone']
            details['phone_source'] = dom_details.get('phone_source') or 'dom'
            details['phone_confidence'] = dom_details.get('phone_confidence', 0)

        normalized_token = self.normalize_post_token(token)

        # فال‌بک HTTP احراز‌شده دیوار؛ این مسیر نیز از Chromium استفاده نمی‌کند.
        if include_contact and not details.get('phone') and not details.get('is_agency_post') and normalized_token:
            try:
                from crawler.divar_session_manager import DivarSessionManager
                direct_phone = DivarSessionManager.fetch_contact_phone(normalized_token)
                if direct_phone:
                    details['phone'] = direct_phone
                    details['phone_source'] = 'divar_authenticated_http_api'
                    details['phone_confidence'] = 100
            except Exception:
                pass

        # آخرین فال‌بک: شماره‌ای که خود مالک در توضیحات عمومی آگهی نوشته است.
        if include_contact and not details.get('phone') and not details.get('is_agency_post'):
            ph = extract_phone_number(details.get('description') or '', filter_dummy=True)
            if ph:
                details['phone'] = ph
                details['phone_source'] = 'description_text'
                details['phone_confidence'] = 72

        return details

    def _build_validated_item(
        self,
        cand: Dict[str, Any],
        post_details: Dict[str, Any],
        category_meta: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None
    ) -> Optional[NormalizedPropertySchema]:
        """اعتبارسنجی نهایی، فیلترینگ سخت‌گیرانه، محاسبه امتیاز و ساخت شیء نرمالایز شده"""
        if post_details.get('is_non_real_estate'):
            return None
        if post_details.get('is_agency_post'):
            return None
        if post_details.get('is_stale_post'):
            return None

        token = cand['token']
        title = cand['title']
        source_id = cand['source_id']
        district = cand['district']
        middle_desc = cand['middle_desc']
        bottom_desc = cand['bottom_desc']
        raw_img = cand.get('raw_img')
        d = cand.get('d', {})

        # فیلترینگ جغرافیایی هوشمند (منطقه یا محله در صورت درخواست)
        req_districts = (filters or {}).get('districts', [])
        if req_districts:
            matched_d = False
            for rd in req_districts:
                rd_clean = (rd or '').strip()
                if not rd_clean or rd_clean in ['all', 'تهران', 'کل شهر', 'همه']:
                    matched_d = True
                    break
                if any(x in rd_clean for x in ['منطقه ۵', 'منطقه 5', 'منطقه ۲', 'منطقه 2']):
                    if is_in_region_2_or_5(district, f"{title} {middle_desc} {bottom_desc}"):
                        matched_d = True
                        break
                elif rd_clean in district or rd_clean in title or rd_clean in middle_desc:
                    matched_d = True
                    break
            if not matched_d:
                return None

        # رد قطعی آگهی‌های تاریخ‌گذشته (۲ روز پیش به بالا، ۶ روز پیش، هفته‌های قبل)
        time_check_text = f"{bottom_desc} {middle_desc} {post_details.get('time_title', '')}"
        if is_stale_ad(time_check_text):
            return None

        deal_type = category_meta['deal_type']
        prop_type = category_meta['property_type']

        real_desc = post_details.get('description', '')
        all_images = list(post_details.get('images', []))
        if raw_img and raw_img not in all_images and 'divarcdn.com' in raw_img:
            all_images.insert(0, raw_img)

        final_desc = real_desc or ''

        # فیلتر مرحله دوم: بررسی سخت‌گیرانه روی متن کامل آگهی جهت حذف واسطه‌ها
        full_filter_res = OwnerFilter.evaluate(
            platform='divar',
            title=title,
            description=final_desc,
            widget_data=d,
            raw_text=f"{middle_desc} {bottom_desc}"
        )
        if not full_filter_res.is_personal:
            return None

        # فیلتر ثانویه سخت‌گیرانه حذف همخونه در متن کامل
        if any(kw in f"{final_desc} {title}".lower() for kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS):
            return None

        # مالی
        total_price = 0
        meter_price = 0
        deposit = 0
        monthly_rent = 0

        if deal_type == 'sale':
            total_price = post_details.get('total_price') or (parse_price(middle_desc) if any(x in middle_desc for x in ['میلیارد', 'تومان', 'قیمت']) else 0)
            meter_price = post_details.get('meter_price') or 0
        else:
            deposit = post_details.get('deposit') or (parse_price(middle_desc) if any(x in middle_desc for x in ['ودیعه', 'رهن', 'میلیارد', 'میلیون']) else 0)
            monthly_rent = post_details.get('monthly_rent') or (parse_price(bottom_desc) if 'اجاره' in bottom_desc else 0)

        total_price, deposit, monthly_rent = sanitize_property_financials(
            deal_type=deal_type,
            total_price=total_price,
            deposit=deposit,
            monthly_rent=monthly_rent,
            property_type=prop_type
        )

        features = list(post_details.get('features', []))
        from crawler.schemas import calculate_mortgage_conversion
        if deal_type == 'rent':
            conv = calculate_mortgage_conversion(deposit, monthly_rent)
            full_mortgage_val = conv.get('full_mortgage_equivalent', 0)
            if full_mortgage_val > 0:
                features.append(f"معادل رهن کامل: {int(full_mortgage_val / 1_000_000):,} میلیون تومان")
                features.append("عرف تبدیل: هر ۱۰۰ میلیون رهن = ۳ میلیون اجاره")
            if post_details.get('conversion_note'):
                features.append(f"وضعیت تبدیل: {post_details['conversion_note']}")

        # ابعاد و مشخصات
        combined_text = f"{title} {middle_desc} {bottom_desc} {final_desc}"
        area = post_details.get('area') or d.get('area') or self._extract_area(combined_text)
        if not area or parse_area(area) < 5:
            return None
        rooms = post_details.get('rooms')
        if rooms is None:
            rooms = self._extract_rooms(combined_text) or 0

        if area > 0 and total_price > 0 and not meter_price:
            meter_price = int(total_price / area)

        floor = post_details.get('floor')
        total_floors = post_details.get('total_floors')
        build_year = post_details.get('build_year') or d.get('build_year')

        has_elevator = post_details.get('has_elevator', False)
        has_parking = post_details.get('has_parking', False)
        has_warehouse = post_details.get('has_warehouse', False)
        has_balcony = post_details.get('has_balcony', False)

        # بررسی انطباق دقیق با فیلترهای درخواستی کاربر
        if filters:
            req_districts = filters.get('districts', [])
            if req_districts:
                matched_d = False
                for rd in req_districts:
                    rd_clean = (rd or '').strip()
                    if rd_clean and rd_clean not in ['all', 'تهران', 'کل شهر', 'همه']:
                        if rd_clean in district or rd_clean in title or rd_clean in final_desc:
                            matched_d = True
                            break
                    else:
                        matched_d = True
                        break
                if not matched_d:
                    return None

            if deal_type == 'rent':
                min_dep = filters.get('min_deposit')
                max_dep = filters.get('max_deposit')
                min_r = filters.get('min_rent')
                max_r = filters.get('max_rent')
                if min_dep and deposit < min_dep:
                    return None
                if max_dep and deposit > max_dep:
                    return None
                if min_r and monthly_rent < min_r:
                    return None
                if max_r and monthly_rent > max_r:
                    return None
            else:
                min_p = filters.get('min_price')
                max_p = filters.get('max_price')
                if min_p and total_price < min_p:
                    return None
                if max_p and total_price > max_p:
                    return None

            min_a = filters.get('min_area')
            max_a = filters.get('max_area')
            if min_a and area < min_a:
                return None
            if max_a and area > max_a:
                return None

            # فیلتر سن بنا و سال ساخت (بر مبنای سال ۱۴۰۳)
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

            if filters.get('rooms') and rooms < int(filters.get('rooms')):
                return None

            if filters.get('has_parking') and not has_parking:
                return None

            if filters.get('has_elevator') and not (has_elevator or (floor and floor <= 1)):
                return None

            if filters.get('has_warehouse') and not has_warehouse:
                return None

            if filters.get('has_balcony') and not has_balcony:
                return None

        # استخراج شماره تماس واقعی
        extracted_phone = extract_phone_number(
            post_details.get('phone') or f"{final_desc} {title}",
            filter_dummy=True,
        )
        owner_phone = extracted_phone if extracted_phone else ""
        source_url = f"https://divar.ir/v/{token}"

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
                'notes': (
                    f"ثبت خودکار از کراولر دیوار برای منطقه {district}. "
                    f"{'(منبع شماره: ' + str(post_details.get('phone_source') or 'متن عمومی') + ')' if extracted_phone else '(شماره در دیوار محفوظ است)'}"
                )
            }
        }

        try:
            return NormalizedPropertySchema(**item_dict)
        except Exception:
            return None

    def _parse_html_state(self, html_text: str, category_meta: Dict[str, Any], limit: int, filters: Optional[Dict[str, Any]] = None, on_item_found: Optional[Callable[[NormalizedPropertySchema], None]] = None) -> Tuple[List[NormalizedPropertySchema], bool, int, Optional[str]]:
        results: List[NormalizedPropertySchema] = []
        reached_limit = False
        total_raw_widgets = 0
        next_last_post_date = None

        # استخراج از window.__PRELOADED_STATE__
        match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', html_text)
        if match:
            try:
                state_data = json.loads(match.group(1))
                nb = state_data.get('nb', {})
                widgets = nb.get('listWidgets', [])
                total_raw_widgets = len(widgets)
                pag_data = nb.get('pagination', {})
                if isinstance(pag_data, dict):
                    next_last_post_date = pag_data.get('data', {}).get('last_post_date') or pag_data.get('last_post_date')
                if not next_last_post_date:
                    next_last_post_date = nb.get('last_post_date')
                candidates: List[Dict[str, Any]] = []

                for w in widgets:
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

                    # فیلترینگ جغرافیایی هوشمند بر اساس محله‌های درخواستی
                    req_districts = (filters or {}).get('districts', [])
                    if req_districts:
                        matched_d = False
                        for rd in req_districts:
                            rd_clean = (rd or '').strip()
                            if not rd_clean or rd_clean in ['all', 'تهران', 'کل شهر', 'همه']:
                                matched_d = True
                                break
                            if any(x in rd_clean for x in ['منطقه ۵', 'منطقه 5', 'منطقه ۲', 'منطقه 2']):
                                if is_in_region_2_or_5(district, f"{title} {bottom_desc} {middle_desc}"):
                                    matched_d = True
                                    break
                            elif rd_clean in district or rd_clean in title or rd_clean in bottom_desc:
                                matched_d = True
                                break
                        if not matched_d:
                            continue

                    # ۰. رد فوری و قطعی پنل‌ها و مشاوران املاک از متن توصیفی پایین ویجت
                    if any(term in bottom_desc for term in ['مشاور', 'آژانس', 'املاک', 'دپارتمان', 'مسکن', 'هلدینگ', 'کارشناس', 'بنگاه', 'دفتر', 'گروه']):
                        continue

                    # ۱. بررسی بازه زمانی: رد فوری آگهی‌های تاریخ‌گذشته و غیرلحظه‌ای (اولویت با انتشار لحظه‌ای و روز جاری)
                    if is_stale_ad(bottom_desc) or is_stale_ad(middle_desc):
                        continue

                    # ۲. فیلتر سریع حذف آگهی‌های همخونه
                    combined_initial_text = f"{title} {middle_desc} {bottom_desc}".lower()
                    if any(kw in combined_initial_text for kw in OwnerFilter.SHARED_HOUSING_NEGATIVE_KEYWORDS):
                        continue

                    # ۳. فیلتر مرحله اول: بررسی متادیتای اولیه
                    filter_res = OwnerFilter.evaluate(
                        platform='divar',
                        title=title,
                        description=middle_desc,
                        widget_data=d,
                        raw_text=bottom_desc
                    )
                    if not filter_res.is_personal:
                        _console(f"[DivarFilter] ❌ {token}: {title[:28]} -> {filter_res.reason} {filter_res.detected_terms}")
                        continue

                    raw_img = (
                        d.get('image_url') or 
                        (d.get('image', {}).get('url') if isinstance(d.get('image'), dict) else None) or
                        (d.get('images')[0] if isinstance(d.get('images'), list) and d.get('images') and isinstance(d.get('images')[0], str) else None) or
                        d.get('top_image_url') or
                        d.get('middle_description_image_url')
                    )
                    if raw_img:
                        raw_img = (
                            raw_img.replace('/webp_thumbnail/', '/webp_post/')
                                   .replace('/thumbnail/', '/post/')
                                   .replace('/webp_medium/', '/webp_post/')
                                   .replace('/medium/', '/post/')
                        )

                    candidates.append({
                        'token': token,
                        'title': title,
                        'source_id': source_id,
                        'district': district,
                        'middle_desc': middle_desc,
                        'bottom_desc': bottom_desc,
                        'raw_img': raw_img,
                        'd': d
                    })

                    # گردآوری کاندیدهای واجد شرایط این صفحه تا سقف مورد نیاز
                    if len(candidates) >= max(limit * 2, 14):
                        break

                # واکشی همروند (Concurrent) جزئیات کاندیدها با حداکثر ۶ ورکر جهت سرعت فوق‌العاده
                if candidates:
                    with ThreadPoolExecutor(max_workers=6) as executor:
                        future_to_cand = {executor.submit(self._fetch_post_details, c['token']): c for c in candidates}
                        for future in as_completed(future_to_cand):
                            cand = future_to_cand[future]
                            try:
                                post_details = future.result()
                                validated = self._build_validated_item(cand, post_details, category_meta, filters)
                                if validated:
                                    results.append(validated)
                                    dedup_engine.mark_seen(cand['source_id'])
                                    if on_item_found:
                                        try:
                                            on_item_found(validated)
                                        except Exception:
                                            pass
                                    if len(results) >= limit:
                                        break
                            except Exception:
                                pass

            except Exception as e:
                pass

        return results, reached_limit, total_raw_widgets, next_last_post_date

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
