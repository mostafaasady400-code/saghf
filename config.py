import os
import warnings
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / '.env')


class Config:
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development').lower()
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('1', 'true') if FLASK_ENV == 'production' else os.environ.get('DEBUG', 'True').lower() in ('1', 'true')
    
    # Secret key configuration:
    # 1. Read from environment variable (.env)
    # 2. In development mode, provide a secure development-only fallback key
    # 3. In production mode, strictly require SECRET_KEY to prevent vulnerabilities
    _env_secret = os.environ.get('SECRET_KEY')
    if _env_secret:
        SECRET_KEY = _env_secret
    elif FLASK_ENV in ('development', 'dev', 'testing', 'test'):
        SECRET_KEY = 'dev-saghf-secret-key-fallback-only-for-local-development'
        warnings.warn(
            "⚠️ [Security Notice] SECRET_KEY is not set in environment; using a default development key. "
            "Please configure SECRET_KEY in your .env file for production.",
            UserWarning
        )
    else:
        raise RuntimeError(
            "🔴 CRITICAL SECURITY ERROR: SECRET_KEY is not configured in the environment. "
            "Running in production without a secure SECRET_KEY is strictly forbidden. "
            "Please add SECRET_KEY to your .env or environment variables."
        )

    _db_url = os.environ.get('DATABASE_URL')
    if _db_url and _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = _db_url or f"sqlite:///{BASE_DIR / 'saghf_database.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    if SQLALCHEMY_DATABASE_URI.startswith('postgresql'):
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_size': 10,
            'max_overflow': 20,
            'pool_pre_ping': True,
            'pool_recycle': 300
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {}

    # CSRF Protection settings
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'True').lower() in ('1', 'true', 'yes')
    WTF_CSRF_TIME_LIMIT = 3600  # Token valid for 1 hour
    WTF_CSRF_HEADERS = ['X-CSRFToken', 'X-CSRF-Token']

    # Super Admin Access & Telegram Authorization Settings
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'saghf_admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', os.environ.get('ADMIN_DEFAULT_PASSWORD', 'SaghfSuperAdmin#2026!'))
    ADMIN_TELEGRAM_ID = os.environ.get('ADMIN_TELEGRAM_ID', '').strip()
    ADMIN_DEFAULT_PASSWORD = ADMIN_PASSWORD
    ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY', '')

    # Telegram Bot Configurations (Reads strictly from environment)
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID', '')
    TELEGRAM_WEBHOOK_URL = os.environ.get('TELEGRAM_WEBHOOK_URL', '')

    # Bale Bot Configurations (Domestic Messenger)
    BALE_BOT_TOKEN = os.environ.get('BALE_BOT_TOKEN', '')
    BALE_CHANNEL_ID = os.environ.get('BALE_CHANNEL_ID', '')
    BALE_WEBHOOK_URL = os.environ.get('BALE_WEBHOOK_URL', '')
    ADMIN_BALE_ID = os.environ.get('ADMIN_BALE_ID', '').strip()
    
    # Crawler configurations
    DIVAR_OPEN_PLATFORM_POST_URL = os.environ.get(
        'DIVAR_OPEN_PLATFORM_POST_URL',
        'https://open-api.divar.ir/v2/open-platform/finder/post'
    )
    DIVAR_BASE_URL = "https://api.divar.ir/v8/web-search"
    DIVAR_API_KEY = os.environ.get('DIVAR_API_KEY', '')
    DIVAR_AUTH_TOKEN = os.environ.get('DIVAR_AUTH_TOKEN', '')
    SHEYPOOR_BASE_URL = "https://www.sheypoor.com/api/web/v2"
    DEFAULT_CITY = "tehran"
    CRAWLER_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ]
    CRAWL_DELAY = 1.5  # Polite delay between calls

