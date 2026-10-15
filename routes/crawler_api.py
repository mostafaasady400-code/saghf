from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from crawler.crawler_manager import crawler_manager
from database.models import Property, SearchRun

crawler_bp = Blueprint('crawler', __name__, url_prefix='/crawler')

@crawler_bp.route('/')
def index():
    return redirect(url_for('crawler.live_monitor'))

@crawler_bp.route('/live')
def live_monitor():
    # نمایش همه آگهی‌های استخراج‌شده با اولویت «مالک هستم» و ترتیب جدیدترین
    sale_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'sale'
    ).order_by(
        Property.is_personal_owner.desc(),
        Property.score.desc(),
        Property.created_at.desc()
    ).all()

    rent_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.deal_type == 'rent'
    ).order_by(
        Property.is_personal_owner.desc(),
        Property.score.desc(),
        Property.created_at.desc()
    ).all()

    crawled_properties = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor'])
    ).order_by(Property.created_at.desc()).all()

    return render_template(
        'crawler/live.html',
        sale_properties=sale_properties,
        rent_properties=rent_properties,
        crawled_properties=crawled_properties
    )

@crawler_bp.route('/districts', methods=['GET'])
def get_districts():
    from data.tehran_districts import TEHRAN_REGIONS
    region = request.args.get('region')
    if region and str(region) in TEHRAN_REGIONS:
        return jsonify({
            'region': region,
            'data': TEHRAN_REGIONS[str(region)]
        })
    return jsonify({
        'regions': TEHRAN_REGIONS
    })


def _normalize_accessible_criteria(raw):
    """Map assistant/API values to strict nullable crawler criteria."""
    allowed = {
        'city', 'districts', 'deal_type', 'property_type', 'min_area', 'max_area',
        'rooms', 'min_price', 'max_price', 'min_deposit', 'max_deposit',
        'min_rent', 'max_rent', 'has_parking', 'has_elevator', 'has_warehouse',
        'has_balcony', 'window_hours',
    }
    result = {key: raw.get(key) for key in allowed if key in raw}
    districts = result.get('districts') or raw.get('district') or []
    if isinstance(districts, str):
        districts = [item.strip() for item in districts.split(',') if item.strip()]
    result['districts'] = districts
    result['city'] = result.get('city') or 'tehran'
    if result.get('city') == 'تهران':
        result['city'] = 'tehran'
    if result.get('property_type') in (None, 'residential'):
        result['property_type'] = 'apartment'
    for key in (
        'min_area', 'max_area', 'rooms', 'min_price', 'max_price',
        'min_deposit', 'max_deposit', 'min_rent', 'max_rent', 'window_hours',
    ):
        if result.get(key) in ('', 0, '0'):
            result[key] = None if key != 'window_hours' else 24
    result['window_hours'] = max(1, min(168, int(result.get('window_hours') or 24)))
    return result


@crawler_bp.route('/search-runs', methods=['POST'])
def create_search_run():
    """Start a finite, resumable and auditable accessible-source search."""
    from services.nlp_extractor import PropertyLeadNLPExtractor
    from services.search_run_service import SearchRunService

    data = request.get_json(silent=True) or request.form.to_dict(flat=True)
    query_text = str(data.get('query') or data.get('query_text') or '').strip()
    supplied = data.get('criteria') if isinstance(data.get('criteria'), dict) else {}
    extracted = PropertyLeadNLPExtractor.extract_criteria(query_text) if query_text else {}
    extracted.update(supplied)
    # Explicit top-level fields win over NLP output.
    extracted.update({key: value for key, value in data.items() if key not in {'query', 'query_text', 'criteria', 'start'}})
    criteria = _normalize_accessible_criteria(extracted)
    if criteria.get('deal_type') not in {'sale', 'rent'}:
        return jsonify({
            'success': False,
            'error': 'clarification_required',
            'question': 'قصد خرید دارید یا رهن و اجاره؟',
            'criteria': criteria,
        }), 400

    try:
        run = SearchRunService.create_run(criteria, query_text=query_text)
        should_start = str(data.get('start', 'true')).lower() not in {'false', '0', 'no'}
        if should_start:
            runtime = max(10, min(900, int(data.get('max_runtime_seconds') or 180)))
            SearchRunService.execute_async(current_app._get_current_object(), run.run_id, runtime)
        return jsonify({
            'success': True,
            'run': run.to_dict(),
            'status_url': url_for('crawler.search_run_status', run_id=run.run_id),
            'results_url': url_for('crawler.search_run_view', run_id=run.run_id),
        }), 202 if should_start else 201
    except (TypeError, ValueError) as exc:
        return jsonify({'success': False, 'error': 'invalid_criteria', 'message': str(exc)}), 400


@crawler_bp.route('/search-runs/<run_id>', methods=['GET'])
def search_run_status(run_id):
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    return jsonify({'success': True, 'run': run.to_dict()})


@crawler_bp.route('/search-runs/<run_id>/results', methods=['GET'])
def search_run_results(run_id):
    from services.search_run_service import SearchRunService
    try:
        payload = SearchRunService.paginated_results(
            run_id,
            section=request.args.get('section', 'main'),
            page=request.args.get('page', 1, type=int),
            per_page=request.args.get('per_page', 20, type=int),
        )
        return jsonify({'success': True, **payload})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404


