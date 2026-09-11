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
