from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
from database.db import db
from database.models import Property, Client, Owner
from crawler.crawler_manager import crawler_manager
from crawler.divar_session_manager import DivarSessionManager

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('جهت دسترسی به این بخش، لطفاً ابتدا وارد حساب مدیریت شوید.', 'warning')
            return redirect(url_for('admin.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('is_admin'):
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        if username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session['is_admin'] = True
            session['admin_user'] = Config.ADMIN_USERNAME
            flash(f'خوش آمدید مدیر ارشد {Config.ADMIN_USERNAME}. نشست مدیریت با موفقیت برقرار شد.', 'success')
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('admin.dashboard'))
        else:
            flash('نام کاربری یا کلمه عبور مدیر اشتباه است. دسترسی رد شد.', 'error')

    return render_template('admin/login.html')

@admin_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('is_admin', None)
    session.pop('admin_user', None)
    flash('نشست مدیریت با موفقیت خاتمه یافت.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    total_props = Property.query.count()
    sale_props = Property.query.filter_by(deal_type='sale').count()
    rent_props = Property.query.filter_by(deal_type='rent').count()

    divar_props = Property.query.filter_by(source='divar').count()
    sheypoor_props = Property.query.filter_by(source='sheypoor').count()
    direct_props = Property.query.filter_by(source='direct_owner').count()

    total_clients = Client.query.count()
    crawler_status = crawler_manager.get_status()

    tg_token_set = bool(Config.TELEGRAM_BOT_TOKEN)
    tg_admin_id = Config.ADMIN_TELEGRAM_ID or 'تنظیم نشده در .env'

    divar_auth = DivarSessionManager.is_authenticated()

    recent_properties = Property.query.order_by(Property.created_at.desc()).limit(8).all()

    return render_template(
        'admin/dashboard.html',
        admin_user=session.get('admin_user', Config.ADMIN_USERNAME),
        total_props=total_props,
        sale_props=sale_props,
        rent_props=rent_props,
        divar_props=divar_props,
        sheypoor_props=sheypoor_props,
        direct_props=direct_props,
        total_clients=total_clients,
        crawler_status=crawler_status,
        tg_token_set=tg_token_set,
        tg_admin_id=tg_admin_id,
        divar_auth=divar_auth,
        recent_properties=recent_properties
    )
