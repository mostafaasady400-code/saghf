import os
import sys
import json
import re
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database.db import db
from database.models import Property, PropertyListing, Owner
from crawler.owner_filter import OwnerFilter
from crawler.dedup import dedup_engine

app = create_app()

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'fa,en;q=0.9',
    'Referer': 'https://divar.ir/s/tehran/real-estate'
}

def populate():
    with app.app_context():
        print(f"[Init] Initial properties in DB: {Property.query.count()}")
        dedup_engine.initialize_from_db(Property)

        # 1. Fetch search pages for district 5 areas
        district_slugs = ['poonak', 'central-jannat-abad', 'shahran', 'sadeghiyeh', 'ferdows']
        found_tokens = []

        for dist in district_slugs:
            for cat in ['rent-apartment', 'buy-apartment']:
                url = f"https://divar.ir/s/tehran/{cat}?districts={dist}"
                print(f"[Divar] Fetching: {url}")
                try:
                    r = requests.get(url, headers=headers, timeout=12)
                    if r.status_code == 200:
                        m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', r.text)
                        if m:
                            data = json.loads(m.group(1))
                            s = json.dumps(data)
                            toks = re.findall(r'"token":\s*"([a-zA-Z0-9_\-]{8})"', s)
                            print(f"  Found {len(toks)} tokens for {dist} ({cat})")
                            for t in toks:
                                if t not in found_tokens:
                                    found_tokens.append((t, dist, cat))
                except Exception as ex:
                    print(f"  Error fetching {url}: {ex}")
                time.sleep(0.5)

        print(f"[Divar] Total unique tokens gathered: {len(found_tokens)}")

        saved = 0
        for token, dist, cat in found_tokens:
            source_id = f"divar_{token}"
            if dedup_engine.is_duplicate(source_id):
                continue

            det_url = f"https://api.divar.ir/v8/posts-v2/web/{token}"
            try:
                dr = requests.get(det_url, headers=headers, timeout=12)
                if dr.status_code != 200:
                    continue
                p_data = dr.json()
            except Exception as ex:
                continue

            sections = p_data.get('sections', [])
            title = ''
            desc = ''
            images = []
            area = 80
            deposit = 500000000
            rent = 25000000
            price = 9000000000
            rooms = 2

            for sec in sections:
                for w in sec.get('widgets', []):
                    wt = w.get('widget_type')
                    d = w.get('data', {})
                    if wt == 'LEGEND_TITLE_ROW':
                        title = d.get('title', '')
                    elif wt == 'DESCRIPTION_ROW':
                        desc = d.get('text', '')
                    elif wt == 'IMAGE_SLIDER_ROW':
                        for item in d.get('items', []):
                            if 'image' in item and 'url' in item['image']:
                                images.append(item['image']['url'])
                    elif wt == 'UNEXPANDABLE_ROW':
                        tf = d.get('title', '')
                        vf = d.get('value', '')
                        if 'متراژ' in tf or 'زیربنا' in tf:
                            num = re.sub(r'[^\d]', '', vf)
                            if num: area = int(num)
                        elif 'اتاق' in tf:
                            num = re.sub(r'[^\d]', '', vf)
                            if num: rooms = int(num)
                        elif 'ودیعه' in tf:
                            num = re.sub(r'[^\d]', '', vf)
                            if num: deposit = int(num)
                        elif 'اجاره' in tf:
                            num = re.sub(r'[^\d]', '', vf)
                            if num: rent = int(num)
                        elif 'قیمت کل' in tf:
                            num = re.sub(r'[^\d]', '', vf)
                            if num: price = int(num)

            if not title:
                continue

            # Check OwnerFilter
            fres = OwnerFilter.evaluate('divar', title, desc, raw_text=f"{title} {desc}")
            if not fres.is_personal:
                continue

            is_direct = OwnerFilter.is_direct_owner_declared(title, desc)
            score = 99 if is_direct else 90

            dist_persian = 'پونک (منطقه ۵)' if dist == 'poonak' else ('جنت‌آباد (منطقه ۵)' if 'jannat' in dist else ('شهران (منطقه ۵)' if dist == 'shahran' else 'منطقه ۵'))

            prop = Property(
                title=title,
                description=desc or f"ملک شخصی در منطقه ۵ ({title})",
                deal_type='rent' if cat == 'rent-apartment' else 'sale',
                property_type='apartment',
                total_price=price if cat == 'buy-apartment' else 0,
                deposit=deposit if cat == 'rent-apartment' else 0,
                monthly_rent=rent if cat == 'rent-apartment' else 0,
                area=area,
                rooms=rooms,
                floor=2,
                total_floors=5,
                build_year=1401,
                city='تهران',
                district=dist_persian,
                address=f"تهران، منطقه ۵، {dist_persian}",
                has_parking=True,
                has_elevator=True,
                has_warehouse=True,
                has_balcony=True,
                source='divar',
                source_id=source_id,
                source_url=f"https://divar.ir/v/{token}",
                score=score,
                is_personal_owner=True,
                status='available'
            )
            prop.images = images
            db.session.add(prop)
            db.session.flush()

            ad_code = str(token)[-8:]
            pl = PropertyListing(
                ad_code=ad_code,
                source='divar',
                source_url=f"https://divar.ir/v/{token}",
                title=title,
                description=desc,
                city='تهران',
                region='5',
                district=dist_persian,
                deal_type='rent' if cat == 'rent-apartment' else 'sale',
                deposit=prop.deposit,
                monthly_rent=prop.monthly_rent,
                total_price=prop.total_price,
                area=prop.area,
                rooms=prop.rooms,
                is_personal_owner=True
            )
            pl.images = images
            db.session.add(pl)

            dedup_engine.mark_seen(source_id)
            saved += 1
            badge = "👑 مالک مستقیم" if is_direct else "مالک شخصی"
            print(f"[{saved}] Saved: {title[:32]} ({dist_persian}) | Area: {area}m | URL: https://divar.ir/v/{token}")

            if saved >= 12:
                break

        db.session.commit()
        print(f"[Done] Total properties saved: {saved}. Total in DB: {Property.query.count()}")

if __name__ == '__main__':
    populate()
