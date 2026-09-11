import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'saghf-super-secret-key-2026-neon-dark-glass')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR / 'saghf_database.db'}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Crawler configurations
    DIVAR_BASE_URL = "https://api.divar.ir/v8/web-search"
    SHEYPOOR_BASE_URL = "https://www.sheypoor.com/api/web/v2"
    DEFAULT_CITY = "tehran"
    CRAWLER_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
    ]
    CRAWL_DELAY = 1.5  # Polite delay between calls
