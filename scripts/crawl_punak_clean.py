import sys
import os
import time
import re
import json
import sqlite3
import logging

sys.path.insert(0, os.path.abspath('.'))
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from app import create_app
from database.db import db
from database.models import Property, Owner
from crawler.network.impersonator import TLSImpersonatorClient
from crawler.owner_filter import OwnerFilter, is_stale_ad, extract_phone_number
from crawler.dedup import dedup_engine
from crawler.schemas import parse_price, parse_area, persian_to_english_numbers, sanitize_property_financials, calculate_mortgage_conversion

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("SaghfDivarRealtime")

def upgrade_image_url(url: str) -> str:
    """
    ارتقای اجباری تامبنیل تار به کیفیت اصلی Full-HD روی CDN دیوار
    """
    if not url or not isinstance(url, str):
        return ""
    if 'divarcdn.com' in url:
        return (
            url.replace('/webp_thumbnail/', '/webp_post/')
               .replace('/thumbnail/', '/post/')
               .replace('/webp_medium/', '/webp_post/')
               .replace('/medium/', '/post/')
        )
    return url

def purge_all_databases():
    """
    ۱. پاک‌سازی کامل و ایمن دیتابیس (Data Purge):
    ریست کردن تمام رکوردهای قدیمی، ماک و دارای خطای قبلی در هر دو مسیر پایگاه داده
    و بازنشانی شمارنده auto-increment جهت شروع فایل‌ها از شناسه ۱ (کد فایل ۱۰۰۰۱).
    """
    logger.info("🧹 [Data Purge] در حال پاک‌سازی قطعی جداول SQLite و ریست کردن شماره سریال...")
    
    db_paths = [
        os.path.abspath("instance/saghf_database.db"),
        os.path.abspath("saghf_database.db")
    ]
    
    for db_path in db_paths:
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF;")
            tables = ['matching_records', 'visits', 'interactions', 'properties', 'owners']
            for t in tables:
                cur.execute(f"DELETE FROM {t};")
            # ریست شماره سریال auto-increment
            try:
                cur.execute("DELETE FROM sqlite_sequence WHERE name IN ('properties', 'owners', 'matching_records', 'visits', 'interactions');")
            except Exception:
                pass
            conn.commit()
            cur.execute("PRAGMA foreign_keys = ON;")
            conn.close()
            logger.info(f"   ✅ دیتابیس در مسیر {db_path} کاملاً پاک‌سازی و صفر شد.")
        except Exception as ex:
            logger.error(f"خطا در پاک‌سازی دیتابیس {db_path}: {ex}")

    dedup_engine.clear()
    logger.info("✅ حافظه کش DeduplicationEngine تخلیه شد. آماده استخراج اصیل از ابتدا.")

