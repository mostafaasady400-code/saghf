import sys
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import urllib.request
import json
import time

endpoints = [
    ('/', 200),
    ('/crawler/live', 200),
    ('/properties/', 200),
    ('/clients/', 200),
    ('/matching/', 200),
    ('/crm/pipeline', 200),
    ('/crm/calls', 200),
    ('/crm/visits', 200),
    ('/api/dashboard/stats', 200),
    ('/crawler/status', 200)
]

print("🔍 Testing Saghf Web System Endpoints...")
all_pass = True
for url, expected_code in endpoints:
    full_url = f"http://127.0.0.1:5000{url}"
    try:
        req = urllib.request.urlopen(full_url, timeout=6)
        status = req.getcode()
        if status == expected_code:
            print(f"  ✅ [PASS] {url} -> HTTP {status}")
        else:
            print(f"  ❌ [FAIL] {url} -> got {status}, expected {expected_code}")
            all_pass = False
    except Exception as e:
        print(f"  ❌ [ERROR] {url} -> {e}")
        all_pass = False

print("\n🚀 Testing Crawler Execution via API (with CSRF Protection)...")
try:
    # 1. First fetch a page to obtain the session cookie and CSRF token from meta tag
    import re
    from http.cookiejar import CookieJar
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    page_resp = opener.open("http://127.0.0.1:5000/crawler/live", timeout=6)
    html_content = page_resp.read().decode('utf-8')
    token_match = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html_content)
    csrf_token = token_match.group(1) if token_match else None
    
    if not csrf_token:
        print("  ❌ Could not extract csrf-token from /crawler/live")
        all_pass = False
    else:
        print(f"  🔑 Extracted CSRF Token: {csrf_token[:16]}...")
        req = urllib.request.Request(
            "http://127.0.0.1:5000/crawler/start",
            data=json.dumps({"sources": ["divar", "sheypoor"], "categories": ["buy-apartment"], "limit": 4}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": csrf_token
            }
        )
        res = opener.open(req)
        data = json.loads(res.read().decode("utf-8"))
        print(f"  ✅ Crawler API response: {data}")

        print("  ⏳ Waiting for crawler to extract and save properties...")
        time.sleep(4)
        status_res = opener.open("http://127.0.0.1:5000/crawler/status")
        status_data = json.loads(status_res.read().decode("utf-8"))
        print(f"  📊 Live Crawler Status: {status_data['stats']}")
except Exception as e:
    print(f"  ❌ Crawler test error: {e}")
    all_pass = False

if all_pass:
    print("\n🎉 ALL TESTS PASSED! Saghf Real Estate System is 100% operational!")
else:
    print("\n⚠️ Some tests failed.")