@crawler_bp.route('/search-runs/<run_id>/view', methods=['GET'])
def search_run_view(run_id):
    from services.search_run_service import SearchRunService
    section = request.args.get('section', 'main')
    try:
        payload = SearchRunService.paginated_results(
            run_id,
            section=section,
            page=request.args.get('page', 1, type=int),
            per_page=request.args.get('per_page', 20, type=int),
        )
    except ValueError:
        return ('اجرای جست‌وجو پیدا نشد.', 404)
    return render_template('crawler/search_results.html', **payload)


@crawler_bp.route('/search-runs/<run_id>/resume', methods=['POST'])
def resume_search_run(run_id):
    from services.search_run_service import SearchRunService
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    if run.status == 'running':
        return jsonify({'success': True, 'message': 'اجرا هم‌اکنون در حال پردازش است.', 'run': run.to_dict()})
    if not run.can_resume:
        return jsonify({'success': False, 'message': 'این اجرا به پایان واقعی منبع رسیده و قابل ادامه نیست.'}), 409
    runtime = max(10, min(900, int((request.get_json(silent=True) or {}).get('max_runtime_seconds') or 180)))
    SearchRunService.execute_async(current_app._get_current_object(), run_id, runtime)
    return jsonify({'success': True, 'message': 'ادامهٔ پیمایش از checkpoint آغاز شد.'}), 202


@crawler_bp.route('/listings/<int:listing_id>/publisher-correction', methods=['POST'])
def correct_listing_publisher(listing_id):
    from services.search_run_service import SearchRunService
    data = request.get_json(silent=True) or request.form
    try:
        listing = SearchRunService.apply_manual_correction(
            listing_id,
            str(data.get('category') or ''),
            str(data.get('reason') or ''),
            reviewer=str(data.get('reviewer') or '') or None,
        )
        return jsonify({'success': True, 'listing': listing.to_dict()})
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400

@crawler_bp.route('/search-runs/<run_id>/process-pending', methods=['POST'])
def process_pending_run_classifications(run_id):
    from services.search_run_service import SearchRunService
    run = SearchRun.query.filter_by(run_id=run_id).first_or_404()
    data = request.get_json(silent=True) or {}
    max_items = max(1, min(200, int(data.get('max_items', 50))))
    result = SearchRunService.process_pending_classifications(run_id=run.run_id, max_items=max_items)
    return jsonify({'success': True, 'result': result})


@crawler_bp.route('/start', methods=['POST'])
def start_crawl():
    """Backward-compatible entry point backed by the uncapped resumable core."""
    from services.search_run_service import SearchRunService

    data = request.get_json(silent=True) or request.form
    categories = data.getlist('categories') if hasattr(data, 'getlist') else data.get('categories', ['buy-apartment', 'rent-apartment'])
    city = data.get('city', 'tehran').strip() or 'tehran'
    district = data.get('district', '').strip() or None
    
    # فیلترهای پیشرفته جغرافیایی و مالی
    districts = data.getlist('districts') if hasattr(data, 'getlist') else data.get('districts', [])
    if isinstance(districts, str):
        districts = [d.strip() for d in districts.split(',') if d.strip()]
    if district and district not in districts:
        districts.append(district)

    min_deposit = int(data.get('min_deposit', 0)) if data.get('min_deposit') else None
    max_deposit = int(data.get('max_deposit', 0)) if data.get('max_deposit') else None
    min_rent = int(data.get('min_rent', 0)) if data.get('min_rent') else None
    max_rent = int(data.get('max_rent', 0)) if data.get('max_rent') else None
    min_price = int(data.get('min_price', 0)) if data.get('min_price') else None
    max_price = int(data.get('max_price', 0)) if data.get('max_price') else None
    min_area = int(data.get('min_area', 0)) if data.get('min_area') else None
    max_area = int(data.get('max_area', 0)) if data.get('max_area') else None
    min_year = int(data.get('min_year', 0)) if data.get('min_year') else None

    category_list = categories if isinstance(categories, list) else [categories]
    run_payloads = []
    for category in category_list:
        deal_type = 'rent' if 'rent' in category else 'sale'
        if any(item in category for item in ('commercial', 'office')):
            property_type = 'commercial'
        elif 'villa' in category:
            property_type = 'villa'
        else:
            property_type = 'apartment'
        criteria = _normalize_accessible_criteria({
            'city': city,
            'districts': districts,
            'deal_type': deal_type,
            'property_type': property_type,
            'min_price': min_price,
            'max_price': max_price,
            'min_deposit': min_deposit,
            'max_deposit': max_deposit,
            'min_rent': min_rent,
            'max_rent': max_rent,
            'min_area': min_area,
            'max_area': max_area,
            'window_hours': 24,
        })
        run = SearchRunService.create_run(criteria, query_text='فرم مانیتورینگ کراولر')
        SearchRunService.execute_async(current_app._get_current_object(), run.run_id, 180)
        run_payloads.append({
            'run_id': run.run_id,
            'deal_type': deal_type,
            'results_url': url_for('crawler.search_run_view', run_id=run.run_id),
        })
    return jsonify({
        'success': True,
        'message': 'پیمایش بدون سقف تعداد آغاز شد؛ پیشرفت و پوشش برای ادامه ذخیره می‌شود.',
        'runs': run_payloads,
    }), 202

