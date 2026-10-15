import requests
import json
import sys

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'application/json'
}

url = 'https://api.divar.ir/v8/web-search/1/rent-apartment'
try:
    r = requests.post(url, headers=headers, json={}, timeout=12)
    print('Search status:', r.status_code)
    if r.status_code == 200:
        data = r.json()
        wlist = data.get('widget_list', [])
        print('Widget count from API:', len(wlist))
        items = []
        for w in wlist:
            dto = w.get('data', {})
            t = dto.get('token')
            tit = dto.get('title') or ''
            bot = dto.get('bottom_description_text') or ''
            mid = dto.get('middle_description_text') or ''
            if t:
                items.append({'token': t, 'title': tit, 'bottom': bot, 'middle': mid})
        with open('divar_fresh_tokens.json', 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"Saved {len(items)} tokens to divar_fresh_tokens.json")
except Exception as e:
    print('Error:', e)