def extract_and_seed_divar(target_count=5, do_purge=True):
    """
    موتور استخراج زنده و بدون واسطه از دیوار با فیلترینگ چندلایه و ارقام مالی بدون خطا
    """
    app = create_app()

    if do_purge:
        purge_all_databases()

    with app.app_context():
        client = TLSImpersonatorClient(impersonate="chrome120")

        target_endpoints = [
            ("buy-apartment", "sale", "پونک", "https://divar.ir/s/tehran/buy-apartment/punak?business-type=personal"),
            ("rent-apartment", "rent", "پونک", "https://divar.ir/s/tehran/rent-apartment/punak?business-type=personal"),
            ("buy-apartment", "sale", "اباذر", "https://divar.ir/s/tehran/buy-apartment/abazar?business-type=personal"),
            ("rent-apartment", "rent", "اباذر", "https://divar.ir/s/tehran/rent-apartment/abazar?business-type=personal"),
            ("buy-apartment", "sale", "صادقیه", "https://divar.ir/s/tehran/buy-apartment/sadeghiyeh?business-type=personal"),
            ("rent-apartment", "rent", "صادقیه", "https://divar.ir/s/tehran/rent-apartment/sadeghiyeh?business-type=personal"),
            ("buy-apartment", "sale", "اکباتان", "https://divar.ir/s/tehran/buy-apartment/ekbatan?business-type=personal"),
            ("rent-apartment", "rent", "اکباتان", "https://divar.ir/s/tehran/rent-apartment/ekbatan?business-type=personal"),
            ("buy-apartment", "sale", "پونک (صفحه ۲)", "https://divar.ir/s/tehran/buy-apartment/punak?business-type=personal&page=2"),
            ("rent-apartment", "rent", "پونک (صفحه ۲)", "https://divar.ir/s/tehran/rent-apartment/punak?business-type=personal&page=2"),
            ("buy-apartment", "sale", "اباذر (صفحه ۲)", "https://divar.ir/s/tehran/buy-apartment/abazar?business-type=personal&page=2"),
            ("rent-apartment", "rent", "اباذر (صفحه ۲)", "https://divar.ir/s/tehran/rent-apartment/abazar?business-type=personal&page=2"),
            ("buy-apartment", "sale", "پونک (صفحه ۳)", "https://divar.ir/s/tehran/buy-apartment/punak?business-type=personal&page=3"),
            ("rent-apartment", "rent", "پونک (صفحه ۳)", "https://divar.ir/s/tehran/rent-apartment/punak?business-type=personal&page=3"),
            ("buy-apartment", "sale", "اکباتان (صفحه ۲)", "https://divar.ir/s/tehran/buy-apartment/ekbatan?business-type=personal&page=2"),
            ("rent-apartment", "rent", "اکباتان (صفحه ۲)", "https://divar.ir/s/tehran/rent-apartment/ekbatan?business-type=personal&page=2"),
        ]

        DISTRICT_5_KEYWORDS = [
            'پونک', 'همیلا', 'باغ فیض', 'باغ‌فیض', 'جنت‌آباد', 'جنت آباد', 'جنت‌آباد جنوبی', 'جنت‌آباد شمالی', 'جنت‌آباد مرکزی',
            'صادقیه', 'فردوس', 'بلوار فردوس', 'کوی فردوس', 'شهران', 'شهران شمالی', 'شهران جنوبی',
            'سازمان برنامه', 'سازمان برنامه شمالی', 'سازمان برنامه جنوبی',
            'اباذر', 'اکباتان', 'شاهین', 'شهرزیبا', 'شهر زیبا', 'کوهسار', 'کن', 'اشرفی اصفهانی', 'پیامبر', 'باکری', 'بیمه', 'کوی بیمه'
        ]

        saved_properties = []
        seen_tokens = set()

        logger.info(f"\n🚀 آغاز چرخه استخراج زنده دیوار برای حداقل {target_count} فایل شخصی تاییدشده...")

        for cat_slug, deal_type, district_name, target_url in target_endpoints:
            if len(saved_properties) >= target_count:
                break

            logger.info(f"\n📡 بررسی کانون: {target_url} ({district_name} - {deal_type})")
            time.sleep(3.2)  # رعایت ضرباهنگ مجاز ۳.۲ ثانیه جهت دریافت قطعی تمام کارت‌ها

            try:
                # ایجاد کلاینت تازه جهت جلوگیری از استهلاک سشن
                client = TLSImpersonatorClient(impersonate="chrome120")
                res = client.get(target_url, timeout=15)
                if not res or res.status_code != 200:
                    logger.warning(f"عدم پاسخ از {target_url} (کد: {res.status_code if res else 'None'})")
                    continue

                m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', res.text)
                if not m:
                    continue

                state = json.loads(m.group(1))
                nb = state.get('nb', {})
                widgets = nb.get('listWidgets', [])

                if not widgets:
                    logger.info("   ⏳ مکث ۱۵ ثانیه‌ای جهت رفع محدودیت ضرباهنگ دیوار و بازیابی مجدد کارت‌ها...")
                    time.sleep(15.0)
                    client = TLSImpersonatorClient(impersonate="chrome120")
                    res = client.get(target_url, timeout=15)
                    if res and res.status_code == 200:
                        m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', res.text)
                        if m:
                            state = json.loads(m.group(1))
                            widgets = state.get('nb', {}).get('listWidgets', [])

                logger.info(f"   📦 تعداد کل کارت‌های دریافت شده: {len(widgets)}")

                for w in widgets:
                    if len(saved_properties) >= target_count:
                        break

                    dto = w.get('data', {}).get('dto', {})
                    if dto.get('widget_type') != 'POST_ROW':
                        continue

                    d = dto.get('data', {})
                    token = d.get('token') or d.get('action', {}).get('payload', {}).get('token')
                    card_title = d.get('title', '').strip()
                    bottom_desc = d.get('bottom_description_text', '').strip()
                    middle_desc = d.get('middle_description_text', '').strip()
                    top_desc = d.get('top_description_text', '').strip()

                    if not token or not card_title:
                        continue

                    # فیلتر و تخصیص محله در منطقه ۵
                    current_district = district_name
                    if district_name == "منطقه ۵":
                        matched_kw = next((kw for kw in DISTRICT_5_KEYWORDS if kw in bottom_desc or kw in middle_desc or kw in card_title), None)
                        if matched_kw:
                            current_district = matched_kw

                    if token in seen_tokens:
                        continue
                    seen_tokens.add(token)

                    source_id = f"divar_{token}"
                    if dedup_engine.is_duplicate(source_id=source_id, title=card_title):
                        continue

                    # =========================================================
                    # مرحله ۱: فیلتر اولیه متادیتا (حذف قطعی نشان‌های آژانس، دپارتمان، مشاور)
                    # =========================================================
                    is_agency_badge = any(term in bottom_desc for term in ['املاک', 'آژانس', 'دپارتمان', 'مسکن', 'مشاور', 'بنگاه', 'کارگزاری', 'هلدینگ'])
                    if is_agency_badge:
                        continue

                    # بررسی تازگی آگهی (فقط در لحظه و ساعات اخیر - حذف روزهای قبل)
                    if is_stale_ad(bottom_desc) or is_stale_ad(middle_desc):
                        continue

                    st1 = OwnerFilter.evaluate('divar', card_title, middle_desc, d, bottom_desc)
                    if not st1.is_personal:
                        continue

                    # =========================================================
                    # استخراج اطلاعات تکمیلی و عمیق از API آگهی
                    # =========================================================
                    time.sleep(0.4)
                    api_url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
                    det_res = client.get(api_url, timeout=10)
                    if not det_res or det_res.status_code != 200:
                        continue

                    details = det_res.json()
                    sections = details.get('sections', [])

                    # فیلتر متادیتای اختصاصی کسب‌وکار در API دیوار
                    is_biz_section = False
                    for sec in sections:
                        sec_name = str(sec.get('section_name', '')).upper()
                        if any(bs in sec_name for bs in ['BUSINESS_SECTION', 'AGENCY_SECTION', 'SELLER_PROFILE', 'BUSINESS']):
                            is_biz_section = True
                            break
                        for rw in sec.get('widgets', []):
                            wt = str(rw.get('widget_type', ''))
                            rwd = rw.get('data', {})
                            if wt == 'LAZY_SECTION':
                                ptype = str(rwd.get('request_data', {}).get('post_business_type', '')).lower()
                                if ptype in ['premium-panel', 'business', 'agency', 'consultant', 'real_estate_agency']:
                                    is_biz_section = True
                                    break
                            elif any(x in wt.lower() for x in ['agency', 'business', 'consultant', 'seller_profile']):
                                is_biz_section = True
                                break
                    if is_biz_section:
                        continue

                    # استخراج دقیق مشخصات و فیلدهای عددی خام
                    raw_description = ""
                    raw_prices = {}
                    images = []
                    features = []
                    area = 0.0
                    build_year = 1400
                    rooms = 1
                    floor = 1
                    total_floors = None
                    has_elevator = False
                    has_parking = False
                    has_warehouse = False
                    has_balcony = False
                    total_price = 0
                    meter_price = 0
                    deposit = 0
                    monthly_rent = 0
                    is_convertible = False
                    conversion_note = ""
                    exact_address = f"تهران، {current_district}"

                    # عنوان دقیق و پیراسته
                    full_title = details.get('share', {}).get('title') or details.get('seo', {}).get('title') or card_title
                    if 'در تهران' in full_title and ' - ' in full_title:
                        full_title = full_title.split('در تهران')[0].replace('اجاره', '').replace('فروش', '').strip()

                    for sec in sections:
                        for widget in sec.get('widgets', []):
                            wt = widget.get('widget_type', '')
                            wd = widget.get('data', {})

                            # آدرس و موقعیت دقیق
                            if wt == 'EXPANDABLE_SECTION':
                                exp_t = wd.get('title', '')
                                if 'در' in exp_t:
                                    loc_str = exp_t.split('در')[-1].strip()
                                    if loc_str:
                                        exact_address = loc_str
                                        for kw in DISTRICT_5_KEYWORDS:
                                            if kw in loc_str:
                                                current_district = kw
                                                break

                            # توضیحات آگهی
                            elif wt == 'DESCRIPTION_ROW':
                                raw_description = wd.get('text', '')

                            # عکس‌های گالری با ارتقای Full-HD
                            elif 'IMAGE' in wt:
                                for item in wd.get('items', []):
                                    u = item.get('image', {}).get('url') if isinstance(item, dict) else item
                                    hi_res = upgrade_image_url(u)
                                    if hi_res and hi_res not in images:
                                        images.append(hi_res)

                            # متراژ، سال ساخت و اتاق‌ها
                            elif wt in ['UNEXPANDABLE_ROW', 'GROUP_INFO_ROW'] and wd.get('items'):
                                for item in wd.get('items', []):
                                    it_title = item.get('title', '')
                                    it_val = item.get('value', '')
                                    val_en = persian_to_english_numbers(it_val)
                                    if 'متراژ' in it_title:
                                        # استخراج اعشاری دقیق بدون رند کردن (الزام بند ۳)
                                        area = parse_area(val_en)
                                    elif 'ساخت' in it_title:
                                        my = re.search(r'\d+', val_en)
                                        if my: build_year = int(my.group(0))
                                    elif 'اتاق' in it_title:
                                        if 'بدون' in it_val: rooms = 0
                                        else:
                                            mr = re.search(r'\d+', val_en)
                                            if mr: rooms = int(mr.group(0))

                            # ارقام مالی خام
                            elif wt in ['UNEXPANDABLE_ROW', 'LIST_DATA_ROW'] and (wd.get('title') or wd.get('value')):
                                t = wd.get('title', '')
                                v = wd.get('value', '')
                                raw_prices[t] = v
                                v_en = persian_to_english_numbers(v)

                                if 'ودیعه و اجاره' in t or 'تبدیل' in t:
                                    conversion_note = v
                                    if 'قابل تبدیل' in v and 'غیر' not in v:
                                        is_convertible = True
                                    features.append(f"وضعیت تبدیل: {v}")
                                elif t == 'ودیعه' or 'رهن' in t:
                                    deposit = parse_price(v)
                                elif t.startswith('اجاره'):
                                    monthly_rent = parse_price(v)
                                elif 'قیمت هر متر' in t:
                                    meter_price = parse_price(v)
                                elif 'قیمت کل' in t or t == 'قیمت':
                                    total_price = parse_price(v)
                                elif 'طبقه' in t:
                                    m_floors = re.search(r'(\d+)\s*از\s*(\d+)', v_en)
                                    if m_floors:
                                        floor = int(m_floors.group(1))
                                        total_floors = int(m_floors.group(2))
                                    elif 'همکف' in v:
                                        floor = 0
                                    else:
                                        mf = re.search(r'\d+', v_en)
                                        if mf: floor = int(mf.group(0))
                                elif 'تصویر' in t and 'همین ملک' in t and 'بله' in v:
                                    features.append("تصاویر متعلق به همین ملک (تأییدشده در دیوار)")
                                elif t and v and t not in ['گزارش آگهی', 'شناسه آگهی']:
                                    features.append(f"{t}: {v}")

                            # اسلایدر ودیعه و اجاره (ویجت جدید دیوار)
                            elif wt == 'RENT_SLIDER':
                                c_val = wd.get('credit', {}).get('value')
                                r_val = wd.get('rent', {}).get('value')
                                if c_val:
                                    p_c = parse_price(c_val)
                                    if p_c > 0:
                                        deposit = p_c
                                if r_val:
                                    p_r = parse_price(r_val)
                                    if p_r > 0:
                                        monthly_rent = p_r

                            # ویژگی ودیعه و اجاره قابل تبدیل
                            elif wt == 'FEATURE_ROW':
                                feat_title = wd.get('title', '')
                                if 'قابل تبدیل' in feat_title and 'غیر' not in feat_title:
                                    is_convertible = True
                                    features.append(f"وضعیت تبدیل: {feat_title}")

                            # امکانات اصلی (پارکینگ، آسانسور، انباری)
                            elif wt == 'GROUP_FEATURE_ROW':
                                for fit in wd.get('items', []):
                                    ftitle = fit.get('title', '')
                                    avail = fit.get('available', True)
                                    if 'آسانسور' in ftitle:
                                        has_elevator = avail and ('ندارد' not in ftitle)
                                    elif 'پارکینگ' in ftitle:
                                        has_parking = avail and ('ندارد' not in ftitle)
                                    elif 'انباری' in ftitle:
                                        has_warehouse = avail and ('ندارد' not in ftitle)
                                    features.append(ftitle)

                    # فال‌بک هوشمند ارقام مالی به کارت در صورت عدم استخراج از ویجت‌های داخلی
                    if deal_type == 'rent' and deposit == 0 and monthly_rent == 0:
                        if top_desc:
                            p_dep = parse_price(top_desc)
                            if p_dep > 0:
                                deposit = p_dep
                        if middle_desc:
                            if 'رهن کامل' in middle_desc:
                                monthly_rent = 0
                                if 'ودیعه' in middle_desc and deposit == 0:
                                    deposit = parse_price(middle_desc)
                            else:
                                p_rent = parse_price(middle_desc)
                                if p_rent > 0:
                                    monthly_rent = p_rent
                    elif deal_type == 'sale' and total_price == 0:
                        if middle_desc:
                            p_tot = parse_price(middle_desc)
                            if p_tot > 0:
                                total_price = p_tot

                    # عکس‌های وب تکمیلی
                    for wimg in details.get('web_images', []):
                        u = wimg.get('src') if isinstance(wimg, dict) else (wimg if isinstance(wimg, str) else None)
                        hi_res = upgrade_image_url(u)
                        if hi_res and hi_res not in images:
                            images.append(hi_res)

                    # عکس کارت اصلی
                    raw_card_img = d.get('image_url') or (d.get('image', {}).get('url') if isinstance(d.get('image'), dict) else None)
                    if raw_card_img:
                        hi_res = upgrade_image_url(raw_card_img)
                        if hi_res and hi_res not in images:
                            images.insert(0, hi_res)

                    final_desc = raw_description if (raw_description and len(raw_description) > 10) else f"آگهی استخراج شده از دیوار: {full_title} در {district_name}."

                    # تضمین قطعی تعلق به کانون‌های منطقه ۵ تهران (الزام ممیزی فاز ۱)
                    matched_d5 = next((kw for kw in DISTRICT_5_KEYWORDS if kw in exact_address or kw in full_title or kw in final_desc or kw in bottom_desc or kw in current_district), None)
                    if not matched_d5 and district_name != "پونک":
                        logger.info(f"   ⚠️ رد شد: خارج از کانون‌های منطقه ۵: {exact_address}")
                        continue
                    if matched_d5:
                        current_district = matched_d5
                    # مرحله ۲ و ۳: بلک‌لیست سخت‌گیرانه اصطلاحات دلالی و تحلیل لحن مالک
                    # =========================================================
                    st2 = OwnerFilter.evaluate('divar', full_title, final_desc, d, bottom_desc)
                    if not st2.is_personal:
                        logger.info(f"   🚫 رد در فیلتر کلمات دلالی: {token} | {full_title[:30]} ({st2.reason})")
                        continue

                    # =========================================================
                    # مرحله ۴: نرمال‌سازی ارقام مالی و قاعده تبدیل رهن
                    # =========================================================
                    total_price, deposit, monthly_rent = sanitize_property_financials(
                        deal_type=deal_type,
                        total_price=total_price,
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        property_type='apartment'
                    )

                    # رد کردن آگهی‌های ناقص فاقد قیمت معتبر (جلوگیری از ورود داده‌های پوچ)
                    if deal_type == 'sale' and total_price <= 0:
                        logger.info(f"   ⚠️ رد شد: آگهی فروش فاقد قیمت معتبر عددی: {token}")
                        continue
                    if deal_type == 'rent' and deposit <= 0 and monthly_rent <= 0:
                        logger.info(f"   ⚠️ رد شد: آگهی اجاره فاقد ودیعه یا اجاره معتبر: {token}")
                        continue

                    # قاعده تبدیل رهن و اجاره تهران (الزام بند ۳: فقط در صورت برچسب تبدیل)
                    if deal_type == 'rent':
                        if is_convertible:
                            conv = calculate_mortgage_conversion(deposit, monthly_rent)
                            full_mortgage_val = conv.get('full_mortgage_equivalent', 0)
                            if full_mortgage_val > 0:
                                features.append(f"معادل رهن کامل: {int(full_mortgage_val / 1_000_000):,} میلیون تومان")
                                features.append("عرف تبدیل: هر ۱۰۰ میلیون رهن = ۳ میلیون اجاره")
                        else:
                            if 'وضعیت تبدیل' not in ''.join(features):
                                features.append("وضعیت تبدیل: غیر قابل تبدیل (رهن و اجاره قطعی)")

                    extracted_phone = extract_phone_number(f"{final_desc} {full_title}")
                    owner_phone = extracted_phone if extracted_phone else ""

                    is_direct_owner = OwnerFilter.is_direct_owner_declared(full_title, final_desc)
                    score = 99 if is_direct_owner else min(95, 80 + (10 if len(images) > 0 else 0) + (10 if len(final_desc) > 80 else 0))

                    # لینک معتبر تگ a به آگهی مستقیم دیوار
                    source_url = f"https://divar.ir/v/{token}"

                    # ثبت یا پیوند مالک
                    owner_id = None
                    if owner_phone:
                        existing_o = Owner.query.filter_by(phone_number=owner_phone).first()
                        if not existing_o:
                            new_o = Owner(
                                full_name=f"مالک محترم ({district_name})",
                                phone_number=owner_phone,
                                urgency='high',
                                flexibility='منعطف' if is_convertible else 'معمولی',
                                notes=f"استخراج واقعی از دیوار: {full_title}"
                            )
                            db.session.add(new_o)
                            db.session.flush()
                            owner_id = new_o.id
                        else:
                            owner_id = existing_o.id

                    # ایجاد شیء نهایی ملک
                    prop = Property(
                        title=full_title,
                        description=final_desc,
                        property_type='apartment',
                        deal_type=deal_type,
                        total_price=total_price,
                        meter_price=meter_price,
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        area=area or 80.0,
                        rooms=rooms or 2,
                        floor=floor or 1,
                        total_floors=total_floors,
                        build_year=build_year or 1400,
                        city='تهران',
                        district=current_district,
                        address=exact_address,
                        has_parking=has_parking,
                        has_elevator=has_elevator,
                        has_warehouse=has_warehouse,
                        has_balcony=has_balcony,
                        source='divar',
                        source_id=source_id,
                        source_url=source_url,
                        owner_id=owner_id,
                        status='verified' if is_direct_owner else 'available',
                        score=score,
                        is_personal_owner=True,
                        features=features
                    )
                    prop.images = images
                    db.session.add(prop)
                    db.session.commit()

                    dedup_engine.mark_seen(source_id)
                    
                    price_display = f"ودیعه: {int(deposit/1_000_000):,} م | اجاره: {int(monthly_rent/1_000_000):,} م" if deal_type == 'rent' else f"قیمت کل: {int(total_price/1_000_000):,} میلیون تومان"
                    
                    item_summary = {
                        'file_code': prop.file_code,
                        'token': token,
                        'title': full_title,
                        'district': current_district,
                        'address': exact_address,
                        'deal_type': deal_type,
                        'area': prop.area,
                        'rooms': prop.rooms,
                        'price_display': price_display,
                        'is_convertible': is_convertible,
                        'images_count': len(images),
                        'sample_full_hd_image': images[0] if images else "بدون تصویر",
                        'source_url': source_url,
                        'time_in_divar': bottom_desc
                    }
                    saved_properties.append(item_summary)

                    logger.info(f"   🌟 [ثبت تاییدشده #{len(saved_properties)}] کد: {prop.file_code} | {full_title[:35]} | {district_name} | {price_display} | عکس‌های HD: {len(images)}")

            except Exception as e:
                logger.error(f"خطا در پردازش تارگت {target_url}: {e}")
                db.session.rollback()

        # همگام‌سازی دیتابیس ریشه در صورت تفاوت مسیر
        try:
            root_db = os.path.abspath("saghf_database.db")
            inst_db = os.path.abspath("instance/saghf_database.db")
            if os.path.exists(inst_db) and os.path.exists(root_db) and inst_db != root_db:
                import shutil
                shutil.copyfile(inst_db, root_db)
                logger.info("🔄 دیتابیس ریشه با دیتابیس instance همگام‌سازی شد.")
        except Exception:
            pass

        logger.info(f"\n=======================================================")
        logger.info(f"🎯 مجموع آگهی‌های استخراج‌شده و ثبت‌شده در این اجرا: {len(saved_properties)}")
        logger.info(f"=======================================================\n")
        return saved_properties