@crawler_bp.route('/status')
def get_status():
    status = crawler_manager.get_status()
    # Also fetch recent properties count
    total_crawled_in_db = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).count()
    status['stats']['total_in_db'] = total_crawled_in_db
    return jsonify(status)

@crawler_bp.route('/messenger-feed')
def messenger_feed():
    """
    خروجی تمیز و ساختاریافته ویژه پایپ‌لاین پیام‌رسان‌ها (تلگرام، بله، ایتا، واتساپ و پیامک)
    شامل صرفاً آگهی‌های تأییدشده شخصی (مالک مستقیم)
    """
    limit = int(request.args.get('limit', 20))
    deal_type = request.args.get('deal_type')

    query = Property.query.filter_by(is_personal_owner=True)
    if deal_type:
        query = query.filter_by(deal_type=deal_type)

    properties = query.order_by(Property.created_at.desc()).limit(limit).all()
    feed = [p.to_messenger_dict() for p in properties]

    return jsonify({
        'total': len(feed),
        'filter_applied': 'personal_owner_only',
        'items': feed
    })

@crawler_bp.route('/live-items')
def live_items():
    since_id = request.args.get('since_id', 0, type=int)
    new_props = Property.query.filter(
        Property.source.in_(['divar', 'sheypoor']),
        Property.id > since_id
    ).order_by(Property.id.asc()).limit(30).all()

    total_sale = Property.query.filter(Property.source.in_(['divar', 'sheypoor']), Property.deal_type == 'sale').count()
    total_rent = Property.query.filter(Property.source.in_(['divar', 'sheypoor']), Property.deal_type == 'rent').count()
    total_all = total_sale + total_rent

    return jsonify({
        'items': [p.to_dict() for p in new_props],
        'latest_id': new_props[-1].id if new_props else since_id,
        'total_sale': total_sale,
        'total_rent': total_rent,
        'total_all': total_all
    })

@crawler_bp.route('/reset-data', methods=['POST'])
def reset_data():
    from database.db import db
    from database.models import Property, Owner, MatchRecord
    from crawler.dedup import dedup_engine

    try:
        crawled_props = Property.query.filter(Property.source.in_(['divar', 'sheypoor'])).all()
        prop_ids = [p.id for p in crawled_props]
        if prop_ids:
            MatchRecord.query.filter(MatchRecord.property_id.in_(prop_ids)).delete(synchronize_session=False)
            Property.query.filter(Property.id.in_(prop_ids)).delete(synchronize_session=False)

        dedup_engine.clear()
        dedup_engine.initialize_from_db(Property)
        db.session.commit()

        crawler_manager.stats['total_crawled'] = 0
        crawler_manager.stats['new_saved'] = 0
        crawler_manager.stats['duplicates_skipped'] = 0
        crawler_manager.stats['status'] = 'idle'

        return jsonify({
            'success': True,
            'message': f'اطلاعات {len(prop_ids)} فایل کراول‌شده با موفقیت پاک‌سازی شد.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'خطا در پاک‌سازی داده‌ها: {str(e)}'
        }), 500

@crawler_bp.route('/divar-session/status')
def divar_session_status():
    from crawler.divar_session_manager import DivarSessionManager
    return jsonify({
        'authenticated': DivarSessionManager.is_authenticated(),
        'has_token': bool(DivarSessionManager.get_token())
    })


@crawler_bp.route('/divar-session/quota')
def divar_session_quota():
    """دریافت وضعیت سهمیه روزانه و کانال‌های فعال استخراج شماره"""
    from crawler.divar_session_pool import DivarSessionPool
    from crawler.divar_quota_tracker import DivarQuotaTracker
    channels = DivarSessionPool.get_available_channels()
    local_stats = DivarQuotaTracker.get_today_stats('local_session')
    cdp_stats = DivarQuotaTracker.get_today_stats('chrome_cdp')
    return jsonify({
        'channels': channels,
        'local': local_stats,
        'cdp': cdp_stats,
        'total_remaining': sum(c['remaining_quota'] for c in channels if c['is_available'])
    })

@crawler_bp.route('/divar-session/request-code', methods=['POST'])
def divar_session_request_code():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    phone = data.get('phone', '')
    result = DivarSessionManager.request_sms_code(phone)
    return jsonify(result)

@crawler_bp.route('/divar-session/confirm', methods=['POST'])
def divar_session_confirm():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    phone = data.get('phone', '')
    code = data.get('code', '')
    result = DivarSessionManager.confirm_sms_code(phone, code)
    return jsonify(result)

@crawler_bp.route('/divar-session/manual-token', methods=['POST'])
def divar_session_manual_token():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    token = data.get('token', '').strip()
    if not token:
        return jsonify({'success': False, 'message': 'توکن نامعتبر است.'}), 400
    success = DivarSessionManager.save_token(token)
    return jsonify({'success': success, 'message': 'توکن دیوار با موفقیت ذخیره شد.' if success else 'خطا در ذخیره توکن.'})

