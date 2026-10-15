import sys
import os
import time
import re
import json

sys.path.insert(0, os.path.abspath('.'))
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from app import create_app
from database.db import db
from database.models import Property, PropertyListing, Owner, MatchRecord, Visit, Interaction
from crawler.network.impersonator import TLSImpersonatorClient
from crawler.owner_filter import OwnerFilter, is_stale_ad, extract_phone_number
from crawler.dedup import dedup_engine
from crawler.schemas import parse_price, persian_to_english_numbers, sanitize_property_financials
from data.tehran_districts import is_in_region_2_or_5

PROFILES = ["chrome120", "chrome119", "safari15_5", "chrome110"]

def get_client(index: int):
    p = PROFILES[index % len(PROFILES)]
    return TLSImpersonatorClient(impersonate=p)

def run_real_divar_crawl(target_count=35):
    print("=" * 60)
    print("🚀 SAGHF REAL DIVAR CRAWLER - BATCH EXTRACTION")
    print(f"Target: At least {target_count} authentic personal owner ads from Divar")
    print("=" * 60)

    app = create_app()
    with app.app_context():
        # 1. Purge any mock/test properties
        mock_props = Property.query.filter(
            (Property.source_url.like('%127.0.0.1%')) | 
            (Property.source == 'omnichannel_whatsapp') |
            (Property.source_url == None) |
            (Property.source_url == '')
        ).all()
        if mock_props:
            print(f"🗑️ Deleting {len(mock_props)} mock/test properties...")
            for p in mock_props:
                PropertyListing.query.filter_by(source_url=p.source_url).delete()
                MatchRecord.query.filter_by(property_id=p.id).delete()
                Visit.query.filter_by(property_id=p.id).delete()
                Interaction.query.filter_by(property_id=p.id).delete()
                db.session.delete(p)
            db.session.commit()
            print("✅ Mock data purged.")

        # Re-initialize deduplication engine from existing real properties
        dedup_engine.initialize_from_db(Property)
        existing_real_count = Property.query.filter_by(is_personal_owner=True).count()
        print(f"📊 Currently existing verified real owner properties: {existing_real_count}")

        # Targeted URLs for high volume of owner ads in Tehran
        target_endpoints = [
            # Direct owner keyword queries
            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?q=%D9%85%D8%A7%D9%84%DA%A9"),
            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?q=%D8%B4%D8%AE%D8%B5%DB%8C"),
            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?q=%D8%A8%DB%8C%E2%80%8C%D9%88%D8%A7%D8%B3%D8%B7%D9%87"),
            
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?q=%D9%85%D8%A7%D9%84%DA%A9"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?q=%D8%B4%D8%AE%D8%B5%DB%8C"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?q=%D8%A8%DB%8C%E2%80%8C%D9%88%D8%A7%D8%B3%D8%B7%D9%87"),

            # General categories
            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment"),

            # Region 5 & Region 2 high-volume districts
            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=punak"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=punak"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=saadat-abad"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=saadat-abad"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=bagh-e-feyz"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=bagh-e-feyz"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=shahrak-e-gharb"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=shahrak-e-gharb"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=tarasht"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=tarasht"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=sattarkhan"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=sattarkhan"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=ekbatan"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=ekbatan"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=shahr-e-ziba"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=shahr-e-ziba"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=abazar"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=abazar"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=shahin"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=shahin"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=ferdows"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=ferdows"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=marzdaran"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=marzdaran"),

            ("buy-apartment", "sale", "https://divar.ir/s/tehran/buy-apartment?districts=gisha"),
            ("rent-apartment", "rent", "https://divar.ir/s/tehran/rent-apartment?districts=gisha"),

            ("buy-residential", "sale", "https://divar.ir/s/tehran/buy-residential"),
            ("rent-residential", "rent", "https://divar.ir/s/tehran/rent-residential")
        ]

        total_in_db = Property.query.filter_by(is_personal_owner=True).count()
        saved_count = total_in_db
        total_seen_tokens = set()

        for idx, (cat_slug, deal_type, target_url) in enumerate(target_endpoints):
            if saved_count >= target_count:
                print(f"🎯 Target reached: {saved_count} properties saved.")
                break

            time.sleep(1.2)  # Polite pacing
            client = get_client(idx)
            print(f"\n📡 [{idx+1}/{len(target_endpoints)}] Fetching target: {target_url}...")

            try:
                res = client.get(target_url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'fa,en;q=0.9',
                    'Referer': 'https://divar.ir'
                }, timeout=12)

                if not res or res.status_code != 200:
                    print(f"⚠️ Failed to fetch {target_url} (status: {res.status_code if res else 'None'})")
                    continue

                match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', res.text)
                if not match:
                    print("⚠️ No __PRELOADED_STATE__ found in page.")
                    continue

                state_data = json.loads(match.group(1))
                widgets = state_data.get('nb', {}).get('listWidgets', [])
                print(f"📦 Total raw widgets found: {len(widgets)}")

                for w in widgets:
                    if saved_count >= target_count:
                        break

                    dto = w.get('data', {}).get('dto', {})
                    if dto.get('widget_type') != 'POST_ROW':
                        continue

                    d = dto.get('data', {})
                    token = d.get('token') or d.get('action', {}).get('payload', {}).get('token')
                    title = d.get('title', '')
                    if not token or not title:
                        continue

                    if token in total_seen_tokens:
                        continue
                    total_seen_tokens.add(token)

                    source_id = f"divar_{token}"
                    if dedup_engine.is_duplicate(source_id=source_id, title=title):
                        continue

                    district = d.get('action', {}).get('payload', {}).get('web_info', {}).get('district_persian', '')
                    bottom_desc = d.get('bottom_description_text', '')
                    middle_desc = d.get('middle_description_text', '')
                    if not district:
                        district = bottom_desc.replace('در ', '').strip() or 'تهران'

                    # Check freshness: skip stale ads older than 2-3 days
                    if is_stale_ad(bottom_desc) or is_stale_ad(middle_desc):
                        continue

                    # Filter stage 1: metadata and banner terms
                    st1 = OwnerFilter.evaluate('divar', title, middle_desc, d, bottom_desc)
                    if not st1.is_personal:
                        continue

                    # Stage 2: Fetch full post details from Divar API
                    time.sleep(0.3)  # Respect rate limit
                    api_url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
                    details = {}
                    try:
                        api_res = client.get(api_url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Accept': 'application/json'
                        }, timeout=6)
                        if api_res and api_res.status_code == 200:
                            details = api_res.json()
                    except Exception as ex:
                        pass

                    if not details:
                        continue

                    # Parse detailed sections
                    sections = details.get('sections', [])
                    is_agency = False
                    real_desc = ""
                    images = []
                    features = []
                    area = 0
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

                    for sec in sections:
                        sec_name = str(sec.get('section_name', '')).upper()
                        if any(bs in sec_name for bs in ['BUSINESS_SECTION', 'AGENCY_SECTION', 'SELLER_PROFILE', 'BUSINESS']):
                            is_agency = True
                            break

                        for widget in sec.get('widgets', []):
                            wt = widget.get('widget_type', '')
                            wd = widget.get('data', {})

                            if wt == 'LAZY_SECTION':
                                req_d = wd.get('request_data', {})
                                biz_type = str(req_d.get('post_business_type', '')).lower()
                                if biz_type in ['premium-panel', 'business', 'agency', 'consultant', 'real_estate_agency']:
                                    is_agency = True
                                    break
                            elif any(x in wt.lower() for x in ['agency_info', 'business_section', 'seller_profile', 'consultant']):
                                is_agency = True
                                break

                            # Exclude Divar system widgets from agency checks
                            if wt not in ['SELECTOR_ROW', 'FEEDBACK_ROW', 'REPORT_ROW', 'SHARE_ROW', 'SAFETY_ROW', 'BREADCRUMB_ROW', 'TAG_ROW', 'DESCRIPTION_ROW', 'UNEXPANDABLE_ROW', 'GROUP_INFO_ROW', 'GROUP_FEATURE_ROW', 'IMAGE_CAROUSEL']:
                                w_text = f"{wd.get('title', '')} {wd.get('subtitle', '')} {wd.get('text', '')}"
                                if any(term in w_text for term in OwnerFilter.NON_PERSONAL_ACCOUNT_TERMS):
                                    is_agency = True
                                    break

                            if wt == 'DESCRIPTION_ROW':
                                real_desc = wd.get('text', '')

                            elif wt in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER_ROW', 'IMAGES_ROW', 'IMAGE_SLIDER', 'IMAGE_ROW'] or 'IMAGE' in wt:
                                for item in wd.get('items', []):
                                    if isinstance(item, dict):
                                        u = item.get('image', {}).get('url') or item.get('url') or item.get('src')
                                    elif isinstance(item, str) and item.startswith(('http://', 'https://')):
                                        u = item
                                    else:
                                        u = None
                                    if u and u not in images and 'divarcdn.com' in u:
                                        images.append(u)

                            elif wt in ['UNEXPANDABLE_ROW', 'GROUP_INFO_ROW']:
                                for item in wd.get('items', []):
                                    it_title = item.get('title', '')
                                    it_val = item.get('value', '')
                                    val_en = persian_to_english_numbers(it_val)
                                    if 'متراژ' in it_title:
                                        ma = re.search(r'\d+', val_en)
                                        if ma: area = int(ma.group(0))
                                    elif 'ساخت' in it_title:
                                        my = re.search(r'\d+', val_en)
                                        if my: build_year = int(my.group(0))
                                    elif 'اتاق' in it_title:
                                        mr = re.search(r'\d+', val_en)
                                        if mr: rooms = int(mr.group(0))
                                        elif 'بدون' in it_val: rooms = 0

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

                            elif wt == 'TITLE_ROW':
                                t_title = wd.get('title', '')
                                if 'طبقه' in t_title:
                                    mt = re.search(r'طبقه\s*(\d+)', persian_to_english_numbers(t_title))
                                    if mt: floor = int(mt.group(1))

                    if is_agency:
                        continue

                    final_desc = real_desc if (real_desc and len(real_desc) > 10) else f"آگهی استخراج شده از دیوار: {title} در {district}."

                    # Stage 2 filter on description
                    st2 = OwnerFilter.evaluate('divar', title, final_desc, d, bottom_desc)
                    if not st2.is_personal:
                        continue

                    # Financials
                    if deal_type == 'sale':
                        total_price = parse_price(middle_desc) or parse_price(bottom_desc) or parse_price(final_desc) or 0
                        if area > 0 and total_price > 0:
                            meter_price = int(total_price / area)
                    else:
                        deposit = parse_price(middle_desc) or 0
                        monthly_rent = parse_price(bottom_desc) or 0

                    total_price, deposit, monthly_rent = sanitize_property_financials(
                        deal_type=deal_type,
                        total_price=total_price,
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        property_type='apartment'
                    )

                    # Photos
                    for wimg in details.get('web_images', []):
                        u = wimg.get('src') if isinstance(wimg, dict) else (wimg if isinstance(wimg, str) else None)
                        if u and u not in images and 'divarcdn.com' in u:
                            images.append(u)

                    raw_card_img = d.get('image_url') or (d.get('image', {}).get('url') if isinstance(d.get('image'), dict) else None)
                    if raw_card_img and raw_card_img not in images and 'divarcdn.com' in raw_card_img:
                        images.insert(0, raw_card_img)

                    # Extract phone if present
                    extracted_phone = extract_phone_number(f"{final_desc} {title}")
                    owner_phone = extracted_phone if extracted_phone else ""

                    # Priority score: Direct owner declarations get 99
                    is_direct_owner = OwnerFilter.is_direct_owner_declared(title, final_desc)
                    score = 99 if is_direct_owner else min(95, 75 + (10 if len(images) > 0 else 0) + (10 if len(final_desc) > 100 else 0))

                    # Direct authentic link to Divar
                    source_url = f"https://divar.ir/v/{token}"

                    # Owner record
                    owner_id = None
                    if owner_phone:
                        existing_o = Owner.query.filter_by(phone_number=owner_phone).first()
                        if not existing_o:
                            new_o = Owner(
                                full_name=f"مالک شخصی ({district})",
                                phone_number=owner_phone,
                                urgency='high',
                                flexibility='معمولی',
                                notes=f"استخراج واقعی از آگهی دیوار: {title}"
                            )
                            db.session.add(new_o)
                            db.session.flush()
                            owner_id = new_o.id
                        else:
                            owner_id = existing_o.id

                    # Create Property model
                    prop = Property(
                        title=title,
                        description=final_desc,
                        property_type='apartment',
                        deal_type=deal_type,
                        total_price=total_price,
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        area=area or 85,
                        rooms=rooms or 2,
                        floor=floor or 1,
                        total_floors=total_floors,
                        build_year=build_year or 1400,
                        city='تهران',
                        district=district,
                        address=f"تهران، {district}",
                        has_parking=has_parking,
                        has_elevator=has_elevator,
                        has_warehouse=has_warehouse,
                        has_balcony=has_balcony,
                        source='divar',
                        source_id=source_id,
                        source_url=source_url,
                        owner_id=owner_id,
                        status='verified' if is_direct_owner else 'active',
                        score=score,
                        is_personal_owner=True,
                        features=features
                    )
                    prop.images = images
                    db.session.add(prop)
                    db.session.flush()

                    # Create PropertyListing entry
                    ad_code = token[-8:]
                    listing = PropertyListing(
                        ad_code=ad_code,
                        source='divar',
                        source_url=source_url,
                        title=title,
                        description=final_desc,
                        city='تهران',
                        region='5' if is_in_region_2_or_5(district, '') else '2',
                        district=district,
                        deal_type=deal_type,
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        total_price=total_price,
                        area=area or 85,
                        rooms=rooms or 2,
                        is_personal_owner=True
                    )
                    listing.images = images
                    db.session.add(listing)
                    db.session.commit()

                    dedup_engine.mark_seen(source_id)
                    saved_count += 1
                    print(f"  ✅ [{saved_count}/{target_count}] SAVED: [{token}] {title[:32]} ({district}) | {deal_type} | Score: {score} | URL: {source_url}")

            except Exception as e:
                print(f"⚠️ Error processing target {target_url}: {e}")
                db.session.rollback()

        print("\n" + "=" * 60)
        print(f"🎉 CRAWL FINISHED! Total real personal ads saved: {saved_count}")
        print("=" * 60)

if __name__ == '__main__':
    run_real_divar_crawl(35)
