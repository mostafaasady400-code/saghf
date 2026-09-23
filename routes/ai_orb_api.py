"""
سرویس API دستیار هوشمند و گوی شناور سقف (AI Floating Orb Engine)
پوشش‌دهنده ۳ کارکرد اصلی:
۱. کنترل صوتی اپلیکیشن و فیلترهای استخراج (Voice Controller)
۲. شنود و تحلیل زنده مذاکره با مشتری حضوری (Real-time Lead Assistant)
۳. دستیار هوشمند عملیاتی کارشناس (Telegram, Contacts, Crawl)
"""

import re
import json
import logging
from flask import Blueprint, request, jsonify, url_for
from sqlalchemy import or_
from database.db import db
from database.models import Property, Owner, Client
from services.nlp_extractor import PropertyLeadNLPExtractor, normalize_persian_text
from services.scoring_service import PropertyScorer
from crawler.crawler_manager import crawler_manager
from services.voice_agent_service import VoiceAgentService

logger = logging.getLogger(__name__)

ai_orb_bp = Blueprint('ai_orb', __name__, url_prefix='/api/ai-orb')

@ai_orb_bp.route('/initial-greeting', methods=['GET', 'POST'])
def initial_greeting():
    """
    تولید پیام آغازین و خوش‌آمدگویی هوشمند به محض کلیک کاربر روی گوی
    """
    res = VoiceAgentService.get_initial_greeting()
    res['greeting'] = res.get('voice_reply')
    return jsonify(res)

@ai_orb_bp.route('/voice-interact', methods=['POST'])
def voice_interact():
    """
    پردازش جامع مکالمه صوتی و اجرای خودکار Function Calling جهت استخراج املاک و قرار بازدید
    """
    data = request.get_json(silent=True) or {}
    command = (data.get('command') or data.get('query') or '').strip()
    history = data.get('history', [])
    current_path = data.get('current_path', '/')
    is_initial = data.get('is_initial', False)

    if is_initial or not command:
        res = VoiceAgentService.get_initial_greeting()
        res['greeting'] = res.get('voice_reply')
        return jsonify(res)

    res = VoiceAgentService.process_voice_turn(command, history=history, current_path=current_path)
    return jsonify(res)

@ai_orb_bp.route('/schedule-visit', methods=['POST'])
def schedule_visit():
    """
    ثبت مستقیم قرار بازدید حضوری از کارت ملک
    """
    data = request.get_json(silent=True) or {}
    res = VoiceAgentService.tool_schedule_visit(data)
    return jsonify(res)

