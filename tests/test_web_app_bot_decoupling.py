import pytest
from app import create_app
from database.db import db
from database.models import Property, Owner

def test_web_app_boots_completely_isolated(monkeypatch):
    """
    تست استقلال کامل وب‌اپ از ربات‌های تلگرام و بله
    وب‌اپ باید بدون نیاز به اجرای بات، بدون توکن تلگرام و بله، به صورت کاملاً مستقل لود شود.
    """
    monkeypatch.setattr("config.Config.TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr("config.Config.BALE_BOT_TOKEN", "")
    
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        # 1. صفحه اصلی و داشبورد
        resp = client.get('/')
        assert resp.status_code in [200, 302]

        # 2. اندپوینت لیست املاک
        resp = client.get('/properties/')
        assert resp.status_code == 200

        # 3. اندپوینت احراز هویت وب
        resp = client.get('/auth/login')
        assert resp.status_code == 200

        # 4. اندپوینت وضعیت تلگرام وب‌سرویس باید بدون کرش unconfigured برگرداند
        resp = client.get('/api/telegram/status')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('configured') is False

def test_omnichannel_engine_resilient_without_bots(monkeypatch):
    """
    تست انعطاف‌پذیری موتور چندکاناله در صورت در دسترس نبودن یا خطای بات‌ها
    """
    from services.omnichannel_engine import OmniChannelEngine
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        # فراخوانی متد با متن ورودی جدید
        res = OmniChannelEngine.ingest_interaction(
            channel="web",
            sender_id="web_visitor_99",
            text="سلام آپارتمان ۱۰۰ متری برای اجاره در سعادت آباد می‌خواهم"
        )
        assert res.get('success') is True
        assert res.get('channel') == "web"
