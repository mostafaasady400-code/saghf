from functools import wraps
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from config import Config
from database.db import db
from database.models import Property, Client, Owner, User
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

def _ensure_super_admin_exists():
    """
    Ensures default Super Admin exists in the database and is synced with Config and Telegram.
    """
    try:
        uname = Config.ADMIN_USERNAME or 'saghf_admin'
        user = User.query.filter((User.username == uname) | (User.role == 'super_admin') | (User.telegram_id == '7495565146')).first()
        if not user:
            user = User(
                username=uname,
                full_name='مدیر ارشد سامانه سقف',
                phone='09120000000',
                telegram_id='7495565146',
                role='super_admin',
                is_active=True,
                notes='حساب پیش‌فرض مدیر ارشد (Super Admin) و توسعه‌دهنده سقف'
            )
            user.set_password(Config.ADMIN_PASSWORD or 'admin123')
            db.session.add(user)
            db.session.commit()
        else:
            if not user.telegram_id:
                user.telegram_id = '7495565146'
            if user.role != 'super_admin':
                user.role = 'super_admin'
            db.session.commit()
    except Exception:
        db.session.rollback()

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('is_admin'):
        return redirect(url_for('admin.dashboard'))

    _ensure_super_admin_exists()

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()

        # 1. Check DB users
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if not user.is_active:
                flash('حساب کاربری شما غیرفعال است. لطفاً با مدیر ارشد تماس حاصل فرمایید.', 'error')
                return render_template('admin/login.html')
            if user.role not in ['super_admin', 'admin']:
                flash('این حساب کاربری دسترسی لازم به پنل مدیریت را ندارد.', 'error')
                return render_template('admin/login.html')

            session['is_admin'] = True
            session['admin_user'] = user.username
            session['user_id'] = user.id
            session['user_role'] = user.role
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash(f'خوش آمدید {user.full_name} ({user.role_title}).', 'success')
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('admin.dashboard'))

        # 2. Fallback to Config credentials
        elif username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD:
            session['is_admin'] = True
            session['admin_user'] = Config.ADMIN_USERNAME
            session['user_role'] = 'super_admin'
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
    session.pop('user_id', None)
    session.pop('user_role', None)
    flash('نشست مدیریت با موفقیت خاتمه یافت.', 'info')
    return redirect(url_for('admin.login'))

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    _ensure_super_admin_exists()

    total_props = Property.query.count()
    sale_props = Property.query.filter_by(deal_type='sale').count()
    rent_props = Property.query.filter_by(deal_type='rent').count()

    divar_props = Property.query.filter_by(source='divar').count()
    sheypoor_props = Property.query.filter_by(source='sheypoor').count()
    direct_props = Property.query.filter_by(source='direct_owner').count()

    total_clients = Client.query.count()
    crawler_status = crawler_manager.get_status()

    # User metrics
    total_users = User.query.count()
    admin_users = User.query.filter(User.role.in_(['super_admin', 'admin'])).count()

    tg_token_set = bool(Config.TELEGRAM_BOT_TOKEN)
    tg_admin_id = Config.ADMIN_TELEGRAM_ID or '7495565146'

    bale_token_set = bool(Config.BALE_BOT_TOKEN)
    bale_admin_id = getattr(Config, 'ADMIN_BALE_ID', '') or Config.ADMIN_TELEGRAM_ID or 'تنظیم نشده در .env'

    divar_auth = DivarSessionManager.is_authenticated()
    recent_properties = Property.query.order_by(Property.created_at.desc()).limit(8).all()
    recent_users = User.query.order_by(User.id.desc()).limit(5).all()

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
        total_users=total_users,
        admin_users=admin_users,
        crawler_status=crawler_status,
        tg_token_set=tg_token_set,
        tg_admin_id=tg_admin_id,
        bale_token_set=bale_token_set,
        bale_admin_id=bale_admin_id,
        divar_auth=divar_auth,
        recent_properties=recent_properties,
        recent_users=recent_users
    )

@admin_bp.route('/health')
@admin_required
def system_health():
    from services.system_health import SystemHealthService
    report = SystemHealthService.get_full_report()
    return render_template(
        'admin/system_health.html',
        admin_user=session.get('admin_user', Config.ADMIN_USERNAME),
        report=report
    )

@admin_bp.route('/health/data')
@admin_required
def system_health_data():
    from services.system_health import SystemHealthService
    report = SystemHealthService.get_full_report()
    return jsonify(report)

# =========================================================================
# User & Admin CRUD Endpoints (Create, Read, Update, Delete)
# =========================================================================

