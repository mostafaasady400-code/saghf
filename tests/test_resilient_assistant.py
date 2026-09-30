"""
مجموعه آزمون جامع تاب‌آوری، معماری ترکیبی و پایداری دستیار هوش مصنوعی سقف
پوشش‌دهنده ۱۲ سناریوی کلیدی:
۱. عملکرد عادی مدل اصلی با فراخوانی ابزار
۲. محدودیت درخواست و اتمام اعتبار (HTTP 429 / Quota Exhaustion)
۳. کلید نامعتبر و خطای احراز هویت (Auth Error / 401 / 403)
۴. تایم‌اوت، خطای ۵۰۳ و بازیابی با جیتر
۵. قطع کامل مدل‌های خارجی و کارکرد تضمینی سطح ۴ (Tier 4 Baseline)
۶. اجرای آفلاین کامل بدون نیاز به هیچ کلید API
۷. تداوم و حفظ نیازمندی‌های مشتری (Criteria Persistence) در تغییر مسیر
۸. مکانیزم مدارشکن (Circuit Breaker) و پروب بازیابی (HALF_OPEN -> CLOSED)
۹. مدیریت مکالمات طولانی و فشرده‌سازی زمینه (Context Compaction)
۱۰. ایزولاسیون کامل حافظه دو کاربر و قابلیت پاکسازی (Reset)
۱۱. مدیریت حالت عدم وجود ملک بدون دیتای ماک یا توهم قیمت
۱۲. جلوگیری از ثبت تکراری قرار بازدید با کلید یکتا (Idempotency)
۱۳. آزمون اندپوینت‌های وضعیت (/status) و پاکسازی حافظه (/reset-memory)
"""

import os
import time
import json
import pytest
from unittest.mock import patch, MagicMock

from app import create_app
from database.db import db
from database.models import Property, Client, Visit
from services.assistant.circuit_breaker import CircuitBreaker, CircuitState, ErrorClassifier, ErrorType
from services.assistant.memory_manager import AssistantMemoryManager, SessionMemory, CustomerCriteria
from services.assistant.search_engine import HybridPropertySearchEngine
from services.assistant.gateway import ResilientAIAssistantGateway
from services.voice_agent_service import VoiceAgentService


@pytest.fixture(scope='module')
def app_instance():
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        # اطمینان از وجود حداقل یک ملک نمونه واقعی برای تست‌های دیتابیس
        existing_prop = Property.query.first()
        if not existing_prop:
            prop = Property(
                title="آپارتمان ۱۰۰ متری پونک نوساز",
                deal_type="sale",
                property_type="apartment",
                city="تهران",
                district="پونک",
                total_price=8_000_000_000,
                area=100,
                rooms=2,
                status="available",
                is_personal_owner=True,
                source_url="https://divar.ir/v/test1"
            )
            db.session.add(prop)
            db.session.commit()
        yield app


@pytest.fixture(autouse=True)
def reset_gateway_circuit():
    """پیش از هر تست، مدارشکن گیت‌وی را ریست می‌کنیم"""
    ResilientAIAssistantGateway.reset_circuit()