@crawler_bp.route('/divar-openapi/set-key', methods=['POST'])
def divar_openapi_set_key():
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form
    api_key = data.get('api_key', '').strip()
    if not api_key:
        return jsonify({'success': False, 'message': 'کلید API پلتفرم باز نمی‌تواند خالی باشد.'}), 400
    success = DivarSessionManager.save_open_platform_key(api_key)
    return jsonify({'success': success, 'message': 'کلید OpenAPI دیوار با موفقیت ذخیره شد.' if success else 'خطا در ذخیره کلید.'})


@crawler_bp.route('/divar-session/launch-chrome', methods=['POST'])
def divar_session_launch_chrome():
    """
    راه‌اندازی خودکار Chrome با پورت Debugging 9222 برای کاربر جهت ورود به دیوار
    """
    import subprocess
    import os
    import requests as req_lib

    # بررسی اگر از قبل فعال است
    try:
        r = req_lib.get('http://localhost:9222/json/version', timeout=1)
        if r.status_code == 200:
            return jsonify({
                'success': True,
                'already_running': True,
                'message': 'مرورگر Chrome با پورت دیباگ 9222 فعال است. کافیست در آن وارد divar.ir شوید و سپس دکمه همگام‌سازی را بزنید.'
            })
    except Exception:
        pass

    # یافتن مسیر Chrome در ویندوز
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    chrome_exe = None
    for cp in chrome_paths:
        if os.path.exists(cp):
            chrome_exe = cp
            break

    if not chrome_exe:
        return jsonify({
            'success': False,
            'message': 'مرورگر Google Chrome در سیستم یافت نشد.'
        }), 404

    profile_dir = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\SaghfProfile")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        chrome_exe,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://divar.ir"
    ]
    try:
        subprocess.Popen(cmd)
        return jsonify({
            'success': True,
            'already_running': False,
            'message': 'مرورگر با موفقیت باز شد! وارد حساب دیوار شوید و سپس دکمه همگام‌سازی را بزنید.'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'خطا در اجرای مرورگر: {str(e)}'
        }), 500