@admin_bp.route('/users', methods=['GET'])
@admin_required
def users_list():
    """
    READ (List & Filter & Search):
    نمایش فهرست کامل کاربران و ادمین‌های سامانه به همراه فیلتر و جستجو
    """
    _ensure_super_admin_exists()

    query_str = (request.args.get('q') or '').strip()
    role_filter = (request.args.get('role') or '').strip()
    status_filter = (request.args.get('status') or '').strip()

    query = User.query

    if query_str:
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        clean_q = query_str.translate(fa_to_en)
        search_pattern = f"%{clean_q}%"
        query = query.filter(
            (User.username.ilike(search_pattern)) |
            (User.full_name.ilike(search_pattern)) |
            (User.phone.ilike(search_pattern)) |
            (User.telegram_id.ilike(search_pattern))
        )

    if role_filter:
        query = query.filter_by(role=role_filter)

    if status_filter:
        if status_filter == 'active':
            query = query.filter_by(is_active=True)
        elif status_filter == 'inactive':
            query = query.filter_by(is_active=False)

    users = query.order_by(User.id.asc()).all()

    # Metrics
    total_users = User.query.count()
    admin_users = User.query.filter(User.role.in_(['super_admin', 'admin'])).count()
    agent_users = User.query.filter_by(role='agent').count()
    active_users = User.query.filter_by(is_active=True).count()

    return render_template(
        'admin/users.html',
        users=users,
        total_users=total_users,
        admin_users=admin_users,
        agent_users=agent_users,
        active_users=active_users,
        query_str=query_str,
        role_filter=role_filter,
        status_filter=status_filter,
        admin_user=session.get('admin_user', Config.ADMIN_USERNAME)
    )