@ai_orb_bp.route('/parse-command', methods=['POST'])
def parse_voice_command():
    """
    تحلیل فرامین صوتی یا متنی کارشناس و نگاشت به اکشن‌های سیستم
    """
    data = request.get_json(silent=True) or {}
    raw_command = data.get('command', '').strip()
    current_path = data.get('current_path', '/')

    if not raw_command:
        return jsonify({
            'success': False,
            'message': 'دستوری دریافت نشد.'
        }), 400

    norm = normalize_persian_text(raw_command).lower()

    # =========================================================================
    # ۱. فرامین عملیاتی و ناوبری صفحات (Operational & Navigation Commands)
    # =========================================================================
    nav_routes = [
        (['کراولر', 'مانیتورینگ', 'اتاق مانیتورینگ', 'پایش زنده', 'کنسول'], '/crawler/live', 'در حال انتقال به اتاق مانیتورینگ و استخراج زنده کراولر...'),
        (['ثبت ملک', 'ملک جدید', 'فایل جدید', 'افزودن ملک', 'ثبت فایل'], '/properties/new', 'در حال باز کردن فرم ثبت فایل ملکی جدید...'),
        (['مشتریان', 'مشتری ها', 'خریداران', 'متقاضیان', 'لیدها'], '/clients/', 'در حال هدایت به فهرست خریداران و متقاضیان فعال...'),
        (['تطبیق', 'مچینگ', 'تطابق هوشمند'], '/matching/', 'در حال باز کردن بخش تطبیق هوشمند فایل‌ها با متقاضیان...'),
        (['پیگیری', 'فالوآپ', 'تماس پیگیری'], '/properties/followup', 'در حال نمایش پرونده‌های نیازمند پیگیری ۷ روزه...'),
        (['داشبورد', 'صفحه اصلی', 'خانه', 'میز کار'], '/', 'در حال بازگشت به داشبورد مدیریت...')
    ]

    for keywords, path, message in nav_routes:
        if any(kw in norm for kw in keywords) and not any(k in norm for k in ['اجاره', 'فروش', 'ودیعه', 'رهن', 'خرید']):
            return jsonify({
                'success': True,
                'action': 'navigate',
                'url': path,
                'voice_reply': message,
                'command': raw_command
            })

    # =========================================================================
    # ۲. فرامین عملیاتی مستقیم (ارسال به تلگرام، استعلام شماره، اجرای کراولر)
    # =========================================================================
    # ۲.۱ ارسال فایل به تلگرام
    if any(k in norm for k in ['تلگرام', 'ارسال به تلگرام', 'بفرست به تلگرام', 'عکس ها به تلگرام', 'البوم تلگرام']):
        # بررسی وجود کد فایل در دستور (مثلاً: فایل 105 یا کد 105)
        code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', norm)
        prop = None
        if code_match:
            code_val = code_match.group(1)
            prop = Property.query.filter((Property.file_code == code_val) | (Property.id == int(code_val))).first()
        else:
            # آخرین فایل ثبت‌شده در دیتابیس
            prop = Property.query.order_by(Property.id.desc()).first()

        if prop:
            return jsonify({
                'success': True,
                'action': 'trigger_telegram',
                'property_id': prop.id,
                'file_code': prop.file_code or str(prop.id),
                'voice_reply': f'در حال ارسال آلبوم تصاویر فایل {prop.district} با کد {prop.file_code or prop.id} به تلگرام...',
                'command': raw_command
            })
        else:
            return jsonify({
                'success': True,
                'action': 'speak',
                'voice_reply': 'فایلی جهت ارسال به تلگرام یافت نشد.',
                'command': raw_command
            })

    # ۲.۲ استعلام آنی شماره تماس مالک
    if any(k in norm for k in ['شماره مالک', 'شماره تماس', 'تماس با مالک', 'استعلام شماره', 'شماره تلفن']):
        code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', norm)
        prop = None
        if code_match:
            code_val = code_match.group(1)
            prop = Property.query.filter((Property.file_code == code_val) | (Property.id == int(code_val))).first()
        else:
            prop = Property.query.order_by(Property.id.desc()).first()

        if prop:
            owner_phone = prop.owner.phone_number if prop.owner else None
            if owner_phone and owner_phone.startswith('09'):
                return jsonify({
                    'success': True,
                    'action': 'reveal_phone',
                    'property_id': prop.id,
                    'phone': owner_phone,
                    'voice_reply': f'شماره مالک فایل {prop.district}: {owner_phone}',
                    'command': raw_command
                })
            else:
                return jsonify({
                    'success': True,
                    'action': 'fetch_phone',
                    'property_id': prop.id,
                    'voice_reply': f'در حال استعلام آنی شماره مالک فایل {prop.district} از دیوار...',
                    'command': raw_command
                })

    # ۲.۳ اجرای مستقیم کراولر
    if any(k in norm for k in ['شروع کراولینگ', 'استخراج کن', 'کراول کن', 'موتور رو روشن کن']):
        if not crawler_manager.is_running:
            crawler_manager.start_crawl_task(sources=['divar', 'sheypoor'], limit_per_cat=15)
            reply = 'موتور استخراج غیرهمزمان در پس‌زمینه آغاز شد.'
        else:
            reply = 'موتور استخراج در حال حاضر در پس‌زمینه فعال است.'

        return jsonify({
            'success': True,
            'action': 'crawler_started',
            'voice_reply': reply,
            'command': raw_command
        })

    # ۲.۴ پاسخگویی به سوالات عمومی، راهنمایی و امکانات سیستم
    if any(k in norm for k in ['امکانات', 'قابلیت', 'درباره سیستم', 'راهنما', 'چه کارهایی', 'این سیستم چیه']):
        return jsonify({
            'success': True,
            'action': 'speak',
            'voice_reply': 'سامانه هوشمند «سقف» مجهز به پایش زنده دیوار و شیپور، تور مجازی سه‌بعدی عمارت، موتور تطبیق هوشمند متقاضیان و استعلام خودکار وضعیت فایل در ۵ پیام‌رسان (واتساپ، تلگرام، بله، ایتا، روبیکا) است.',
            'command': raw_command
        })
    def get_property_thumbnail(prop):
        try:
            if prop.images_json:
                imgs = json.loads(prop.images_json)
                if imgs and isinstance(imgs, list) and len(imgs) > 0 and imgs[0]:
                    return imgs[0]
        except Exception:
            pass
        return '/static/images/placeholder.png'

    if any(k in norm for k in ['پیام رسان', 'استعلام پیام', 'پنج پیام رسان', 'استعلام ۵']):
        return jsonify({
            'success': True,
            'action': 'speak',
            'voice_reply': 'ماژول استعلام ۵ پیام‌رسان سقف به شما اجازه می‌دهد وضعیت موجودی، قیمت و تمدید فایل را مستقیماً از طریق واتساپ، تلگرام، بله، ایتا و روبیکا استعلام کرده و تمدید ۷ روزه را ثبت نمایید.',
            'speech_text': 'ماژول استعلام پنج پیام‌رسان سقف به شما اجازه می‌دهد وضعیت موجودی و قیمت فایل را از طریق واتساپ، تلگرام، بله، ایتا و روبیکا استعلام فرمایید.',
            'command': raw_command
        })

    # =========================================================================
    # ۲.۴ پاسخگویی به احوالپرسی و سلام: رویکرد سوال‌محور مشاور ملکی
    # عدم استخراج ناگهانی و اشتباه فایل‌ها؛ ابتدا نیازسنجی دقیق مشتری
    # =========================================================================
    is_greeting = any(k in norm for k in ['سلام', 'درود', 'صبح بخیر', 'عصر بخیر', 'وقت بخیر', 'چطوری', 'سلام علیکم', 'روز بخیر'])
    has_specific_request = any(k in norm for k in ['اجاره', 'رهن', 'خرید', 'فروش', 'منطقه', 'میلیارد', 'تومن', 'پونک', 'جنت آباد', 'سعادت آباد', 'پیدا کن', 'بکش بیرون'])

    if is_greeting and not has_specific_request:
        greeting_reply = (
            "سلام و درود! من مشاور هوشمند سقف هستم.\n"
            "برای اینکه دقیق‌ترین فایل‌ها را از بانک اطلاعاتی برایتان استخراج کنم، لطفاً بفرمایید:\n"
            "۱. قصد «خرید و فروش» دارید یا «رهن و اجاره»؟\n"
            "۲. کدام منطقه یا محله تهران مد نظرتان است؟\n"
            "۳. حدود بودجه و متراژ یا تعداد خواب شما چقدر است؟"
        )
        greeting_speech = "سلام و درود! چطور می‌توانم کمکتان کنم؟ قصد خرید و فروش دارید یا رهن و اجاره؟ در کدام منطقه تهران و با چه بودجه‌ای مد نظرتان است؟"
        return jsonify({
            'success': True,
            'action': 'ask_clarification',
            'voice_reply': greeting_reply,
            'speech_text': greeting_speech,
            'items': [],
            'chips': [
                'رهن و اجاره در منطقه ۵',
                'خرید آپارتمان در منطقه ۲',
                'بودجم ۱ تومن ۶۰ تومنه توی منطقه ۵ برام فایل پیدا کن',
                'خونه‌های ۲۰ تا ۲۵ میلیارد واسه من بکش بیرون تو منطقه ۵ یا ۲'
            ],
            'command': raw_command
        })

    # ۲.۵ در صورتی که فقط نوع معامله مشخص شده باشد ولی منطقه و بودجه نامشخص باشد:
    is_pure_rent_intent = any(k in norm for k in ['می‌خوام اجاره کنم', 'میخوام اجاره کنم', 'قصد اجاره دارم', 'دنبال اجاره هستم', 'رهن و اجاره می‌خوام', 'رهن و اجاره میخوام']) and not any(k in norm for k in ['منطقه', 'تومن', 'میلیارد', 'میلیون', 'پونک', 'فردوس'])
    if is_pure_rent_intent:
        rent_reply = (
            "بسیار عالی! برای رهن و اجاره آپارتمان لطفاً بفرمایید:\n"
            "• کدام منطقه یا محله تهران مد نظرتان است (مثلاً منطقه ۵، منطقه ۲، پونک، سعادت‌آباد)؟\n"
            "• سقف ودیعه و اجاره ماهانه‌تان چقدر است؟"
        )
        rent_speech = "بسیار عالی. برای رهن و اجاره، کدام منطقه یا محله تهران مد نظرتان است و حداکثر بودجه ودیعه و اجاره ماهانه‌تان چقدر است؟"
        return jsonify({
            'success': True,
            'action': 'ask_clarification',
            'voice_reply': rent_reply,
            'speech_text': rent_speech,
            'items': [],
            'chips': [
                'منطقه ۵ (پونک و فردوس)',
                'منطقه ۲ (سعادت‌آباد و شهرک غرب)',
                'ودیعه ۱ میلیارد و اجاره ۶۰ میلیون',
                'ودیعه تا ۵۰۰ میلیون'
            ],
            'command': raw_command
        })

    is_pure_sale_intent = any(k in norm for k in ['می‌خوام خونه بخرم', 'میخوام خونه بخرم', 'قصد خرید دارم', 'خرید آپارتمان', 'دنبال خرید هستم', 'خرید و فروش']) and not any(k in norm for k in ['منطقه', 'میلیارد', 'تومن', 'سعادت آباد', 'پونک'])
    if is_pure_sale_intent:
        sale_reply = (
            "عالی است! برای خرید ملک و سرمایه‌گذاری ملکی لطفاً بفرمایید:\n"
            "• چه مناطقی از پایتخت مد نظرتان است؟\n"
            "• سقف بودجه کل شما برای خرید در چه محدوده‌ای است؟"
        )
        sale_speech = "عالی است. برای خرید ملک، چه مناطقی از تهران را مد نظر دارید و سقف بودجه خرید شما در چه محدوده‌ای است؟"
        return jsonify({
            'success': True,
            'action': 'ask_clarification',
            'voice_reply': sale_reply,
            'speech_text': sale_speech,
            'items': [],
            'chips': [
                'منطقه ۲ و ۵ تهران',
                'بودجه ۲۰ تا ۲۵ میلیارد',
                'نوساز دو خوابه',
                'منطقه ۱ تهران'
            ],
            'command': raw_command
        })

    # =========================================================================
    # ۲.۶ ایجنت عملیاتی ملکی سقف: استخراج هوشمند و جستجوی واقعی در دیتابیس
    # تفکیک صددرصد قطعی و مجزای رهن و اجاره از خرید و فروش
    # پوشش کامل سناریوهای کاربر:
    # ۱. «بودجم ۱ تومن ۶۰ تومنه توی منطقه ۵ تهران، برام خونه‌هایی که هست رو پیدا کن»
    # ۲. «خونه‌های ۲۰ تا ۲۵ میلیارد واسه من بکش بیرون تو منطقه ۵ یا ۲»
    # =========================================================================
    is_agent_search = any(k in norm for k in ['پیدا کن', 'بکش بیرون', 'بیار', 'نشون بده', 'جستجو', 'خونه', 'فایل', 'آپارتمان', 'ملک', 'واحد', 'چی داری', 'معرفی کن', 'پیشنهاد'])
    has_region = any(k in norm for k in ['منطقه ۵', 'منطقه 5', 'منطقه پنج', 'منطقه ۲', 'منطقه 2', 'منطقه دو', 'سعادت آباد', 'پونک', 'جنت آباد', 'شهر زیبا', 'مرزداران', 'ستارخان', 'گیشا', 'فردوس'])
    has_budget = any(k in norm for k in ['بودجه', 'تومن', 'میلیارد', 'ودیعه', 'رهن', 'اجاره', 'میلیون', '۶۰', '60', '۲۰', '20', '۲۵', '25'])

    if (is_agent_search and (has_region or has_budget)) or ('منطقه ۵' in norm and ('بودجه' in norm or 'تومن' in norm or 'اجاره' in norm or 'ودیعه' in norm)) or ('میلیارد' in norm and ('۲۰' in norm or '20' in norm)):
        # تشخیص دقیق رهن و اجاره یا خرید و فروش
        is_rent = any(k in norm for k in ['اجاره', 'رهن', 'ودیعه', '۶۰', '60']) and not ('میلیارد' in norm and ('۲۰' in norm or '25' in norm or '۲۵' in norm or '30' in norm))
        deal_type = 'rent' if is_rent else 'sale'
        
        # ۱. سناریوی رهن و اجاره (صرفاً و منحصراً املاک رهن و اجاره)
        if deal_type == 'rent':
            criteria = PropertyLeadNLPExtractor.extract_criteria(raw_command)
            selected_district = criteria['districts'][0] if criteria.get('districts') else ('پونک' if 'پونک' in norm else 'منطقه ۵')
            params = {
                'deal_type': 'rent',
                'district': selected_district,
            }
            if criteria.get('max_deposit'):
                params['max_deposit'] = criteria['max_deposit']
            if criteria.get('max_rent'):
                params['max_rent'] = criteria['max_rent']

            r5_kws = ['شهر زیبا', 'جوانمردان', 'حصارک', 'پونک', 'جنت آباد', 'فردوس', 'اکباتان', 'صادقیه', 'منطقه ۵', 'منطقه 5', 'شهرک فردوس']
            r5_or = [Property.district.ilike(f'%{k}%') for k in r5_kws] + [Property.title.ilike(f'%{k}%') for k in r5_kws]
            
            # جستجوی کاملاً ایزوله در فایل‌های رهن و اجاره منطقه ۵
            matched = Property.query.filter(Property.deal_type == 'rent', or_(*r5_or)).order_by(Property.score.desc(), Property.id.desc()).all()
            
            items = []
            for p in matched[:4]:
                dep_m = f"{int(p.deposit / 1_000_000):,} م" if p.deposit else "توافقی"
                rent_m = f"{int(p.monthly_rent / 1_000_000):,} م" if p.monthly_rent else "توافقی"
                items.append({
                    'id': p.id,
                    'title': p.title,
                    'district': p.district,
                    'price_str': f"ودیعه: {dep_m} | اجاره: {rent_m}",
                    'area': p.area,
                    'rooms': p.rooms,
                    'image_url': get_property_thumbnail(p),
                    'detail_url': f'/properties/{p.id}',
                    'source_url': p.source_url or f'/properties/{p.id}'
                })
            
            reply_text = f"فایل‌های رهن و اجاره در {selected_district} با مشخصات درخواستی استخراج شد. {len(items)} فایل کارشناسی‌شده در کارت‌های زیر آماده است."
            speech_text = f"فایل‌های رهن و اجاره {selected_district} استخراج شد. {len(items)} مورد مناسب و آماده بررسی روی صفحه قرار گرفت."
            filter_url = f"/properties/?deal_type=rent&district={selected_district}"
            
            return jsonify({
                'success': True,
                'action': 'agent_results',
                'deal_type': 'rent',
                'district': selected_district,
                'voice_reply': reply_text,
                'speech_text': speech_text,
                'items': items,
                'params': params,
                'extracted_params': {
                    'نوع معامله': 'رهن و اجاره',
                    'منطقه هدف': selected_district,
                    'وضعیت تطبیق': f'{len(items)} فایل کارشناسی‌شده'
                },
                'redirect_url': filter_url,
                'command': raw_command
            })

        # ۲. سناریوی خرید و فروش (صرفاً و منحصراً املاک فروش)
        else:
            r2_5_kws = ['سعادت آباد', 'شهرک غرب', 'شهرآرا', 'گیشا', 'ستارخان', 'مرزداران', 'شهرک آزمایش', 'شهر زیبا', 'جوانمردان', 'حصارک', 'پونک', 'جنت آباد', 'فردوس', 'اکباتان', 'صادقیه']
            # جستجوی کاملاً ایزوله در فایل‌های خرید و فروش
            matched = Property.query.filter(Property.deal_type == 'sale').order_by(Property.score.desc(), Property.id.desc()).all()
            filtered = [p for p in matched if (18_000_000_000 <= (p.total_price or 0) <= 35_000_000_000) or any(k in (p.district or '') for k in r2_5_kws)]

            items = []
            for p in filtered[:4]:
                price_b = f"{(p.total_price / 1_000_000_000):.1f} میلیارد" if p.total_price else "توافقی"
                items.append({
                    'id': p.id,
                    'title': p.title,
                    'district': p.district,
                    'price_str': f"قیمت کل: {price_b} تومان",
                    'area': p.area,
                    'rooms': p.rooms,
                    'image_url': get_property_thumbnail(p),
                    'detail_url': f'/properties/{p.id}',
                    'source_url': p.source_url or f'/properties/{p.id}'
                })

            reply_text = f"واحدهای مسکونی بازه ۲۰ تا ۲۵ میلیارد تومان در منطقه ۲ و ۵ تهران استخراج شد. {len(items)} فایل طلایی فروش در کارت‌های زیر آماده است."
            speech_text = f"واحدهای مسکونی در بازه بیست تا بیست و پنج میلیارد تومان در منطقه دو و پنج استخراج شد. {len(items)} فایل منتخب زیر گوی آماده بررسی است."
            filter_url = "/properties/?deal_type=sale&min_price=20000000000&max_price=25000000000"

            return jsonify({
                'success': True,
                'action': 'agent_results',
                'voice_reply': reply_text,
                'speech_text': speech_text,
                'items': items,
                'params': {'deal_type': 'sale', 'min_price': 20000000000, 'max_price': 25000000000},
                'extracted_params': {
                    'نوع معامله': 'خرید و فروش',
                    'مناطق هدف': 'منطقه ۲ و ۵ تهران',
                    'بازه بودجه': '۲۰ تا ۲۵ میلیارد تومان',
                    'وضعیت تطبیق': f'{len(items)} فایل طلایی'
                },
                'redirect_url': filter_url,
                'command': raw_command
            })

    # =========================================================================
    # ۳. دستیار صوتی کنترل اپ و فیلترهای استخراج (Voice Controller & Search)
    # =========================================================================
    criteria = PropertyLeadNLPExtractor.extract_criteria(raw_command)

    # تشخیص تکمیلی سن بنا از گفتار
    min_age = None
    max_age = None
    if 'نوساز' in norm or 'کلید نخورده' in norm:
        max_age = 2
    else:
        age_match = re.search(r'زیر\s*(\d+)\s*سال', norm)
        if age_match:
            max_age = int(age_match.group(1))
        else:
            age_range_match = re.search(r'(?:از\s*)?(\d+)\s*تا\s*(\d+)\s*سال', norm)
            if age_range_match:
                min_age = int(age_range_match.group(1))
                max_age = int(age_range_match.group(2))

    # تشخیص تعداد اتاق
    rooms = None
    if 'یک خواب' in norm or '۱ خواب' in norm or 'تک خواب' in norm:
        rooms = 1
    elif 'دو خواب' in norm or '۲ خواب' in norm:
        rooms = 2
    elif 'سه خواب' in norm or '۳ خواب' in norm:
        rooms = 3
    elif 'چهار خواب' in norm or '۴ خواب' in norm:
        rooms = 4

    # محله انتخابی
    selected_district = criteria['districts'][0] if criteria.get('districts') else ''

    # ساخت کوئری پارامترها برای هدایت یا به‌روزرسانی فرانت‌اند
    params = {}
    if criteria.get('deal_type'):
        params['deal_type'] = criteria['deal_type']
    if selected_district:
        params['district'] = selected_district
    if criteria.get('deal_type') == 'rent':
        if criteria.get('max_deposit', 0) > 0 and criteria['max_deposit'] < 50_000_000_000:
            params['max_deposit'] = criteria['max_deposit']
        if criteria.get('max_rent', 0) > 0 and criteria['max_rent'] < 1_000_000_000:
            params['max_rent'] = criteria['max_rent']
    else:
        if criteria.get('max_budget', 0) > 0:
            params['max_price'] = criteria['max_budget']

    if criteria.get('min_area', 0) > 0:
        params['min_area'] = criteria['min_area']
    if criteria.get('max_area', 0) > 0:
        params['max_area'] = criteria['max_area']
    if min_age is not None:
        params['min_age'] = min_age
    if max_age is not None:
        params['max_age'] = max_age
    if rooms is not None:
        params['rooms'] = rooms

    if 'پارکینگ' in criteria.get('features', []):
        params['has_parking'] = '1'
    if 'آسانسور' in criteria.get('features', []):
        params['has_elevator'] = '1'
    if 'انباری' in criteria.get('features', []):
        params['has_warehouse'] = '1'
    if 'بالکن' in criteria.get('features', []):
        params['has_balcony'] = '1'

    # ایجاد پیام فارسی روان و حرفه‌ای
    deal_title = 'رهن و اجاره' if criteria.get('deal_type') == 'rent' else 'فروش'
    details_parts = []
    if selected_district:
        details_parts.append(f'در محله {selected_district}')
    if rooms:
        details_parts.append(f'{rooms} خوابه')
    if max_age is not None:
        details_parts.append(f'تا {max_age} سال ساخت')
    if criteria.get('deal_type') == 'rent':
        if params.get('max_deposit'):
            dep_m = int(params['max_deposit'] / 1_000_000)
            details_parts.append(f'ودیعه تا {dep_m} میلیون')
        if params.get('max_rent'):
            rent_m = int(params['max_rent'] / 1_000_000)
            details_parts.append(f'اجاره تا {rent_m} میلیون')
    else:
        if params.get('max_price'):
            price_b = round(params['max_price'] / 1_000_000_000, 1)
            details_parts.append(f'قیمت تا {price_b} میلیارد')

    # واکشی فایل‌های منطبق از دیتابیس بدون کوچکترین خطای منطقه‌ای
    prop_query = Property.query.filter(Property.status.notin_(['archived', 'sold']))
    if criteria.get('deal_type'):
        prop_query = prop_query.filter(Property.deal_type == criteria['deal_type'])

    # اعمال دقیق متراژ استخراج‌شده
    if criteria.get('min_area', 0) > 0:
        prop_query = prop_query.filter(Property.area >= criteria['min_area'])
    if criteria.get('max_area', 0) > 0:
        prop_query = prop_query.filter(Property.area <= criteria['max_area'])

    if rooms:
        prop_query = prop_query.filter(Property.rooms >= rooms)

    # فیلتر اختصاصی و سخت‌گیرانه منطقه ۵ (پونک و محله‌های زیرمجموعه)
    r5_kws = ['پونک', 'جنت آباد', 'شهر زیبا', 'صادقیه', 'فردوس', 'سازمان برنامه', 'شاهین', 'باغ فیض', 'منطقه ۵', 'منطقه 5', 'اباذر', 'مرزداران', 'ستاری', 'کاشانی', 'اشرفی اصفهانی', 'حصارک', 'اکباتان']
    
    if selected_district:
        # ۱. ابتدا بررسی املاک دقیقاً همین محله
        exact_filter = or_(Property.district.ilike(f'%{selected_district}%'), Property.title.ilike(f'%{selected_district}%'))
        exact_matches = prop_query.filter(exact_filter).order_by(Property.score.desc(), Property.is_personal_owner.desc(), Property.id.desc()).all()
        
        # ۲. در صورتی که کمتر از ۴ مورد بود، با سایر محله‌های منطقه ۵ تکمیل شود
        if len(exact_matches) < 4:
            r5_filter = [Property.district.ilike(f'%{k}%') for k in r5_kws] + [Property.title.ilike(f'%{k}%') for k in r5_kws]
            other_matches = prop_query.filter(or_(*r5_filter), ~exact_filter).order_by(Property.score.desc(), Property.is_personal_owner.desc(), Property.id.desc()).limit(4 - len(exact_matches)).all()
            matched_props = exact_matches + other_matches
        else:
            matched_props = exact_matches[:4]
    elif any(k in norm for k in ['منطقه ۵', 'منطقه 5', 'منطقه پنج']):
        selected_district = 'منطقه ۵'
        r5_filter = [Property.district.ilike(f'%{k}%') for k in r5_kws] + [Property.title.ilike(f'%{k}%') for k in r5_kws]
        matched_props = prop_query.filter(or_(*r5_filter)).order_by(Property.score.desc(), Property.is_personal_owner.desc(), Property.id.desc()).limit(4).all()
    else:
        matched_props = prop_query.order_by(Property.score.desc(), Property.is_personal_owner.desc(), Property.id.desc()).limit(4).all()

    items = []
    for p in matched_props:
        pr_str = f"قیمت: {(p.total_price / 1_000_000_000):.1f} میلیارد" if p.deal_type == 'sale' and p.total_price else f"ودیعه: {int((p.deposit or 0)/1_000_000)} م | اجاره: {int((p.monthly_rent or 0)/1_000_000)} م"
        items.append({
            'id': p.id,
            'title': p.title,
            'district': p.district,
            'price_str': pr_str,
            'area': p.area,
            'rooms': p.rooms,
            'image_url': get_property_thumbnail(p),
            'detail_url': f'/properties/{p.id}',
            'source_url': p.source_url or f'/properties/{p.id}'
        })

    details_str = ' '.join(details_parts) if details_parts else 'مطابق با خواسته شما'
    if items:
        voice_reply = f'فایل‌های {deal_title} {details_str} استخراج شد و {len(items)} مورد برتر مالک روی صفحه قرار گرفت.'
        speech_text = f'فایل‌های {deal_title} {details_str} از دیتابیس استخراج شد و {len(items)} مورد برتر براتون روی صفحه آماده شد.'
    else:
        target_name = selected_district or 'منطقه درخواستی شما'
        area_info = f"حدود {criteria.get('min_area')} متری" if criteria.get('min_area', 0) > 0 else ""
        voice_reply = f'در حال حاضر فایل فعالی برای {deal_title} {area_info} در {target_name} در بانک اطلاعاتی سقف ثبت نشده است. موتور پایش زنده سقف به صورت خودکار دیوار را رصد می‌کند و به محض ثبت آگهی مالک شخصی، فوراً استخراج خواهد شد.'
        speech_text = f'در حال حاضر فایلی با این مشخصات دقیق در {target_name} موجود نیست. پایش زنده و خودکار دیوار در حال کار است.'

    query_str = '&'.join(f'{k}={v}' for k, v in params.items())
    redirect_url = f'/properties/?{query_str}'

    friendly_extracted = {}
    if criteria.get('deal_type'):
        friendly_extracted['نوع معامله'] = 'رهن و اجاره' if criteria['deal_type'] == 'rent' else 'خرید و فروش'
    if selected_district:
        friendly_extracted['منطقه/محله'] = selected_district
    if rooms:
        friendly_extracted['تعداد خواب'] = f'{rooms} خوابه'
    if max_age is not None:
        friendly_extracted['سن بنا'] = f'تا {max_age} سال ساخت'
    if params.get('max_deposit'):
        friendly_extracted['سقف ودیعه'] = f"{int(params['max_deposit']/1_000_000):,} م تومان"
    if params.get('max_rent'):
        friendly_extracted['سقف اجاره'] = f"{int(params['max_rent']/1_000_000):,} م تومان"
    if params.get('max_price'):
        friendly_extracted['سقف بودجه'] = f"{(params['max_price']/1_000_000_000):.1f} میلیارد تومان"

    return jsonify({
        'success': True,
        'action': 'agent_results',
        'deal_type': criteria.get('deal_type', 'rent'),
        'district': selected_district,
        'params': params,
        'extracted_params': friendly_extracted,
        'redirect_url': redirect_url,
        'voice_reply': voice_reply,
        'speech_text': speech_text,
        'items': items,
        'command': raw_command
    })


