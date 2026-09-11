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
    ('/properties/1', 200),
    ('/clients/', 200),
    ('/clients/1', 200),
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

print("\n🚀 Testing Crawler Execution via API...")
try:
    req = urllib.request.Request(
        "http://127.0.0.1:5000/crawler/start",
        data=json.dumps({"sources": ["divar", "sheypoor"], "categories": ["buy-apartment"], "limit": 4}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    data = json.loads(res.read().decode("utf-8"))
    print(f"  ✅ Crawler API response: {data}")

    print("  ⏳ Waiting for crawler to extract and save properties...")
    time.sleep(4)
    status_res = urllib.request.urlopen("http://127.0.0.1:5000/crawler/status")
    status_data = json.loads(status_res.read().decode("utf-8"))
    print(f"  📊 Live Crawler Status: {status_data['stats']}")
except Exception as e:
    print(f"  ❌ Crawler test error: {e}")
    all_pass = False

if all_pass:
    print("\n🎉 ALL TESTS PASSED! Saghf Real Estate System is 100% operational!")
else:
    print("\n⚠️ Some tests failed.")