@admin_bp.route('/users/create', methods=['POST'])
@admin_required
def users_create():
    """
    CREATE:
    ایجاد کاربر یا ادمین جدید در دیتابیس و همگام‌سازی خودکار با ربات تلگرام
    """
    try:
        username = (request.form.get('username') or '').strip().lower()
        password = (request.form.get('password') or '').strip()
        full_name = (request.form.get('full_name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        telegram_id = (request.form.get('telegram_id') or '').strip()
        role = (request.form.get('role') or 'admin').strip()
        is_active = request.form.get('is_active') in ['on', '1', 'true', True]
        notes = (request.form.get('notes') or '').strip()

        # Clean digits
        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        if phone:
            phone = ''.join(filter(lambda c: c.isdigit() or c in ['+', '-'], phone.translate(fa_to_en)))
        if telegram_id:
            telegram_id = ''.join(filter(str.isdigit, telegram_id.translate(fa_to_en)))

        if not username or len(username) < 3:
            flash('نام کاربری باید حداقل ۳ کاراکتر انگلیسی باشد.', 'error')
            return redirect(url_for('admin.users_list'))

        if not password or len(password) < 4:
            flash('کلمه عبور باید حداقل ۴ کاراکتر باشد.', 'error')
            return redirect(url_for('admin.users_list'))

        if not full_name:
            flash('وارد کردن نام و نام‌خانوادگی الزامی است.', 'error')
            return redirect(url_for('admin.users_list'))

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash(f'کاربری با نام کاربری «{username}» قبلاً در سیستم ثبت شده است.', 'error')
            return redirect(url_for('admin.users_list'))

        new_user = User(
            username=username,
            full_name=full_name,
            phone=phone,
            telegram_id=telegram_id,
            role=role,
            is_active=is_active,
            notes=notes
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # If admin role and has telegram_id, sync to telegram_admins
        if role in ['super_admin', 'admin'] and telegram_id:
            try:
                from telegram_bot.bot import add_admin_telegram_user
                add_admin_telegram_user(telegram_id, added_by=session.get('admin_user', 'admin'))
            except Exception:
                pass

        flash(f'کاربر جدید «{full_name}» ({new_user.role_title}) با موفقیت ایجاد شد.', 'success')
        return redirect(url_for('admin.users_list'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ایجاد کاربر: {str(e)}', 'error')
        return redirect(url_for('admin.users_list'))

@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def users_detail_api(user_id):
    """
    READ (Single User JSON):
    دریافت مشخصات یک کاربر برای بارگذاری در فرم ویرایش
    """
    user = User.query.get_or_404(user_id)
    return jsonify({
        'success': True,
        'user': user.to_dict()
    })

@admin_bp.route('/users/<int:user_id>/edit', methods=['POST'])
@admin_required
def users_edit(user_id):
    """
    UPDATE:
    به‌روزرسانی مشخصات، نقش و کلمه عبور کاربر در دیتابیس
    """
    user = User.query.get_or_404(user_id)
    try:
        full_name = (request.form.get('full_name') or '').strip()
        password = (request.form.get('password') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        telegram_id = (request.form.get('telegram_id') or '').strip()
        role = (request.form.get('role') or user.role).strip()
        is_active = request.form.get('is_active') in ['on', '1', 'true', True]
        notes = (request.form.get('notes') or '').strip()

        fa_to_en = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        if phone:
            phone = ''.join(filter(lambda c: c.isdigit() or c in ['+', '-'], phone.translate(fa_to_en)))
        if telegram_id:
            telegram_id = ''.join(filter(str.isdigit, telegram_id.translate(fa_to_en)))

        if not full_name:
            flash('نام و نام‌خانوادگی نمی‌تواند خالی باشد.', 'error')
            return redirect(url_for('admin.users_list'))

        old_telegram_id = user.telegram_id
        old_role = user.role

        # Super admin safeguards
        if user.is_super_admin:
            role = 'super_admin'
            is_active = True

        user.full_name = full_name
        user.phone = phone
        user.telegram_id = telegram_id
        user.role = role
        user.is_active = is_active
        user.notes = notes

        if password:
            if len(password) < 4:
                flash('کلمه عبور جدید باید حداقل ۴ کاراکتر باشد.', 'error')
                return redirect(url_for('admin.users_list'))
            user.set_password(password)

        db.session.commit()

        # Sync with Telegram admin storage
        try:
            from telegram_bot.bot import add_admin_telegram_user, remove_admin_telegram_user
            if role in ['super_admin', 'admin'] and telegram_id:
                add_admin_telegram_user(telegram_id, added_by=session.get('admin_user', 'admin'))
            elif old_role in ['super_admin', 'admin'] and role not in ['super_admin', 'admin'] and old_telegram_id:
                remove_admin_telegram_user(old_telegram_id)
        except Exception:
            pass

        flash(f'مشخصات کاربر «{user.full_name}» با موفقیت به‌روزرسانی شد.', 'success')
        return redirect(url_for('admin.users_list'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در ویرایش کاربر: {str(e)}', 'error')
        return redirect(url_for('admin.users_list'))

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def users_delete(user_id):
    """
    DELETE:
    حذف کاربر از پایگاه داده با حفاظت کامل از مدیر ارشد سیستم
    """
    user = User.query.get_or_404(user_id)
    try:
        if user.is_super_admin or user.username == Config.ADMIN_USERNAME or user.telegram_id == '7495565146':
            flash('امکان حذف حساب کاربری مدیر ارشد (Super Admin) وجود ندارد.', 'error')
            return redirect(url_for('admin.users_list'))

        if session.get('user_id') == user.id:
            flash('شما نمی‌توانید حساب کاربری فعال خود را حذف فرمایید.', 'error')
            return redirect(url_for('admin.users_list'))

        # Remove from Telegram bot storage if it was an admin
        if user.telegram_id and user.role in ['super_admin', 'admin']:
            try:
                from telegram_bot.bot import remove_admin_telegram_user
                remove_admin_telegram_user(user.telegram_id)
            except Exception:
                pass

        user_name = user.full_name
        db.session.delete(user)
        db.session.commit()
        flash(f'کاربر «{user_name}» با موفقیت از سیستم حذف گردید.', 'success')
        return redirect(url_for('admin.users_list'))
    except Exception as e:
        db.session.rollback()
        flash(f'خطا در حذف کاربر: {str(e)}', 'error')
        return redirect(url_for('admin.users_list'))

@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def users_toggle_status(user_id):
    """
    UPDATE (Quick Status Toggle):
    تغییر سریع وضعیت فعال/غیرفعال حساب کاربری
    """
    user = User.query.get_or_404(user_id)
    if user.is_super_admin:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'امکان غیرفعال‌سازی مدیر ارشد وجود ندارد.'}), 400
        flash('امکان غیرفعال‌سازی حساب مدیر ارشد وجود ندارد.', 'error')
        return redirect(url_for('admin.users_list'))

    user.is_active = not user.is_active
    db.session.commit()

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': True,
            'is_active': user.is_active,
            'status_label': 'فعال' if user.is_active else 'غیرفعال'
        })

    state_str = "فعال" if user.is_active else "غیرفعال"
    flash(f'وضعیت حساب «{user.full_name}» به {state_str} تغییر یافت.', 'info')
    return redirect(url_for('admin.users_list'))