class TestResilientAssistant:

    def test_01_normal_llm_execution_with_tool_calling(self, app_instance):
        """سناریو ۱: اجرای عادی مدل اصلی با فراخوانی تابع find_properties"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "find_properties",
                            "args": {
                                "deal_type": "sale",
                                "district": "پونک",
                                "max_price": 9_000_000_000,
                                "min_area": 90,
                                "rooms": 2
                            }
                        }
                    }]
                }
            }]
        }

        with app_instance.app_context():
            with patch('requests.post', return_value=mock_response):
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'valid_test_key'}):
                    res = ResilientAIAssistantGateway.process_turn(
                        command="دنبال آپارتمان خرید در پونک تا ۹ میلیارد هستم",
                        session_id="test_sess_normal"
                    )

                    assert res['success'] is True
                    assert res['action'] == 'properties_found'
                    assert res['telemetry']['tier'] in ['primary_llm', 'fallback_llm']
                    assert res['telemetry']['failover_occurred'] is False
                    assert 'پونک' in res['voice_reply']
                    assert 'items' in res
                    assert res['criteria']['deal_type'] == 'sale'

    def test_02_rate_limit_and_quota_exhausted_failover(self, app_instance):
        """سناریو ۲: شبیه‌سازی خطای ۴۲۹ (پایان سهمیه) و جابه‌جایی آنی به لایه پشتیبان بدون چرخه بی‌پایان"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = '{"error": {"code": 429, "message": "Resource has been exhausted (quota exceeded)"}}'

        with app_instance.app_context():
            with patch('requests.post', return_value=mock_response):
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'valid_test_key'}):
                    res = ResilientAIAssistantGateway.process_turn(
                        command="آپارتمان اجاره‌ای پونک",
                        session_id="test_sess_429"
                    )

                    # پاسخ باید با موفقیت از مسیر پشتیبان بازگردد
                    assert res['success'] is True
                    assert res['telemetry']['failover_occurred'] is True
                    assert res['telemetry']['failover_reason'] == 'quota_exhausted'
                    # مدارشکن باید باز (OPEN) شده باشد تا مانع معطلی کاربر در درخواست‌های بعد شود
                    circuit_status = ResilientAIAssistantGateway.get_circuit_status()
                    assert circuit_status['state'] == 'open'

    def test_03_invalid_api_key_auth_error_no_infinite_loop(self, app_instance):
        """سناریو ۳: کلید نامعتبر و توقف قطعی بدون تلاش مجدد بیهوده"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}}'

        with app_instance.app_context():
            with patch('requests.post', return_value=mock_response):
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'bad_key'}):
                    res = ResilientAIAssistantGateway.process_turn(
                        command="سلام، وقت بخیر",
                        session_id="test_sess_bad_key"
                    )

                    assert res['success'] is True
                    assert res['telemetry']['failover_occurred'] is True
                    assert res['telemetry']['failover_reason'] == 'auth_error'
                    # مدارشکن برای خطای دائم کلید فوراً باز می‌شود
                    assert ResilientAIAssistantGateway.get_circuit_status()['state'] == 'open'

    def test_04_service_unavailable_503_and_timeout(self, app_instance):
        """سناریو ۴: خطای ۵۰۳ سرور یا تایم‌اوت و فال‌بک تمیز"""
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = '{"error": {"code": 503, "message": "The service is temporarily unavailable due to high demand."}}'

        with app_instance.app_context():
            with patch('requests.post', return_value=mock_response):
                with patch.dict(os.environ, {'GEMINI_API_KEY': 'test_key'}):
                    res = ResilientAIAssistantGateway.process_turn(
                        command="خرید ملک در پونک",
                        session_id="test_sess_503"
                    )

                    assert res['success'] is True
                    assert res['telemetry']['failover_occurred'] is True
                    assert res['action'] == 'properties_found'

    def test_05_complete_external_outage_tier4_baseline(self, app_instance):
        """سناریو ۵: قطعی ۱۰۰٪ مدل‌های خارجی و کارکرد کامل سطح ۴ (Baseline Rule-Based Engine)"""
        # تنظیم مدار در حالت OPEN تا هیچ درخواستی به اینترنت ارسال نشود
        circuit = ResilientAIAssistantGateway._circuit
        circuit.state = CircuitState.OPEN
        circuit.last_failure_time = time.time()
        circuit.last_error_reason = "simulated_full_outage"

        with app_instance.app_context():
            res = ResilientAIAssistantGateway.process_turn(
                command="خرید آپارتمان در پونک",
                session_id="test_sess_outage"
            )

            assert res['success'] is True
            assert res['telemetry']['tier'] == 'baseline_engine'
            assert res['telemetry']['failover_occurred'] is True
            assert 'items' in res
            assert len(res['items']) > 0
            # تأیید قانون اصالت داده‌ها و تگ لینک آگهی
            for item in res['items']:
                assert 'source_url' in item
                assert item['title'] is not None

    def test_06_pure_offline_zero_api_key_operation(self, app_instance):
        """سناریو ۶: کارکرد کامل دستیار حتی بدون وجود هیچ کلید API در محیط"""
        with app_instance.app_context():
            with patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': ''}):
                res = ResilientAIAssistantGateway.process_turn(
                    command="سلام، قیمت آپارتمان در پونک چنده؟",
                    session_id="test_sess_no_key"
                )

                assert res['success'] is True
                assert res['telemetry']['tier'] in ['baseline_engine', 'local_nlp']
                assert res['telemetry']['failover_reason'] == 'no_api_key_configured'
                assert len(res['voice_reply']) > 10

    def test_07_customer_criteria_persistence_across_tier_failover(self, app_instance):
        """سناریو ۷: حفظ مشخصات مشتری و اصلاحات تدریجی (Delta Updates) هنگام جابه‌جایی مسیر"""
        session_id = "test_sess_delta_flow"
        AssistantMemoryManager.reset_session(session_id)

        with app_instance.app_context():
            # گام ۱: ترن اول در حالت آنلاین (یا سطح پایه)
            with patch.dict(os.environ, {'GEMINI_API_KEY': ''}):
                res1 = ResilientAIAssistantGateway.process_turn(
                    command="من قصد خرید آپارتمان در محله پونک دارم",
                    session_id=session_id
                )
                assert res1['criteria']['deal_type'] == 'sale'
                assert 'پونک' in res1['criteria']['districts']

                # گام ۲: ترن دوم - تغییر بودجه بدون تکرار محله ("بودجه‌ام شد ۱۰ میلیارد، سه خوابه")
                res2 = ResilientAIAssistantGateway.process_turn(
                    command="بودجه‌ام بیشتر شد و تا ۱۰ میلیارد تومان دارم، سه خوابه می‌خوام",
                    session_id=session_id
                )

                # مشخصات قبلی (پونک و خرید) نباید پاک شده باشند
                assert res2['criteria']['deal_type'] == 'sale'
                assert 'پونک' in res2['criteria']['districts']
                assert res2['criteria']['max_budget'] == 10_000_000_000
                assert res2['criteria']['rooms'] == 3

    def test_08_circuit_breaker_recovery_and_probing(self):
        """سناریو ۸: گذار کنترل‌شده مدارشکن از OPEN به HALF_OPEN و بازگشت به CLOSED"""
        cb = CircuitBreaker(name="test_cb", failure_threshold=2, recovery_timeout=0.2)
        err = ErrorClassifier.classify(None, http_status=503, response_text="temporarily unavailable")

        # ثبت ۲ خطا -> باز شدن مدار
        cb.record_failure(err)
        cb.record_failure(err)
        assert cb.state == CircuitState.OPEN
        assert cb.can_attempt() is False

        # شبیه‌سازی گذشت زمان recovery_timeout
        time.sleep(0.25)
        # اکنون باید اجازه یک درخواست کاوشگر در حالت HALF_OPEN را بدهد
        assert cb.can_attempt() is True
        assert cb.state == CircuitState.HALF_OPEN

        # ثبت موفقیت درخواست کاوشگر -> بازگشت مدار به حالت سالم (CLOSED)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_09_long_conversation_context_compaction(self):
        """سناریو ۹: مدیریت مکالمات طولانی و جلوگیری از سرریز کانتکست با فشرده‌سازی خودکار"""
        sess = SessionMemory(session_id="test_sess_long", max_history_turns=10)

        # اضافه کردن ۱۶ ترن مکالمه
        for i in range(16):
            sess.add_turn('user', f"سوال ملکی کاربر شماره {i}")
            sess.add_turn('assistant', f"پاسخ مشاور شماره {i}")

        # تاریخچه زنده نباید بیش از سقف (۱۰ ترن) باشد
        assert len(sess.history) <= 10
        # خلاصه زمینه باید تولید شده باشد
        assert len(sess.summary_note) > 0

    def test_10_session_isolation_and_reset(self):
        """سناریو ۱۰: ایزولاسیون کامل حافظه دو کاربر و تضمین عدم نشت داده"""
        sess_a = AssistantMemoryManager.get_or_create("user_alpha")
        sess_b = AssistantMemoryManager.get_or_create("user_beta")

        sess_a.criteria.update_delta({'deal_type': 'sale', 'districts': ['نیاوران'], 'max_budget': 30_000_000_000})
        sess_b.criteria.update_delta({'deal_type': 'rent', 'districts': ['پونک'], 'max_deposit': 500_000_000})

        # اطلاعات دو کاربر نباید مخلوط شوند
        assert sess_a.criteria.deal_type == 'sale'
        assert sess_a.criteria.districts == ['نیاوران']
        assert sess_b.criteria.deal_type == 'rent'
        assert sess_b.criteria.districts == ['پونک']

        # پاکسازی نشست الف
        AssistantMemoryManager.reset_session("user_alpha")
        assert sess_a.criteria.deal_type == 'any'
        assert sess_a.criteria.districts == []
        # نشست ب باید دست‌نخورده باقی بماند
        assert sess_b.criteria.deal_type == 'rent'
        assert sess_b.criteria.districts == ['پونک']

    def test_11_no_matching_property_zero_mock_no_hallucination(self, app_instance):
        """سناریو ۱۱: عدم وجود ملک با شرایط نامتعارف بدون تولید داده یا قیمت ساختگی"""
        with app_instance.app_context():
            criteria = CustomerCriteria(
                deal_type="sale",
                districts=["زعفرانیه"],
                max_budget=50_000_000, # بودجه غیرممکن ۵۰ میلیون تومانی در زعفرانیه
                min_area=300
            )
            search_res = HybridPropertySearchEngine.search(criteria)

            # نباید هیچ فایل ساختگی یا جعلی با قیمت ۵۰ میلیون تولید شده باشد
            assert search_res['count'] == 0
            assert len(search_res['items']) == 0

    def test_12_idempotency_prevents_duplicate_visit_scheduling(self, app_instance):
        """سناریو ۱۲: جلوگیری از ثبت تکراری قرار بازدید با کلید یکتا (Idempotency)"""
        with app_instance.app_context():
            session = AssistantMemoryManager.get_or_create("test_idempotent_sess")
            session.reset()

            prop = Property.query.first()
            assert prop is not None

            test_phone = f"0999{int(time.time()) % 10000000:07d}"
            # پاکسازی هرگونه رکورد آزمایشی قبلی
            existing_c = Client.query.filter_by(phone_number=test_phone).first()
            if existing_c:
                Visit.query.filter_by(client_id=existing_c.id).delete()
                db.session.delete(existing_c)
                db.session.commit()

            visit_params = {
                'property_id': prop.id,
                'client_name': 'متقاضی آزمایشی',
                'client_phone': test_phone,
                'preferred_time': 'فردا ساعت ۱۸'
            }

            # بار اول: ثبت موفقیت‌آمیز
            first_res = ResilientAIAssistantGateway._execute_idempotent_visit_schedule(visit_params, session)
            assert first_res['success'] is True
            assert first_res.get('already_scheduled') is not True

            # بار دوم: تلاش مجدد یا تغییر مسیر نباید رکورد دوم ایجاد کند
            second_res = ResilientAIAssistantGateway._execute_idempotent_visit_schedule(visit_params, session)
            assert second_res['success'] is True
            assert second_res.get('already_scheduled') is True
            assert 'پیش‌تر' in second_res['message']

    def test_13_api_status_and_reset_endpoints(self, app_instance):
        """سناریو ۱۳: صحت عملکرد اندپوینت‌های وضعیت سلامت و ریست حافظه در وب‌سرویس"""
        client = app_instance.test_client()

        # ۱. تست استعلام وضعیت مدار و مدل‌ها
        status_resp = client.get('/api/ai-orb/status')
        assert status_resp.status_code == 200
        sdata = status_resp.get_json()
        assert sdata['success'] is True
        assert 'circuit' in sdata
        assert 'active_sessions_count' in sdata

        # ۲. تست بازنشانی حافظه
        reset_resp = client.post('/api/ai-orb/reset-memory', json={'session_id': 'sess_to_clear'})
        assert reset_resp.status_code == 200
        rdata = reset_resp.get_json()
        assert rdata['success'] is True
        assert rdata['session_id'] == 'sess_to_clear'
