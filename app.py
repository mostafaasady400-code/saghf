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

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    crawler_manager.init_app(app)

    # Register blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(properties_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(matching_bp)
    app.register_blueprint(crm_bp)
    app.register_blueprint(crawler_bp)
    app.register_blueprint(messenger_bp)

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
        pattern = r'https?://[^\s<>"]+'
        def repl(match):
            url = match.group(0)
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer" style="color: #00f2fe; text-decoration: underline; font-weight: 700;">لینک آگهی</a>'
        return re.sub(pattern, repl, str(text))

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
    print("🌐 رابط کاربری Neon Dark Glassmorphism فعال است")
    print("🚀 دسترسی از طریق: http://127.0.0.1:5000")
    print("==================================================")
    app.run(host='127.0.0.1', port=5000, debug=True)
