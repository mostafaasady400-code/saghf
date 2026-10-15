"""
رابط خط فرمان (CLI) استخراج چندترده دیوار با سلنیوم و بیوتیفول‌سوپ
سازگار با اینترفیس ErfanNahidi/Divar_Property_Scraper با قدرت و فیلترینگ مالک سقف
"""

import sys
import argparse
from typing import Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from .scraper import MultiThreadedDivarScraper
from .browser import find_optimal_thread_count


def interactive_main():
    """اجرای تعاملی خط فرمان شبیه به main.py ریپازیتوری ErfanNahidi"""
    print("=" * 65)
    print("🏘️ سامانه استخراج پیشرفته و چندترده املاک دیوار (سقف - نسخه سلنیوم)")
    print("=" * 65)

    # دریافت تعداد فایل‌های درخواستی
    try:
        count_input = input("تعداد آگهی‌های مالک مستقیم مورد نیاز را وارد کنید [پیش‌فرض 25]: ").strip()
        target_count = int(count_input) if count_input else 25
        if target_count <= 0:
            target_count = 25
    except ValueError:
        print("مقدار نامعتبر، پیش‌فرض ۲۵ فایل در نظر گرفته شد.")
        target_count = 25

    # دریافت تعداد تردها
    thread_input = input("تعداد تردهای موازی (عدد وارد کنید یا 'auto' برای تشخیص هوشمند) [auto]: ").strip()
    if not thread_input or thread_input.lower() == 'auto':
        threads = find_optimal_thread_count()
        print(f"⚡ تشخیص خودکار: {threads} ترد موازی بر مبنای CPU و RAM سیستم انتخاب شد.")
    else:
        try:
            threads = int(thread_input)
            if threads <= 0:
                threads = find_optimal_thread_count()
        except ValueError:
            threads = find_optimal_thread_count()

    # دریافت دسته‌بندی
    print("\nدسته‌بندی‌های موجود:")
    print("1. فروش آپارتمان (buy-apartment)")
    print("2. اجاره آپارتمان (rent-apartment)")
    print("3. فروش مسکونی و ویلایی (buy-residential)")
    print("4. اجاره مسکونی و ویلایی (rent-residential)")
    cat_choice = input("انتخاب دسته‌بندی [1]: ").strip()
    cat_map = {
        "1": "buy-apartment",
        "2": "rent-apartment",
        "3": "buy-residential",
        "4": "rent-residential"
    }
    category = cat_map.get(cat_choice, "buy-apartment")

    district = input("اسلاگ محله در دیوار (مثلاً punak یا خالی برای کل شهر) []: ").strip() or None

    scraper = MultiThreadedDivarScraper(
        city="tehran",
        thread_count=threads,
        csv_output_path="divar_properties.csv"
    )

    results = scraper.run_multi_threaded_extraction(
        category_key=category,
        district_slug=district,
        target_count=target_count
    )

    print(f"\n🎉 استخراج با موفقیت به پایان رسید. {len(results)} فایل شخصی استخراج و ذخیره شد.")


def main():
    parser = argparse.ArgumentParser(description="Divar Multi-Threaded Selenium Scraper")
    parser.add_argument("--count", type=int, default=None, help="Target count of properties")
    parser.add_argument("--threads", type=str, default=None, help="Number of parallel threads or 'auto'")
    parser.add_argument("--category", type=str, default="buy-apartment", help="Divar category key")
    parser.add_argument("--district", type=str, default=None, help="District slug (e.g. punak)")
    parser.add_argument("--csv", type=str, default="divar_properties.csv", help="CSV output path")

    args = parser.parse_args()

    if args.count is None and args.threads is None:
        interactive_main()
    else:
        threads = find_optimal_thread_count() if (args.threads == 'auto' or not args.threads) else int(args.threads)
        scraper = MultiThreadedDivarScraper(
            city="tehran",
            thread_count=threads,
            csv_output_path=args.csv
        )
        scraper.run_multi_threaded_extraction(
            category_key=args.category,
            district_slug=args.district,
            target_count=args.count or 25
        )


if __name__ == "__main__":
    main()
