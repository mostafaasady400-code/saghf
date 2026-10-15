import requests
import json
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

print("==================================================")
print("🔍 تست بلادرنگ و زنده سیستم سقف (Saghf System Test)")
print("==================================================")

# 1. تست صفحه اصلی
try:
    r1 = requests.get('http://127.0.0.1:5000/', timeout=5)
    print(f"1. صفحه اصلی: وضعیت {r1.status_code} (OK)")
except Exception as e:
    print(f"1. خطا در صفحه اصلی: {e}")

# 2. تست وضعیت پایش زنده و مداوم دیوار منطقه ۵
try:
    r2 = requests.get('http://127.0.0.1:5000/crawler/realtime-monitor/status', timeout=5)
    d2 = r2.json()
    print(f"2. وضعیت پایش زنده دیوار: {r2.status_code}")
    print(f"   پیام وضعیت: {d2.get('status_message')}")
    print(f"   منطقه هدف: {d2.get('target_district')} | بازه: {d2.get('interval_seconds')} ثانیه")
except Exception as e:
    print(f"2. خطا در مانیتور دیوار: {e}")

# 3. تست دستیار صوتی با دستور «۸۰ متری پونک»
try:
    r3 = requests.post(
        'http://127.0.0.1:5000/api/ai-orb/parse-command',
        json={'command': '۸۰ متری پونک'},
        timeout=8
    )
    d3 = r3.json()
    print(f"\n3. تحلیل فرمان صوتی «۸۰ متری پونک»: وضعیت {r3.status_code}")
    print(f"   پاسخ هوش مصنوعی (Voice Reply): {d3.get('voice_reply')}")
    print(f"   متن گفتار (Speech Text): {d3.get('speech_text')}")
    items = d3.get('items', [])
    print(f"   تعداد فایل‌های منطبق استخراج‌شده: {len(items)}")
    for i, it in enumerate(items, 1):
        print(f"   [{i}] {it.get('title')} | محله: {it.get('district')} | متراژ: {it.get('area')} متر")
        print(f"       قیمت/ودیعه: {it.get('price_str')}")
        print(f"       لینک مستقیم دیوار: {it.get('source_url')}")
except Exception as e:
    print(f"3. خطا در فرمان صوتی: {e}")

print("==================================================")