@crawler_bp.route('/divar-session/sync-from-cdp', methods=['POST'])
def divar_session_sync_from_cdp():
    """
    استخراج کوکی‌های تازه از Chrome در حال اجرا با پورت debugging
    و بروزرسانی نشست دیوار - نیازی به توکن دستی ندارد
    """
    data = request.get_json(silent=True) or request.form or {}
    cdp_port = int(data.get('port', 9222))

    # تلاش برای اتصال به Chrome CDP
    try:
        import requests as req_lib
        version_resp = req_lib.get(f'http://localhost:{cdp_port}/json/version', timeout=2)
        if version_resp.status_code != 200:
            return jsonify({
                'success': False,
                'message': f'Chrome با پورت debugging {cdp_port} در دسترس نیست. لطفاً run_chrome_debug.bat را اجرا کنید.',
                'instruction': 'run_chrome_debug.bat را اجرا کنید و در Chrome وارد دیوار شوید.',
                'cdp_available': False
            })
    except Exception:
        return jsonify({
            'success': False,
            'message': f'Chrome با پورت debugging {cdp_port} پیدا نشد. لطفاً ابتدا run_chrome_debug.bat را اجرا کنید.',
            'instruction': 'run_chrome_debug.bat را اجرا کنید و در Chrome وارد دیوار شوید.',
            'cdp_available': False
        })

    # استخراج کوکی از Playwright CDP
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f'http://localhost:{cdp_port}')
            contexts = browser.contexts
            if not contexts:
                browser.close()
                return jsonify({'success': False, 'message': 'هیچ context مرورگری یافت نشد. لطفاً یک تب باز کنید.'})

            context = contexts[0]
            cookies_list = context.cookies(['https://divar.ir', 'https://api.divar.ir'])
            browser.close()

        cookies = {c['name']: c['value'] for c in cookies_list if c.get('value')}
        divar_cookies = {k: v for k, v in cookies.items()}

        if not divar_cookies:
            return jsonify({'success': False, 'message': 'کوکی دیوار در Chrome پیدا نشد. لطفاً در Chrome وارد divar.ir شوید.'})

        # بروزرسانی فایل storage_state
        import json
        import os
        storage_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'divar_storage_state.json')
        existing = {}
        if os.path.exists(storage_path):
            try:
                with open(storage_path, encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        existing_map = {c['name']: c for c in existing.get('cookies', [])}
        for cookie in cookies_list:
            existing_map[cookie['name']] = {
                'name': cookie['name'],
                'value': cookie['value'],
                'domain': cookie.get('domain', '.divar.ir'),
                'path': cookie.get('path', '/'),
                'secure': cookie.get('secure', True),
                'expires': cookie.get('expires', -1),
                'httpOnly': cookie.get('httpOnly', False),
                'sameSite': cookie.get('sameSite', 'Lax')
            }
        existing['cookies'] = list(existing_map.values())

        with open(storage_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        has_access_token = 'sAccessToken' in divar_cookies
        return jsonify({
            'success': True,
            'message': f'سشن دیوار با {len(divar_cookies)} کوکی از Chrome بروزرسانی شد.',
            'cookie_count': len(divar_cookies),
            'has_access_token': has_access_token,
            'cookie_names': list(divar_cookies.keys())
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'خطا در استخراج کوکی از Chrome: {str(e)}'
        }), 500


@crawler_bp.route('/divar-session/accounts', methods=['GET'])
def divar_session_accounts():
    """لیست و خلاصه ظرفیت تمام حساب‌های فعال در استخر چنداکانتی"""
    from crawler.divar_account_manager import DivarAccountManager
    return jsonify(DivarAccountManager.get_pool_summary())


@crawler_bp.route('/divar-session/accounts/request-code', methods=['POST'])
def divar_session_account_request_code():
    """ارسال پیامک تایید دیوار برای افزودن سیم‌کارت جدید به استخر"""
    from crawler.divar_session_manager import DivarSessionManager
    data = request.get_json(silent=True) or request.form or {}
    phone = data.get('phone', '').strip()
    return jsonify(DivarSessionManager.request_sms_code(phone))


@crawler_bp.route('/divar-session/accounts/confirm-code', methods=['POST'])
def divar_session_account_confirm_code():
    """تایید کد پیامک و ثبت دائم سیم‌کارت جدید در استخر چرخشی سهمیه"""
    import requests as req_lib
    from crawler.divar_account_manager import DivarAccountManager
    from crawler.divar_session_manager import DivarSessionManager

    data = request.get_json(silent=True) or request.form or {}
    phone = data.get('phone', '').strip()
    code = data.get('code', '').strip()
    label = data.get('label', f'سیم‌کارت {phone}').strip()

    if not phone or not code:
        return jsonify({'success': False, 'message': 'شماره موبایل و کد تایید الزامی است.'}), 400

    url = "https://api.divar.ir/v5/auth/confirm"
    payload = {"phone": phone, "code": code}
    try:
        resp = req_lib.post(url, json=payload, headers=DivarSessionManager.HEADERS, timeout=10)
        if resp.status_code == 200:
            resp_data = resp.json()
            token = resp_data.get('token')
            new_cookies = {c.name: c.value for c in resp.cookies}
            rt = new_cookies.get('refresh_token') or new_cookies.get('sRefreshToken')
            if token:
                new_cookies['sAccessToken'] = token

            success = DivarAccountManager.register_account(
                phone=phone,
                token=token,
                refresh_token=rt,
                cookies=new_cookies,
                label=label
            )
            return jsonify({
                'success': success,
                'message': f'حساب {phone} با موفقیت به استخر اضافه شد! ۲۵ شماره به ظرفیت روزانه افزوده گردید.',
                'pool': DivarAccountManager.get_pool_summary()
            })
        return jsonify({'success': False, 'message': 'کد وارد شده نامعتبر است یا منقضی شده است.'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'خطا در تایید کد: {str(e)}'}), 500


@crawler_bp.route('/divar-session/accounts/remove', methods=['POST'])
def divar_session_account_remove():
    """حذف یک حساب از استخر سهمیه"""
    from crawler.divar_account_manager import DivarAccountManager
    data = request.get_json(silent=True) or request.form or {}
    phone = data.get('phone', '').strip()
    success = DivarAccountManager.remove_account(phone)
    return jsonify({
        'success': success,
        'message': f'حساب {phone} از استخر خارج شد.' if success else 'خطا در حذف حساب.',
        'pool': DivarAccountManager.get_pool_summary()
    })


@crawler_bp.route('/divar-session/test-contact', methods=['POST'])
def divar_session_test_contact():
    """تست استخراج شماره تماس واقعی از یک آگهی دیوار"""
    data = request.get_json(silent=True) or request.form or {}
    token = str(data.get('token', 'gaCP64cf')).strip()

    # پاکسازی توکن
    if '/' in token:
        token = token.rstrip('/').split('/')[-1]
    if token.startswith('divar_'):
        token = token[6:]

    try:
        from crawler.divar_session_manager import DivarSessionManager
        phone = DivarSessionManager.fetch_contact_phone(token)

        if phone:
            return jsonify({
                'success': True,
                'phone': phone,
                'token': token,
                'message': f'شماره واقعی مالک ({phone}) با موفقیت استخراج شد!'
            })
        else:
            # بررسی وضعیت سشن
            cookies = DivarSessionManager.get_cookies_dict()
            import requests as req_lib
            s = req_lib.Session()
            s.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Origin': 'https://divar.ir',
                'Referer': f'https://divar.ir/v/{token}',
            })
            for k, v in cookies.items():
                s.cookies.set(k, v, domain='.divar.ir', path='/')
            resp = s.post(f'https://api.divar.ir/v8/postcontact/web/contact_info_v2/{token}', json={}, timeout=8)
            return jsonify({
                'success': False,
                'token': token,
                'api_status': resp.status_code,
                'api_response': resp.text[:200],
                'message': 'شماره استخراج نشد. سشن نیاز به بروزرسانی دارد.' if resp.status_code in (401, 403) else 'شماره در این آگهی پیدا نشد.'
            })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e), 'token': token}), 500


