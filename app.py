import os
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from flask import Flask
from config import Config
from database.db import db
from crawler.crawler_manager import crawler_manager

# Import Blueprints
from routes.dashboard import dashboard_bp
from routes.properties import properties_bp
from routes.clients import clients_bp
from routes.matching import matching_bp
from routes.crm import crm_bp
from routes.crawler_api import crawler_bp
from routes.messenger_api import messenger_bp
from routes.telegram_api import telegram_bp
from routes.bale_api import bale_bp
from routes.admin import admin_bp
from routes.telephony_api import telephony_bp
from routes.n8n_gateway import n8n_bp
from flask_wtf.csrf import CSRFProtect, CSRFError

csrf = CSRFProtect()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    crawler_manager.init_app(app)

    # Exempt Telegram, Bale, Telephony webhooks and AI/JSON APIs from CSRF protection
    csrf.exempt(telegram_bp)
    csrf.exempt(bale_bp)
    csrf.exempt(messenger_bp)
    csrf.exempt(telephony_bp)
    csrf.exempt(n8n_bp)
    from routes.properties import api_ai_voice_search, api_on_demand_search, api_voice_turn
    from routes.crm import api_sales_assistant_onboard, api_sales_assistant_turn, api_sales_assistant_feedback
    csrf.exempt(api_ai_voice_search)
    csrf.exempt(api_on_demand_search)
    csrf.exempt(api_voice_turn)
    csrf.exempt(api_sales_assistant_onboard)
    csrf.exempt(api_sales_assistant_turn)
    csrf.exempt(api_sales_assistant_feedback)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        from flask import jsonify, request
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.path.startswith(('/api/', '/crawler/', '/matching/', '/properties/')):
            return jsonify({
                'success': False,
                'error': 'CSRF_FAILED',
                'message': 'اعتبارسنجی توکن امنیتی (CSRF) ناموفق بود. لطفاً صفحه را تازه‌سازی کنید.'
            }), 400
        return '<div style="text-align: center; padding: 3rem; font-family: sans-serif; direction: rtl; color: #f43f5e;"><h3>خطای امنیتی CSRF: توکن نامعتبر یا منقضی شده است.</h3><p>لطفاً به صفحه قبل بازگشته و مجدداً صفحه را بارگذاری فرمایید.</p><a href="javascript:history.back()" style="color: #38bdf8;">بازگشت</a></div>', 400

    # Register blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(matching_bp)
    app.register_blueprint(crm_bp)
    app.register_blueprint(crawler_bp)
    app.register_blueprint(messenger_bp)
    app.register_blueprint(telegram_bp)
    app.register_blueprint(bale_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(telephony_bp)
    app.register_blueprint(n8n_bp)

    @app.route('/api/health', methods=['GET'])
    @csrf.exempt
    def api_health():
        from datetime import datetime
        from flask import jsonify
        from services.system_health import SystemHealthService
        uptime = SystemHealthService.get_uptime_seconds()
        db_stat = SystemHealthService.get_database_health()
        bots_stat = SystemHealthService.get_bots_health()
        crawler_stat = SystemHealthService.get_crawler_health()
        status = 'healthy' if (db_stat['status'] == 'healthy' and bots_stat['status'] != 'critical' and crawler_stat['status'] == 'healthy') else 'degraded'
        return jsonify({
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'uptime_seconds': uptime,
            'services': {
                'database': db_stat['status'],
                'telegram_bot': 'online' if bots_stat['telegram']['healthy'] else 'offline',
                'bale_bot': 'online' if bots_stat['bale']['healthy'] else 'offline',
                'bot_runner_process': 'running' if bots_stat['process_runner']['active'] else 'stopped',
                'crawler_tier1': 'ready' if crawler_stat['tier1_tls_impersonator']['available'] else 'unavailable'
            }
        })

    @app.route('/api/health/detailed', methods=['GET'])
    @csrf.exempt
    def api_health_detailed():
        from flask import jsonify
        from services.system_health import SystemHealthService
        report = SystemHealthService.get_full_report()
        return jsonify(report)

    @app.route('/assets/<path:filename>')
    def serve_assets(filename):
        from flask import send_from_directory
        assets_dir = os.path.join(app.root_path, 'static', 'assets')
        if os.path.exists(os.path.join(assets_dir, filename)):
            return send_from_directory(assets_dir, filename)
        return send_from_directory(os.path.join(app.root_path, 'static'), filename)

    @app.context_processor
    def inject_global_stats():
        try:
            from database.models import Property
            from datetime import datetime, timedelta
            cutoff = datetime.utcnow() - timedelta(days=7)
            expired_count = Property.query.filter(
                (Property.created_at < cutoff) | (Property.status == 'needs_followup'),
                Property.status.notin_(['archived', 'sold'])
            ).count()
            return {'expired_properties_count': expired_count}
        except Exception:
            return {'expired_properties_count': 0}

    # Jinja Filters
    @app.template_filter('toman')
    def format_toman(val):
        if not val or val == 0:
            return 'توافقی'
        try:
            val = int(val)
            if val >= 1_000_000_000:
                billions = val / 1_000_000_000
                if billions.is_integer():
                    return f"{int(billions)} میلیارد تومان"
                return f"{billions:.1f} میلیارد تومان"
            elif val >= 1_000_000:
                millions = val / 1_000_000
                if millions.is_integer():
                    return f"{int(millions)} میلیون تومان"
                return f"{millions:.1f} میلیون تومان"
            return f"{val:,} تومان"
        except Exception:
            return str(val)

    @app.template_filter('pnum')
    def to_persian_num(val):
        if val is None:
            return ''
        fa_digits = '۰۱۲۳۴۵۶۷۸۹'
        en_digits = '0123456789'
        trans = str.maketrans(en_digits, fa_digits)
        return str(val).translate(trans)

    @app.template_filter('deal_name')
    def deal_name_filter(deal_type):
        mapping = {
            'sale': 'فروش',
            'rent': 'رهن و اجاره'
        }
        return mapping.get(deal_type, deal_type)

    @app.template_filter('lead_name')
    def lead_name_filter(status):
        mapping = {
            'new': 'سرنخ جدید',
            'contacted': 'تماس اولیه',
            'visiting': 'هماهنگی بازدید',
            'negotiating': 'در حال مذاکره',
            'contract_won': 'عقد قرارداد (موفق)',
            'lost': 'انصرافی / ناموفق'
        }
        return mapping.get(status, status)

    @app.template_filter('linkify_ad')
    def linkify_ad_filter(text):
        if not text:
            return ''
        import re
        from markupsafe import Markup, escape

        # 1. Escape all raw text securely so no HTML/script tags can be injected
        escaped_text = str(escape(text))

        # 2. Match URLs inside the already-escaped text
        pattern = r'https?://[^\s<>"]+'
        def repl(match):
            raw_url = match.group(0)
            if raw_url.startswith(('http://', 'https://')):
                safe_url = str(escape(raw_url))
                return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" style="color: var(--gold-light); text-decoration: underline; font-weight: 700;">لینک آگهی</a>'
            return raw_url

        linkified = re.sub(pattern, repl, escaped_text)
        return Markup(linkified)


    @app.template_filter('time_ago')
    def persian_time_ago(dt):
        if not dt:
            return 'نامشخص'
        from datetime import datetime
        now = datetime.utcnow()
        if dt > now:
            return 'لحظاتی پیش'
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return 'لحظاتی پیش'
        minutes = seconds // 60
        if minutes == 30:
            return 'نیم ساعت پیش'
        elif minutes < 60:
            return f"{to_persian_num(minutes)} دقیقه پیش"
        hours = seconds // 3600
        if hours == 1:
            return 'یک ساعت پیش'
        elif hours < 24:
            return f"{to_persian_num(hours)} ساعت پیش"
        days = diff.days
        if days == 1:
            return 'دیروز'
        elif days < 7:
            return f"{to_persian_num(days)} روز پیش"
        weeks = days // 7
        if weeks < 4:
            return f"{to_persian_num(weeks)} هفته پیش"
        months = days // 30
        return f"{to_persian_num(months)} ماه پیش"

    with app.app_context():
        db.create_all()

    return app

app = create_app()

if __name__ == '__main__':
    print("==================================================")
    print("✨ سامانه جامع مدیریت و فایلینگ املاک سقف (Saghf CRM)")
    print("⚜️ رابط کاربری Black & Gold Luxury با موشن‌های سه‌بعدی فعال است")
    print("🚀 دسترسی عمومی: http://127.0.0.1:5000")
    print("--------------------------------------------------")
    print("👑 مشخصات حساب Super Admin سامانه:")
    print(f"👤 نام کاربری: {Config.ADMIN_USERNAME}")
    print(f"🔑 گذرواژه:   {Config.ADMIN_PASSWORD}")
    print("🌐 ورود به پنل مدیریت: http://127.0.0.1:5000/admin/login")
    print(f"🤖 شناسه ادمین تلگرام: {Config.ADMIN_TELEGRAM_ID or 'تعریف نشده در .env'}")
    print("==================================================")
    app.run(host='127.0.0.1', port=5000, debug=True)