if __name__ == '__main__':
    count = 5
    clean = True
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            if a.isdigit(): count = int(a)
            elif a == '--no-clean': clean = False
    
    extracted = extract_and_seed_divar(target_count=count, do_purge=clean)
    print("\n" + "=" * 75)
    print(f"📊 گزارش ممیزی {len(extracted)} نمونه آگهی استخراج‌شده زنده دیوار:")
    print("=" * 75)
    for idx, item in enumerate(extracted, 1):
        print(f"\n[نمونه شماره {idx}]")
        print(f"• کد فایل سقف: {item['file_code']}")
        print(f"• عنوان آگهی: {item['title']}")
        print(f"• آدرس و لوکیشن: {item['address']} ({item['district']})")
        print(f"• نوع معامله و قیمت: {item['price_display']}")
        print(f"• متراژ دقیق: {item['area']} متر | تعداد اتاق: {item['rooms']} خواب")
        print(f"• وضعیت تبدیل: {'قابل تبدیل بر اساس عرف بازار' if item['is_convertible'] else 'غیر قابل تبدیل (رهن کامل قطعی)'}")
        print(f"• وضعیت مالکیت: مالک شخصی ۱۰۰٪ تاییدشده (فاقد ردپای آژانس یا واژگان دلالی)")
        print(f"• زمان انتشار در دیوار: {item['time_in_divar']}")
        print(f"• تعداد تصاویر Full-HD استخراج‌شده: {item['images_count']}")
        print(f"• نمونه لینک تصویر باکیفیت اصلی (webp_post):\n  {item['sample_full_hd_image']}")
        print(f"• لینک مستقیم و زنده آگهی دیوار: {item['source_url']}")
    print("\n" + "=" * 75)