@crawler_bp.route('/divar-session/extract-phone-jit', methods=['POST'])
def divar_session_extract_phone_jit():
    """
    استخراج آنی و برحسب تقاضا (Just-In-Time) شماره تماس مالک واقعی
    تنها در لحظه درخواست یا کلیک کاربر، با مصرف بهینه سهمیه و اتصال فوری به دیتابیس و CRM
    """
    import logging
    _log = logging.getLogger(__name__)
    from database.db import db
    from database.models import Property, Owner
    from crawler.divar_session_pool import DivarSessionPool

    data = request.get_json(silent=True) or request.form or {}
    property_id = data.get('property_id')
    raw_token = str(data.get('token', '')).strip()

    prop = None
    if property_id:
        try:
            prop = db.session.get(Property, int(property_id))
        except (ValueError, TypeError):
            prop = None

    # ۱. اگر ملک قبلاً شماره داشته باشد، بدون مصرف سهمیه فوراً شماره بازگردانده می‌شود
    if prop and prop.owner and prop.owner.phone_number and prop.owner.phone_number.startswith('09'):
        if not prop.has_verified_phone:
            prop.has_verified_phone = True
            db.session.commit()
        return jsonify({
            'success': True,
            'phone': prop.owner.phone_number,
            'property_id': prop.id,
            'already_extracted': True,
            'message': f'شماره مالک ({prop.owner.phone_number}) از قبل ثبت شده است.'
        })

    # ۲. استخراج توکن دیوار از آدرس یا فیلد source_id ملک
    token = raw_token
    if not token and prop:
        if prop.source_url:
            parts = prop.source_url.rstrip('/').split('/')
            if parts and len(parts[-1]) >= 6:
                token = parts[-1]
        if not token and prop.source_id:
            raw = prop.source_id.replace('divar_', '')
            if len(raw) >= 6:
                token = raw

    if not token:
        return jsonify({'success': False, 'message': 'شناسه آگهی دیوار یافت نشد.'}), 400

    # ۳. استخراج از استخر چندکاناله با انتخاب بهینه‌ترین کانال و کنترل سهمیه
    pool_res = DivarSessionPool.extract_owner_phone(token)

    if pool_res.get('quota_exceeded'):
        return jsonify({
            'success': False,
            'quota_exceeded': True,
            'message': pool_res.get('message', 'سهمیه روزانه استخراج به پایان رسیده است.')
        }), 429

    if pool_res.get('is_chat_only'):
        return jsonify({
            'success': False,
            'is_chat_only': True,
            'token': token,
            'message': 'این آگهی شماره تماس عمومی ندارد و فقط چت دیوار فعال است. سهمیه روزانه مصرف نشد.'
        })

    if pool_res.get('success'):
        normalized = pool_res.get('phone')
        # ۴. ذخیره در جدول Owner و اتصال به Property
        owner_id = None
        if prop and normalized:
            try:
                from crawler.ad_frequency_guard import AdFrequencyGuard
                freq = AdFrequencyGuard.record_ad(
                    phone=normalized,
                    post_token=token,
                    title=prop.title,
                    district=prop.district
                )
                is_broker = freq.get('is_broker', False)

                owner = Owner.query.filter_by(phone_number=normalized).first()
                if not owner:
                    owner = Owner(
                        full_name=prop.title[:50] if prop.title else 'مالک دیوار',
                        phone_number=normalized,
                        notes=f'استخراج آنی JIT ({pool_res.get("channel_used")}) - توکن: {token}'
                    )
                    db.session.add(owner)
                    db.session.flush()
                prop.owner_id = owner.id
                prop.has_verified_phone = True
                if is_broker:
                    prop.is_personal_owner = False
                    prop.owner_type = 'agency'
                    prop.filter_log = freq.get('reason')
                else:
                    prop.is_personal_owner = True
                db.session.commit()
                owner_id = owner.id
            except Exception as ex:
                db.session.rollback()
                _log.error(f"[JIT Extract] خطا در ذخیره دیتابیس: {ex}")

        return jsonify({
            'success': True,
            'phone': normalized,
            'property_id': prop.id if prop else None,
            'owner_id': owner_id,
            'channel': pool_res.get('channel_used'),
            'account': pool_res.get('account_used'),
            'remaining_quota': pool_res.get('remaining_quota'),
            'message': f'شماره واقعی مالک ({normalized}) با موفقیت استخراج شد.'
        })

    return jsonify({
        'success': False,
        'token': token,
        'message': pool_res.get('message', 'استخراج شماره با خطا مواجه شد.')
    })


