import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
import json
from crawler.hybrid_divar import HybridDivarCrawler

c = HybridDivarCrawler()
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://divar.ir/s/tehran/real-estate'
}
r = c.client.get('https://divar.ir/s/tehran/rent-apartment', headers=headers, timeout=15)
print('status:', r.status_code, 'len:', len(r.text))

m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', r.text)
if m:
    data = json.loads(m.group(1))
    
    # search where token is inside data
    def find_paths_to_token(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == 'token' and isinstance(v, str) and len(v) == 8:
                    print(f"Token found at path: {path}.{k} = {v}")
                    return True
                if find_paths_to_token(v, f"{path}.{k}"):
                    return True
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:5]):
                if find_paths_to_token(item, f"{path}[{i}]"):
                    return True
        return False

    find_paths_to_token(data, "data")