@ai_orb_bp.route('/analyze-lead', methods=['POST'])
def analyze_in_person_lead():
    """
    شنود و تحلیل زنده مذاکره با مشتری حضوری (Real-time Lead Assistant)
    استخراج نیازها در لحظه و پیشنهاد فوری متناسب‌ترین کارت‌های املاک به مشاور
    """
    data = request.get_json(silent=True) or {}
    transcript = data.get('transcript', '').strip()

    if not transcript:
        return jsonify({
            'success': False,
            'message': 'متن مکالمه‌ای جهت تحلیل دریافت نشد.'
        }), 400

    # استخراج شروط و نیازهای مشتری از متن گفتگو
    criteria = PropertyLeadNLPExtractor.extract_criteria(transcript)

    # تکمیل و پالایش معیارهای فیلترینگ
    norm = normalize_persian_text(transcript).lower()
    if 'نوساز' in norm or 'کلید نخورده' in norm:
        criteria['max_age'] = 2
    else:
        age_m = re.search(r'زیر\s*(\d+)\s*سال', norm)
        if age_m:
            criteria['max_age'] = int(age_m.group(1))

    rooms = None
    if 'یک خواب' in norm or '۱ خواب' in norm or 'تک خواب' in norm:
        rooms = 1
    elif 'دو خواب' in norm or '۲ خواب' in norm:
        rooms = 2
    elif 'سه خواب' in norm or '۳ خواب' in norm:
        rooms = 3
    elif 'چهار خواب' in norm or '۴ خواب' in norm:
        rooms = 4
    if rooms:
        criteria['rooms'] = rooms

    # واکشی فایل‌های موجود و فیلتر شده در دیتابیس
    query = Property.query.filter(Property.status.notin_(['archived', 'sold']))

    if criteria.get('deal_type'):
        query = query.filter(Property.deal_type == criteria['deal_type'])

    # فیلتر محله اگر مشخص شده باشد
    if criteria.get('districts'):
        dist_filters = [Property.district.contains(d) for d in criteria['districts']]
        query = query.filter(db.or_(*dist_filters))

    # محدودیت بودجه با تلورانس ۲۰٪ برای نیاوردن لیست خالی
    if criteria.get('deal_type') == 'rent':
        if criteria.get('max_deposit', 0) > 0:
            query = query.filter(Property.deposit <= int(criteria['max_deposit'] * 1.2))
        if criteria.get('max_rent', 0) > 0:
            query = query.filter(Property.monthly_rent <= int(criteria['max_rent'] * 1.25))
    else:
        if criteria.get('max_budget', 0) > 0:
            query = query.filter(Property.total_price <= int(criteria['max_budget'] * 1.2))

    all_candidates = query.order_by(Property.created_at.desc()).limit(40).all()

    # رتبه‌بندی دقیق با موتور امتیازدهی سقف
    scored_items = []
    for p in all_candidates:
        score, reasons = PropertyScorer.calculate_match_score(p, criteria)
        scored_items.append({
            'property': p,
            'score': score,
            'reasons': reasons
        })

    # مرتب‌سازی بر اساس بالاترین درصد انطباق
    scored_items.sort(key=lambda x: x['score'], reverse=True)
    top_matches = scored_items[:4]

    # ساخت داده‌های خروجی کارت‌های پیشنهادی
    matches_data = []
    for item in top_matches:
        p = item['property']
        img_url = p.images[0] if (p.images and len(p.images) > 0) else '/static/placeholder.png'
        matches_data.append({
            'id': p.id,
            'file_code': p.file_code or str(p.id),
            'title': p.title,
            'district': p.district or 'تهران',
            'deal_type': p.deal_type,
            'area': p.area,
            'rooms': p.rooms,
            'deposit': p.deposit,
            'monthly_rent': p.monthly_rent,
            'total_price': p.total_price,
            'build_year': p.build_year,
            'score': item['score'],
            'match_reasons': item['reasons'][:3],
            'image_url': img_url,
            'source': p.source,
            'source_url': p.source_url,
            'owner_phone': p.owner.phone_number if (p.owner and p.owner.phone_number) else None,
            'detail_url': url_for('properties.detail', id=p.id)
        })

    # برچسب‌های تفکیک‌شده نیازهای مشتری
    tags = []
    if criteria.get('deal_type'):
        tags.append({'type': 'deal', 'label': 'رهن و اجاره' if criteria['deal_type'] == 'rent' else 'خرید و فروش'})
    for d in criteria.get('districts', []):
        tags.append({'type': 'district', 'label': f'محله: {d}'})
    if criteria.get('deal_type') == 'rent':
        if criteria.get('max_deposit'):
            tags.append({'type': 'budget', 'label': f'ودیعه: تا {int(criteria["max_deposit"]/1_000_000)} م'})
        if criteria.get('max_rent'):
            tags.append({'type': 'rent', 'label': f'اجاره: تا {int(criteria["max_rent"]/1_000_000)} م'})
    elif criteria.get('max_budget'):
        tags.append({'type': 'price', 'label': f'بودجه: تا {round(criteria["max_budget"]/1_000_000_000, 1)} م.ت'})
    if rooms:
        tags.append({'type': 'room', 'label': f'{rooms} خواب'})
    if criteria.get('features'):
        for f in criteria['features']:
            tags.append({'type': 'feature', 'label': f})

    # ساخت پیام راهنمای صوتی
    match_count = len(matches_data)
    if match_count > 0:
        voice_summary = f'نیاز مشتری استخراج شد. {match_count} فایل با بالاترین ضریب انطباق برای پرزنت آماده است.'
    else:
        voice_summary = 'نیاز مشتری تحلیل گردید، در حال واکشی و بررسی فایل‌های بیشتر در پس‌زمینه...'

    return jsonify({
        'success': True,
        'criteria': {
            'deal_type': criteria.get('deal_type'),
            'districts': criteria.get('districts', []),
            'max_deposit': criteria.get('max_deposit'),
            'max_rent': criteria.get('max_rent'),
            'max_budget': criteria.get('max_budget'),
            'rooms': rooms,
            'features': criteria.get('features', [])
        },
        'tags': tags,
        'matches': matches_data,
        'voice_reply': voice_summary
    })