@crawler_bp.route('/divar-session/batch-extract', methods=['POST'])
def divar_session_batch_extract():
    """
    استخراج batch شماره تماس واقعی برای تمام آگهی‌های مالک شخصی در دیتابیس
    محدوده: حداکثر ۳۰ آگهی از جدیدترین‌ها
    """
    from database.db import db
    from database.models import Property, Owner
    from crawler.divar_session_manager import DivarSessionManager
    from crawler.contact_extractor import ContactExtractor
    import re

    data = request.get_json(silent=True) or {}
    limit = min(50, max(1, int(data.get('limit', 20))))

    # دریافت آگهی‌های مالک شخصی بدون شماره
    props = Property.query.filter(
        Property.is_personal_owner == True,
        Property.source == 'divar',
        Property.source_url.isnot(None)
    ).order_by(Property.created_at.desc()).limit(limit).all()

    results = []
    success_count = 0
    already_have = 0

    for prop in props:
        # چک کردن شماره موجود
        if prop.owner and prop.owner.phone_number:
            already_have += 1
            results.append({
                'id': prop.id,
                'title': (prop.title or '')[:30],
                'status': 'already_exists',
                'phone': prop.owner.phone_number
            })
            continue

        # استخراج توکن از URL
        token = None
        if prop.source_url:
            parts = prop.source_url.rstrip('/').split('/')
            if parts and len(parts[-1]) == 8:
                token = parts[-1]
        if not token and prop.source_id:
            raw = prop.source_id.replace('divar_', '')
            if len(raw) == 8:
                token = raw

        if not token:
            results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'no_token'})
            continue

        # استخراج شماره از استخر نشست‌ها با رعایت سهمیه روزانه
        from crawler.divar_session_pool import DivarSessionPool
        pool_res = DivarSessionPool.extract_owner_phone(token)

        if pool_res.get('quota_exceeded'):
            results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'quota_exceeded', 'message': pool_res.get('message')})
            break  # توقف فوری جهت جلوگیری از مسدودیت حساب

        if pool_res.get('is_chat_only'):
            results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'chat_only', 'message': 'فاقد شماره عمومی - فقط چت دیوار'})
            continue

        if pool_res.get('success'):
            normalized = pool_res.get('phone')
            try:
                owner = Owner.query.filter_by(phone_number=normalized).first()
                if not owner:
                    owner = Owner(
                        full_name=prop.title[:50] if prop.title else 'مالک دیوار',
                        phone_number=normalized,
                        notes=f'استخراج batch ({pool_res.get("channel_used")}) - توکن: {token}'
                    )
                    db.session.add(owner)
                    db.session.flush()
                prop.owner_id = owner.id
                prop.is_personal_owner = True
                db.session.commit()
                success_count += 1
                results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'extracted', 'phone': normalized, 'token': token, 'channel': pool_res.get('channel_used')})
            except Exception as ex:
                db.session.rollback()
                results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'db_error', 'error': str(ex)})
        else:
            results.append({'id': prop.id, 'title': (prop.title or '')[:30], 'status': 'not_found', 'token': token})

    return jsonify({
        'success': True,
        'total_processed': len(props),
        'success_count': success_count,
        'already_have_count': already_have,
        'results': results,
        'message': f'{success_count} شماره واقعی جدید استخراج شد (از {len(props)} آگهی پردازش‌شده)'
    })

# =====================================================================
# Targeted Filter Profiles Management
# =====================================================================

@crawler_bp.route('/profiles', methods=['GET'])
def list_profiles():
    from database.models import FilterProfile
    profiles = FilterProfile.query.order_by(FilterProfile.created_at.desc()).all()
    return jsonify({
        'total': len(profiles),
        'profiles': [p.to_dict() for p in profiles]
    })

@crawler_bp.route('/profiles', methods=['POST'])
def save_profile():
    from database.models import FilterProfile
    from database.db import db
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'نام پروفایل الزامی است.'}), 400

    profile = FilterProfile.query.filter_by(name=name).first()
    if not profile:
        profile = FilterProfile(name=name)
        db.session.add(profile)

    profile.city = data.get('city', 'تهران')
    profile.region = data.get('region', '5')
    districts = data.get('active_districts', ['پونک', 'جنت‌آباد'])
    profile.active_districts = districts if isinstance(districts, list) else [districts]
    profile.deal_type = data.get('deal_type', 'rent')
    profile.min_deposit = int(data.get('min_deposit', 0))
    profile.max_deposit = int(data.get('max_deposit', 0))
    profile.min_rent = int(data.get('min_rent', 0))
    profile.max_rent = int(data.get('max_rent', 0))
    profile.min_price = int(data.get('min_price', 0))
    profile.max_price = int(data.get('max_price', 0))
    profile.min_area = int(data.get('min_area', 0))
    profile.max_area = int(data.get('max_area', 0))
    profile.is_auto_crawl_active = bool(data.get('is_auto_crawl_active', True))

    db.session.commit()
    return jsonify({'success': True, 'profile': profile.to_dict()})

@crawler_bp.route('/profiles/<int:profile_id>/toggle-auto', methods=['POST'])
def toggle_profile_auto(profile_id):
    from database.models import FilterProfile
    from database.db import db
    profile = FilterProfile.query.get_or_404(profile_id)
    profile.is_auto_crawl_active = not profile.is_auto_crawl_active
    db.session.commit()
    return jsonify({
        'success': True,
        'is_auto_crawl_active': profile.is_auto_crawl_active,
        'message': f'وضعیت کراول خودکار برای {profile.name} تغییر یافت.'
    })

