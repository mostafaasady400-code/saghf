"""
Saghf Real Estate Intelligence Platform - Infrastructure & Service Health CLI Monitor
Zero-Mock real-time telemetry inspection tool for developers, DevOps, and project evaluators.
"""

import sys
import os

# Ensure project root is in python path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import create_app
from services.system_health import SystemHealthService


def render_progress_bar(percent: float, width: int = 24) -> str:
    filled = int(round(width * percent / 100))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent:.1f}%"


def run_health_check():
    print("=" * 74)
    print(" ⚡ سامانه املاک سقف - مانیتورینگ سلامت زیرساخت و منابع پردازشی")
    print("    Saghf Infrastructure & Service Health Diagnostic Tool (Zero-Mock)")
    print("=" * 74)

    app = create_app()
    with app.app_context():
        report = SystemHealthService.get_full_report()

    os_info = report['compute']['os']
    cpu = report['compute']['cpu']
    ram = report['compute']['ram']
    disk = report['compute']['disk']
    proc = report['compute']['process']
    db = report['database']
    bots = report['bots']
    crawler = report['crawler']

    status_icon = "🟢" if report['overall_status'] == 'HEALTHY' else ("🟡" if report['overall_status'] == 'DEGRADED' else "🔴")

    print(f"\n 📅 زمان سنجش: {report['timestamp']}")
    print(f" 🖥️  میزبان (Host): {os_info['hostname']} | سیستم‌عامل: {os_info['system']} {os_info['release']} ({os_info['architecture']})")
    print(f" 🐍 مفسر پایتون: {os_info['python_version']} | آپ‌تایم فرآیند: {os_info['uptime_seconds']:.1f} ثانیه")
    print("-" * 74)

    print(f" 🏆 شاخص سلامت کلی سامانه: {report['health_score']} / ۱۰۰  | وضعیت: {status_icon} {report['overall_status']}")
    print("-" * 74)

    # 1. Compute & Resources
    print("\n[۱] منابع محاسباتی و سخت‌افزاری (Host Compute & Memory):")
    print(f"  • پردازنده (CPU):      {render_progress_bar(cpu['percent'])}  ({cpu['logical_cores']} هسته منطقی)")
    print(f"  • حافظه اصلی (RAM):   {render_progress_bar(ram['percent'])}  (مصرف: {ram['used_gb']} GB از {ram['total_gb']} GB | آزاد: {ram['available_gb']} GB)")
    print(f"  • فضای دیسک (Disk):   {render_progress_bar(disk['percent'])}  (مصرف: {disk['used_gb']} GB از {disk['total_gb']} GB | آزاد: {disk['free_gb']} GB)")
    print(f"  • فرآیند فعال وب:     PID={proc['pid']} | حافظه فیزیکی (RSS)={proc['rss_mb']} MB | نخ‌ها={proc['threads']}")

    # 2. Database
    print("\n[۲] موتور پایگاه داده (SQLite 3 & SQLAlchemy):")
    db_icon = "🟢" if db['status'] == 'healthy' else "🔴"
    print(f"  • وضعیت پایگاه داده:  {db_icon} {db['status'].upper()} (تاخیر کوئری: {db['query_latency_ms']} ms)")
    print(f"  • فایل پایگاه داده:   {db['file_path']} ({db['file_size_kb']} KB)")
    print(f"  • یکپارچگی ساختار:   PRAGMA quick_check -> {db['integrity_check'].upper()} ✓")
    print(f"  • رکوردهای زنده:      {db['counts']['properties']} ملک | {db['counts']['clients']} مشتری CRM | {db['counts']['visits']} نوبت بازدید | {db['counts']['owners']} مالک")

    # 3. Dual Bots
    print("\n[۳] پیام‌رسان‌ها و درگاه‌های ارتباطی (Dual-Bot Gateway):")
    runner_icon = "🟢 فعال" if bots['process_runner']['active'] else "🔴 متوقف"
    tg_icon = "🟢 آنلاین" if bots['telegram']['healthy'] else "🔴 آفلاین"
    bale_icon = "🟢 آنلاین" if bots['bale']['healthy'] else "🔴 آفلاین"
    print(f"  • پردازه رانر بات‌ها:  {runner_icon} (PID: {bots['process_runner']['pid'] or 'None'} | RSS: {bots['process_runner']['rss_mb']} MB)")
    print(f"  • ربات تلگرام:        {tg_icon} (@{bots['telegram']['username']} | تاخیر: {bots['telegram']['latency_ms']} ms)")
    print(f"  • ربات بله (Bale):    {bale_icon} (@{bots['bale']['username']} | تاخیر: {bots['bale']['latency_ms']} ms)")

    # 4. Crawler & Edge
    print("\n[۴] خط استخراج هوشمند و لایه‌های کراولر (Scraping Pipeline):")
    t1_icon = "🟢 آماده" if crawler['tier1_tls_impersonator']['available'] else "🔴 ناموجود"
    divar_icon = "🟢 در دسترس" if crawler['edge_targets']['divar']['reachable'] else "🔴 قطع"
    sheypoor_icon = "🟢 در دسترس" if crawler['edge_targets']['sheypoor']['reachable'] else "🔴 قطع"
    print(f"  • لایه ۱ TLS Spoofing: {t1_icon} ({crawler['tier1_tls_impersonator']['library']} - {crawler['tier1_tls_impersonator']['target_tls']})")
    print(f"  • اتصال سرورهای دیوار: {divar_icon} (پینگ: {crawler['edge_targets']['divar']['latency_ms']} ms)")
    print(f"  • اتصال شیپور:         {sheypoor_icon} (پینگ: {crawler['edge_targets']['sheypoor']['latency_ms']} ms)")
    print(f"  • موتور کش ددوپلیکیتور:  {crawler['deduplication_engine']['cached_signatures']} شناسه در RAM ({crawler['deduplication_engine']['lookup_complexity']})")

    # Issues & Summary
    print("\n" + "=" * 74)
    if report['issues']:
        print(" ⚠️  هشدارهای نیازمند بررسی:")
        for iss in report['issues']:
            print(f"    - {iss}")
    else:
        print(" ✅ تمامی سرویس‌های سقف در بالاترین سطح آمادگی و تاب‌آوری عملیاتی قرار دارند.")
    print("=" * 74 + "\n")


if __name__ == '__main__':
    run_health_check()
