import json
import re
import sys
from crawler.network.impersonator import TLSImpersonatorClient
from crawler.owner_filter import extract_phone_number

sys.stdout.reconfigure(encoding='utf-8')

client = TLSImpersonatorClient(impersonate='chrome120')
url = 'https://divar.ir/s/tehran/buy-apartment'
resp = client.get(url)
match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', resp.text)
if match:
    state = json.loads(match.group(1))
    widgets = state.get('nb', {}).get('listWidgets', [])
    print(f'Found {len(widgets)} list widgets in Divar')
    found_phones = 0
    checked = 0
    for w in widgets[:15]:
        d = w.get('data', {}).get('dto', {}).get('data', {})
        t = d.get('token')
        if not t:
            continue
        checked += 1
        detail_url = f'https://api.divar.ir/v8/posts-v2/web/{t}'
        det_resp = client.get(detail_url)
        if det_resp.status_code == 200:
            det = det_resp.json()
            desc = ''
            for sec in det.get('sections', []):
                for wid in sec.get('widgets', []):
                    if wid.get('widget_type') == 'DESCRIPTION_ROW':
                        desc = wid.get('data', {}).get('text', '')
            ph = extract_phone_number(f"{d.get('title', '')} {desc}")
            
            # Count real images
            img_count = len(det.get('web_images', []))
            for s in det.get('sections', []):
                for wid in s.get('widgets', []):
                    if wid.get('widget_type') in ['IMAGE_CAROUSEL', 'IMAGE_SLIDER']:
                        img_count = max(img_count, len(wid.get('data', {}).get('items', [])))
            
            print(f'Post {t}: Phone={ph} | Imgs={img_count} | Title={d.get("title")[:30]}')
            if ph:
                found_phones += 1
    print(f'Checked {checked}, found {found_phones} phones directly in text')
