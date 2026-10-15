import sys
sys.stdout.reconfigure(encoding='utf-8')
from crawler.owner_filter import OwnerFilter

test_cases = [
    # --- آزمون‌های مرحله اول: رد بر اساس نوع آگهی‌دهنده (پنل، آژانس، بیزینس) ---
    {
        'platform': 'divar',
        'title': '۷۰متر ۲خواب فول امکانات',
        'desc': 'یک واحد شیک و پرنور با دسترسی عالی',
        'widget_data': {'bottom_description_text': 'املاک رشید در آسمان'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_account_type',
        'description': 'مرحله ۱: دیوار - پنل آژانس املاک در مشخصات حساب'
    },
    {
        'platform': 'divar',
        'title': 'واحد ۱۰۰ متری نوساز',
        'desc': 'نورگیر عالی و پارکینگ سندی',
        'widget_data': {
            'bottom_description_text': 'دقایقی پیش در سعادت آباد',
            'action_log': {'server_side_info': {'info': {'is_business': True, 'agency_id': 1234}}}
        },
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_account_type',
        'description': 'مرحله ۱: دیوار - حساب تجاری (is_business=True و دارای agency_id)'
    },
    {
        'platform': 'sheypoor',
        'title': 'آپارتمان کلید نخورده نور 116 متر',
        'desc': 'فروش فوری',
        'widget_data': {},
        'raw_text': '۶ آپارتمان ۱۱۶ متر Ad تابلو شده ۱۵,۰۸۰,۰۰۰,۰۰۰ املاک نور',
        'expected_personal': False,
        'expected_status': 'rejected_account_type',
        'description': 'مرحله ۱: شیپور - حساب اسپانسری و آژانس (Ad تابلو شده و املاک)'
    },

    # --- آزمون‌های مرحله دوم: حساب شخصی است، ولی در عنوان یا متن کلمات فیلتر دارد ---
    {
        'platform': 'divar',
        'title': 'آپارتمان ۸۵ متری نوساز',
        'desc': 'مشاور شما رضایی در خدمت شماست',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در جی'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (مشاور)'
    },
    {
        'platform': 'divar',
        'title': 'آپارتمان ۷۵ متری نزدیک املاک مرکزی',
        'desc': 'تخلیه و آماده تحویل فوری',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در پونک'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (املاک)'
    },
    {
        'platform': 'divar',
        'title': 'فروش واحد مسکن مهر پردیس',
        'desc': 'طبقه سوم با ویوی عالی',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در پردیس'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (مسکن)'
    },
    {
        'platform': 'divar',
        'title': 'خانه ویلایی ۱۲۰ متری دربست',
        'desc': 'مناسب برای سکونت یا ساخت',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در شهرری'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (خانه)'
    },
    {
        'platform': 'divar',
        'title': 'آپارتمان ۹۰ متری خوش نقشه',
        'desc': 'کارشناس امور ملکی آماده پاسخگویی است',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در تجریش'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (کارشناس)'
    },
    {
        'platform': 'divar',
        'title': 'آپارتمان ۶۰ متری فول',
        'desc': 'کمیسیون طبق تعرفه اتحادیه دریافت می‌گردد',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در ستارخان'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (کمیسیون)'
    },
    {
        'platform': 'divar',
        'title': 'واحد ۱۱۰ متری اکازیون',
        'desc': 'همکار تماس نگیرد فقط خریدار واقعی',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در مرزداران'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (همکار)'
    },

    # --- آزمون دقت مرز کلمات (Word Boundary): کلمه «کارخانه» نباید فیلتر شود ---
    {
        'platform': 'divar',
        'title': 'آپارتمان ۸۰ متری نزدیک کارخانه شیر',
        'desc': 'واحد تمیز و بدون پرتی، سند تک برگ شخصی، بدون واسطه',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در وردآورد'},
        'raw_text': '',
        'expected_personal': True,
        'expected_status': 'approved_personal',
        'description': 'بررسی عدم تداخل رگکس: کلمه کارخانه نباید باعث رد آگهی شود'
    },

    {
        'platform': 'divar',
        'title': 'آپارتمان ۸۵ متری خوش نقشه',
        'desc': 'جهت مشاوره و اطلاعات بیشتر تماس بگیرید',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در ونک'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_forbidden_words',
        'description': 'مرحله ۲: وجود کلمه (مشاوره)'
    },
    {
        'platform': 'divar',
        'title': '۹۰ متر ۲ خواب نوساز',
        'desc': 'فایل اختصاصی با بهترین متریال',
        'widget_data': {'bottom_description_text': 'املاک آرتا در تهرانپارس'},
        'raw_text': '',
        'expected_personal': False,
        'expected_status': 'rejected_account_type',
        'description': 'مرحله ۱: دیوار - پنل املاک آرتا در مشخصات حساب'
    },
    {
        'platform': 'sheypoor',
        'title': 'آپارتمان ۷۰ متری مشاوره املاک مهر',
        'desc': 'نورگیر عالی',
        'widget_data': {},
        'raw_text': 'مشاوره املاک مهر ۷۰ متر آپارتمان',
        'expected_personal': False,
        'expected_status': 'rejected_account_type',
        'description': 'مرحله ۱: شیپور - مشاوره املاک در کارت آگهی'
    },
    # --- آزمون‌های تأیید هویت شخصی (بدون کلمات فیلتر) ---
    {
        'platform': 'divar',
        'title': 'واحد ۸۵ متری تمیز شخصی ساز',
        'desc': 'فروشنده واقعی هستم به خریدار واقعی تخفیف پای معامله داده می‌شود',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در سعادت آباد'},
        'raw_text': '',
        'expected_personal': True,
        'expected_status': 'approved_personal',
        'description': 'شخصی تأیید شده: حساب شخصی دیوار + بدون کلمات فیلتر در متن'
    },

    # --- آزمون‌های آگهی تأییدشده شخصی (عبور از هر دو مرحله) ---
    {
        'platform': 'divar',
        'title': 'یک خوابه فاز دو اکباتان فروشی',
        'desc': 'واحد طبقه دوم بازسازی کامل، سند تک برگ آماده انتقال، بازدید با هماهنگی قبلی.',
        'widget_data': {'bottom_description_text': 'دقایقی پیش در اکباتان'},
        'raw_text': '',
        'expected_personal': True,
        'expected_status': 'approved_personal',
        'description': 'شخصی تأیید شده: حساب شخصی دیوار + بدون کلمات فیلتر در متن'
    },
    {
        'platform': 'sheypoor',
        'title': 'فروش آپارتمان 54 متر در تهرانسر',
        'desc': 'فروش مستقیم واحد ۵۴ متری، پارکینگ سندی، انباری، تخلیه آماده سکونت.',
        'widget_data': {},
        'raw_text': '۹ فروش آپارتمان 54 متر در تهرانسر ۴,۰۰۰,۰۰۰,۰۰۰ ۱۴۰۰ ۵۴ متر ۱ خوابه تهران، تهرانسر | لحظاتی پیش',
        'expected_personal': True,
        'expected_status': 'approved_personal',
        'description': 'شخصی تأیید شده در شیپور: حساب عادی کاربر + بدون کلمات فیلتر'
    }
]

print("=" * 80)
print("🧪 آزمون دقیق فیلتر دومرحله‌ای (۱. نوع آگهی‌دهنده -> ۲. کلمات متن و عنوان)")
print("=" * 80)

all_passed = True
for idx, tc in enumerate(test_cases, 1):
    res = OwnerFilter.evaluate(
        platform=tc['platform'],
        title=tc['title'],
        description=tc['desc'],
        widget_data=tc.get('widget_data'),
        raw_text=tc.get('raw_text', '')
    )
    
    passed_personal = (res.is_personal == tc['expected_personal'])
    passed_status = (res.status == tc['expected_status'])
    passed = passed_personal and passed_status

    if not passed:
        all_passed = False
    
    icon = "✅ PASS" if passed else "❌ FAIL"
    status_label = "شخصی/مالک" if res.is_personal else "غیرشخصی/ردشده"
    print(f"\nتست {idx}: {tc['description']}")
    print(f"  نتیجه: [{status_label}] | وضعیت کد: {res.status} (انتظار: {tc['expected_status']})")
    print(f"  علت رد/تأیید: {res.reason}")
    if res.detected_terms:
        print(f"  موارد شناسایی شده: {res.detected_terms}")
    print(f"  وضعیت آزمون: {icon}")

print("\n" + "=" * 80)
if all_passed:
    print("🎉 تمامی ۱۳ سناریوی آزمایشی با موفقیت ۱۰۰٪ پاس شدند!")
    print("✓ مرحله ۱ (نوع آگهی‌دهنده): تمام پنل‌های املاک، آژانس‌ها و حساب‌های تجاری درجا حذف شدند.")
    print("✓ مرحله ۲ (بررسی عنوان و متن): کلمات (املاک، مسکن، خانه، مشاور، کارشناس، کمیسیون، همکار) به درستی شناسایی و رد شدند.")
    print("✓ بدون خطای مثبت کاذب (کلماتی نظیر 'کارخانه' بدون مشکل تایید شدند).")
else:
    print("⚠️ خطایی در سناریوها رخ داده است.")
print("=" * 80)