@crawler_bp.route('/profiles/<int:profile_id>/run', methods=['POST'])
def run_profile_crawl(profile_id):
    from database.models import FilterProfile
    profile = FilterProfile.query.get_or_404(profile_id)
    cats = ['rent-apartment'] if profile.deal_type == 'rent' else ['buy-apartment']
    districts = profile.active_districts
    district_str = districts[0] if districts else None

    success, msg = crawler_manager.start_crawl_task(
        sources=['divar', 'sheypoor'],
        categories=cats,
        limit_per_cat=10,
        city='tehran',
        district=district_str
    )
    return jsonify({'success': success, 'message': msg, 'profile': profile.name})


# =========================================================================
# پایش زنده و خودکار دیوار (Real-Time Continuous Divar Monitor)
# =========================================================================

@crawler_bp.route('/realtime-monitor/status', methods=['GET'])
def get_realtime_monitor_status():
    from crawler.continuous_monitor import divar_monitor
    status = divar_monitor.get_status()
    return jsonify(status)

@crawler_bp.route('/realtime-monitor/start', methods=['POST'])
def start_realtime_monitor():
    from crawler.continuous_monitor import divar_monitor
    from flask import current_app
    data = request.get_json(silent=True) or request.form or {}
    target_district = data.get('district', 'منطقه ۲ و ۵ تهران')
    
    # استخراج محله‌ها
    districts = data.getlist('districts') if hasattr(data, 'getlist') else data.get('districts', [])
    if isinstance(districts, str):
        districts = [d.strip() for d in districts.split(',') if d.strip()]

    # پارامترهای هدفمند (متراژ، خواب و بازه زمانی ۱۲۰ تا ۱۸۰ ثانیه)
    min_area = int(data.get('min_area')) if data.get('min_area') else None
    max_area = int(data.get('max_area')) if data.get('max_area') else None
    rooms = int(data.get('rooms')) if data.get('rooms') else None
    interval = int(data.get('interval', 150))
    interval = max(60, min(300, interval))

    success = divar_monitor.start(
        app=current_app._get_current_object(),
        target_district=target_district,
        interval_seconds=interval,
        districts=districts if districts else None,
        min_area=min_area,
        max_area=max_area,
        rooms=rooms
    )
    return jsonify({
        'success': success,
        'message': f"پایش زنده دیوار برای {target_district} با موفقیت فعال شد." if success else "خطا در فعال‌سازی پایش زنده.",
        'status': divar_monitor.get_status()
    })

@crawler_bp.route('/realtime-monitor/stop', methods=['POST'])
def stop_realtime_monitor():
    from crawler.continuous_monitor import divar_monitor
    success = divar_monitor.stop()
    return jsonify({
        'success': success,
        'message': "پایش زنده دیوار متوقف شد.",
        'status': divar_monitor.get_status()
    })


@crawler_bp.route('/regional-backfill/start', methods=['POST'])
def start_regional_backfill():
    """شروع استخراج عمیق ۷ روزه مالکین مناطق ۲ و ۵ تهران در پس‌زمینه"""
    import threading
    from crawler.regional_incremental_engine import regional_engine

    def _worker():
        try:
            regional_engine.run_7_day_backfill(max_pages_per_slug=4)
        except Exception as e:
            print(f"[RegionalBackfill] خطا در فرآیند بک‌فیل ۷ روزه: {e}")

    th = threading.Thread(target=_worker, daemon=True, name="Regional7DayBackfill")
    th.start()

    return jsonify({
        'success': True,
        'message': "عملیات استخراج عمیق ۷ روزه مالکین مناطق ۲ و ۵ تهران در پس‌زمینه آغاز شد.",
        'checkpoint': regional_engine.load_checkpoint()
    })


@crawler_bp.route('/regional-checkpoint/status', methods=['GET'])
def get_regional_checkpoint_status():
    """دریافت وضعیت تایم‌بندی، چک‌پوینت و آمار استخراج مناطق ۲ و ۵"""
    from crawler.regional_incremental_engine import regional_engine
    chk = regional_engine.load_checkpoint()
    return jsonify({
        'success': True,
        'checkpoint': chk
    })


@crawler_bp.route('/purge-non-2-5', methods=['POST'])
def purge_non_regions_2_5():
    """پاک‌سازی ۱۰۰٪ قطعی پایگاه داده از هرگونه ملک یا آگهی خارج از مناطق ۲ و ۵ تهران"""
    from crawler.regional_incremental_engine import regional_engine
    res = regional_engine.purge_any_non_region_2_5()
    return jsonify({
        'success': True,
        'message': "پایگاه داده به طور کامل پالایش شد و فقط املاک مناطق ۲ و ۵ حفظ شدند.",
        'result': res
    })


@crawler_bp.route('/divar-status/sync-all', methods=['POST'])
def sync_all_divar_status():
    """استعلام سریع وضعیت زنده‌بودن تمام آگهی‌های دیوار و شناسایی فایل‌های حذف‌شده با تردپول هم‌روند"""
    from crawler.divar_health_watcher import DivarHealthWatcher
    res = DivarHealthWatcher.sync_all_database_listings(max_workers=8)
    return jsonify({
        'success': True,
        'message': f"استعلام سلامت آگهی‌ها به پایان رسید: {res.get('alive')} فعال، {res.get('deleted')} حذف‌شده از دیوار.",
        'metrics': res
    })

