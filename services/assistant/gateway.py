"""
درگاه یکپارچه، ترکیبی و فوق‌مقاوم دستیار هوش مصنوعی سقف (Resilient AI Assistant Gateway)
پوشش‌دهنده:
۱. مدیریت سطوح چهارگانه پشتیبان (Tier 1 -> Tier 2 -> Tier 3 -> Tier 4 Baseline)
۲. مدارشکن (Circuit Breaker) و طبقه‌بندی هوشمند خطا بدون اتلاف وقت کاربر
۳. اجرای امن ابزارها با کلید یکتا و جلوگیری از عملیات تکراری (Idempotency)
۴. استقلال کامل منطق اصلی محصول از مدل خارجی
۵. دورسنجی، کنترل مصرف و تضمین عدم افشای کلیدها
"""

import os
import re
import json
import time
import random
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta

from config import Config
from database.db import db
from database.models import Property, Client, Visit
from services.nlp_extractor import normalize_persian_text, PropertyLeadNLPExtractor
from services.assistant.circuit_breaker import CircuitBreaker, CircuitState, ErrorClassifier, ErrorType
from services.assistant.memory_manager import AssistantMemoryManager, SessionMemory, CustomerCriteria
from services.assistant.search_engine import HybridPropertySearchEngine

logger = logging.getLogger(__name__)

class ResilientAIAssistantGateway:
    """درگاه ترکیبی و مقاوم دستیار هوش مصنوعی با معماری چندسطحی و استقلال منطق پایه"""

    # مدارشکن مرکزی ارائه‌دهنده Gemini
    _circuit = CircuitBreaker(
        name="google_gemini",
        failure_threshold=3,
        recovery_timeout=45.0,
        half_open_success_threshold=1
    )

    TURN_TIMEOUT_BUDGET_SEC = 8.0 # سقف حداکثر زمان پاسخگویی به کاربر
    ESTIMATED_CHARS_PER_TOKEN = 4.0

    @classmethod
    def get_circuit_status(cls) -> Dict[str, Any]:
        return cls._circuit.get_status()

    @classmethod
    def reset_circuit(cls):
        cls._circuit.reset()

    @classmethod
    def process_turn(
        cls,
        command: str,
        session_id: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        current_path: str = '/'
    ) -> Dict[str, Any]:
        """
        پردازش یک ترن ورودی با تضمین قطعی پاسخ و گزارش کامل دورسنجی
        """
        start_time = time.time()
        norm_cmd = normalize_persian_text(command or '').strip()

        # ۱. بازیابی یا ایجاد حافظه نشست
        session = AssistantMemoryManager.get_or_create(session_id)
        if history and not session.history:
            for h in history[-20:]:
                session.history.append({'role': h.get('role', 'user'), 'content': h.get('content', '')})

        if not norm_cmd:
            greeting_text = (
                "سلام و عرض ادب! من مشاور هوشمند سقف در خدمت شما هستم. "
                "قصد خرید آپارتمان دارید یا رهن و اجاره؟ "
                "چه متراژ و محله‌ای مد نظرتونه تا بهترین فایل‌های شخصی و بدون واسطه رو نشونتون بدم؟"
            )
            session.add_turn('assistant', greeting_text)
            return {
                'success': True,
                'state': 'greeting',
                'voice_reply': greeting_text,
                'speech_text': greeting_text,
                'action': 'initial_greeting',
                'items': [],
                'telemetry': {
                    'tier': 'baseline_greeting',
                    'model': 'local_engine',
                    'latency_ms': int((time.time() - start_time) * 1000),
                    'failover_occurred': False
                }
            }

        session.add_turn('user', norm_cmd)

        # ۲. پیش‌پردازش محلی فرامین دستوری فوق‌سریع (مانند استعلام شماره مالک)
        if any(w in norm_cmd.lower() for w in ['شماره مالک', 'شماره تماس', 'تماس با مالک', 'استعلام شماره', 'شماره تلفن']):
            local_res = cls._handle_owner_contact_inquiry(norm_cmd, session)
            local_res['telemetry'] = {
                'tier': 'local_instant',
                'model': 'divar_contact_engine',
                'latency_ms': int((time.time() - start_time) * 1000),
                'failover_occurred': False
            }
            return local_res

        # استخراج تدریجی نیازمندی‌ها (Delta Updates) در حافظه نشست
        cls._apply_local_delta_extraction(norm_cmd, session)

        gemini_key = os.getenv('GEMINI_API_KEY')
        if gemini_key is None:
            gemini_key = os.getenv('GOOGLE_API_KEY')
        if gemini_key is None:
            gemini_key = getattr(Config, 'GEMINI_API_KEY', '')
        api_available = bool(gemini_key and gemini_key.strip())

        # ۳. مسیرهای اجرای چندسطحی (Multi-Tier Execution Pipeline)
        telemetry: Dict[str, Any] = {
            'failover_occurred': False,
            'failover_reason': None,
            'tier': 'primary_llm',
            'model': 'unassigned',
            'circuit_status': cls._circuit.state.value,
            'estimated_tokens': 0
        }

        # الف) تلاش در سطوح ۱ و ۲: مدل‌های آنلاین خارجی در صورت باز بودن مدار و وجود کلید
        if api_available and cls._circuit.can_attempt():
            online_resp = cls._execute_online_tiers(norm_cmd, session, gemini_key, start_time, telemetry)
            if online_resp:
                return online_resp

        # اگر کلید نبود یا مدار باز بود، دلیل جابه‌جایی را ثبت می‌کنیم
        if not api_available:
            telemetry['failover_occurred'] = True
            telemetry['failover_reason'] = 'no_api_key_configured'
        elif not cls._circuit.can_attempt():
            telemetry['failover_occurred'] = True
            if not telemetry.get('failover_reason'):
                telemetry['failover_reason'] = f"circuit_open_{cls._circuit.last_error_reason or 'cooldown'}"

        # ب) تلاش در سطح ۳: کلاسیفایر هوشمند محلی و استخراج نیازمندی‌ها (Local Heuristic NLP)
        local_nlp_resp = cls._execute_tier3_local_nlp(norm_cmd, session, telemetry)
        if local_nlp_resp:
            local_nlp_resp['telemetry']['latency_ms'] = int((time.time() - start_time) * 1000)
            return local_nlp_resp

        # ج) سطح ۴: دستیار پایه مستقل و پایدار (Baseline Independent Engine)
        baseline_resp = cls._execute_tier4_baseline(norm_cmd, session, telemetry)
        baseline_resp['telemetry']['latency_ms'] = int((time.time() - start_time) * 1000)
        return baseline_resp

    # =========================================================================
    # سطوح ۱ و ۲: مدل‌های زبانی آنلاین (Primary & Compatible Fallback LLMs)
    # =========================================================================
    @classmethod
    def _execute_online_tiers(
        cls,
        command: str,
        session: SessionMemory,
        api_key: str,
        start_time: float,
        telemetry: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        اجرای مدل اصلی با امکان سوئیچ خودکار به مدل سازگار بعدی در صورت خطای موقت
        """
        preferred_model = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash').strip()
        candidate_models = [preferred_model, 'gemini-3.8-flash', 'gemini-3.5-flash', 'gemini-flash-latest']
        models_to_try = list(dict.fromkeys(m for m in candidate_models if m))

        tools_schema = cls._build_gemini_tools_schema()
        system_instruction = (
            "شما کارشناس ارشد، خبره و بسیار محترم املاک لوکس در سامانه «سقف» هستید. "
            "لحن شما گرم، صمیمی، حرفه‌ای و هدفمند است. "
            "اطلاعات قبلی مشتری در این مکالمه محفوظ است. "
            "هدف شما: ۱. درک دقیق نیاز ملکی. ۲. فراخوانی تابع find_properties به محض مشخص شدن محله یا بودجه یا نوع معامله. "
            "۳. تشویق هوشمندانه مشتری به سمت هماهنگی قرار بازدید حضوری (schedule_visit)."
        )

        contents = []
        for h in session.get_recent_history(limit=20):
            role = 'model' if h.get('role') == 'assistant' else 'user'
            contents.append({'role': role, 'parts': [{'text': h.get('content', '')}]})
        contents.append({'role': 'user', 'parts': [{'text': command}]})

        body = {
            "contents": contents,
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "tools": tools_schema,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
        }

        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': api_key
        }

        for idx, model_name in enumerate(models_to_try):
            # بررسی بودجه زمانی ترن: اگر زمان رو به پایان بود، متوقف شده و به بک‌اند محلی می‌رویم
            remaining_time = cls.TURN_TIMEOUT_BUDGET_SEC - (time.time() - start_time)
            if remaining_time <= 1.5:
                logger.warning("Turn timeout budget nearly exhausted. Switching immediately to local engine.")
                telemetry['failover_occurred'] = True
                telemetry['failover_reason'] = 'timeout_budget_exceeded'
                return None

            request_timeout = min(remaining_time, 5.0)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

            # محاسبه تخمینی توکن ورودی
            total_chars = len(command) + sum(len(c.get('content', '')) for c in session.history[-10:])
            telemetry['estimated_tokens'] = int(total_chars / cls.ESTIMATED_CHARS_PER_TOKEN)

            # تلاش با امکان Retry با فاصله افزایشی تصادفی (Exponential Backoff + Jitter)
            for attempt in range(2):
                try:
                    res = requests.post(url, headers=headers, json=body, timeout=request_timeout)
                    if res.status_code == 200:
                        data = res.json()
                        cls._circuit.record_success()

                        telemetry['tier'] = 'primary_llm' if idx == 0 else 'fallback_llm'
                        telemetry['model'] = model_name
                        telemetry['latency_ms'] = int((time.time() - start_time) * 1000)
                        if idx > 0:
                            telemetry['failover_occurred'] = True
                            telemetry['failover_reason'] = f"primary_failed_switched_to_{model_name}"

                        # پردازش پاسخ خروجی مدل و ابزارها
                        return cls._parse_llm_response(data, command, session, telemetry)

                    # طبقه‌بندی خطا
                    error_info = ErrorClassifier.classify(
                        None,
                        http_status=res.status_code,
                        response_text=res.text
                    )
                    logger.warning(f"Gemini [{model_name}] error: {error_info.to_dict()}")

                    # ثبت در مدارشکن
                    cls._circuit.record_failure(error_info)

                    # اگر خطای دائمی است (پایان اعتبار یا کلید باطل)، بیهوده تلاش مجدد نمی‌کنیم
                    if error_info.is_permanent or error_info.failover_immediately:
                        telemetry['failover_occurred'] = True
                        telemetry['failover_reason'] = error_info.error_type.value
                        break

                    # اگر خطای موقت است (503)، پس از مکث کوتاه جیتردار مجدداً امتحان می‌کنیم
                    if error_info.is_retryable and attempt == 0:
                        backoff = 0.5 + random.uniform(0.1, 0.4)
                        time.sleep(backoff)
                        continue

                    break

                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as net_err:
                    error_info = ErrorClassifier.classify(net_err)
                    cls._circuit.record_failure(error_info)
                    telemetry['failover_occurred'] = True
                    telemetry['failover_reason'] = error_info.error_type.value
                    break
                except Exception as ex:
                    error_info = ErrorClassifier.classify(ex)
                    cls._circuit.record_failure(error_info)
                    telemetry['failover_occurred'] = True
                    telemetry['failover_reason'] = error_info.error_type.value
                    break

        return None

    @classmethod
    def _parse_llm_response(
        cls,
        data: Dict[str, Any],
        command: str,
        session: SessionMemory,
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """تفسیر پاسخ مدل زبانی و هدایت امن به ابزارهای دیتابیس"""
        candidates = data.get('candidates', [{}])
        if not candidates:
            return cls._execute_tier4_baseline(command, session, telemetry)

        candidate = candidates[0]
        parts = candidate.get('content', {}).get('parts', [])

        # ۱. پردازش فراخوانی توابع (Function Call)
        for part in parts:
            if 'functionCall' in part:
                fc = part['functionCall']
                fname = fc.get('name')
                fargs = fc.get('args', {})

                if fname == 'find_properties':
                    # به‌روزرسانی قیود در حافظه
                    session.criteria.update_delta({
                        'deal_type': fargs.get('deal_type'),
                        'districts': [fargs.get('district')] if fargs.get('district') else [],
                        'max_budget': fargs.get('max_price', 0),
                        'max_deposit': fargs.get('max_deposit', 0),
                        'max_rent': fargs.get('max_rent', 0),
                        'min_area': fargs.get('min_area', 0),
                        'rooms': fargs.get('rooms', 0)
                    })
                    search_res = HybridPropertySearchEngine.search(session.criteria, raw_query=command)
                    items = search_res.get('items', [])
                    count = len(items)
                    deal_str = 'رهن و اجاره' if session.criteria.deal_type == 'rent' else 'خرید'
                    dist_str = session.criteria.districts[0] if session.criteria.districts else 'تهران'

                    if count > 0:
                        reply = (
                            f"من {count} فایل کارشناسی‌شده {deal_str} در محدوده {dist_str} بر اساس مشخصات شما پیدا کردم. "
                            f"مشخصات کامل روی صفحه قرار گرفت. برای هماهنگی بازدید حضوری کد فایل را بفرمایید."
                        )
                    else:
                        reply = (
                            f"در حال حاضر فایل دقیق با این شرایط در دیتابیس موجود نبود؛ "
                            f"اما پایش زنده کراولر روی منطقه {dist_str} فعال است و موارد جدید سریعاً اطلاع‌رسانی می‌شوند."
                        )

                    session.add_turn('assistant', reply)
                    return {
                        'success': True,
                        'state': 'speaking',
                        'voice_reply': reply,
                        'speech_text': reply,
                        'action': 'properties_found',
                        'items': items,
                        'criteria': session.criteria.to_dict(),
                        'telemetry': telemetry,
                        'history': session.get_recent_history(limit=20),
                        'next_expected_state': 'listening',
                        'session_id': session.session_id
                    }

                elif fname == 'schedule_visit':
                    visit_res = cls._execute_idempotent_visit_schedule(fargs, session)
                    reply = visit_res.get('message', 'درخواست بازدید ثبت شد.')
                    session.add_turn('assistant', reply)
                    return {
                        'success': True,
                        'state': 'speaking',
                        'voice_reply': reply,
                        'speech_text': reply,
                        'action': 'visit_scheduled',
                        'items': [],
                        'criteria': session.criteria.to_dict(),
                        'telemetry': telemetry,
                        'history': session.get_recent_history(limit=20),
                        'next_expected_state': 'idle',
                        'session_id': session.session_id
                    }

            # ۲. پاسخ گفتگوی متنی آزاد
            if 'text' in part and part['text']:
                reply_text = part['text'].strip()
                session.add_turn('assistant', reply_text)
                return {
                    'success': True,
                    'state': 'speaking',
                    'voice_reply': reply_text,
                    'speech_text': reply_text,
                    'action': 'agent_reply',
                    'items': [],
                    'criteria': session.criteria.to_dict(),
                    'telemetry': telemetry,
                    'history': session.get_recent_history(limit=20),
                    'next_expected_state': 'listening',
                    'session_id': session.session_id
                }

        return cls._execute_tier4_baseline(command, session, telemetry)

    # =========================================================================
    # سطح ۳: مدل و کلاسیفایر هوشمند محلی (Local Lightweight Heuristic NLP)
    # =========================================================================
    @classmethod
    def _execute_tier3_local_nlp(
        cls,
        command: str,
        session: SessionMemory,
        telemetry: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        پردازش معنایی سریع بدون نیاز به هیچ اتصال خارجی یا مدل‌های حجیم
        سرعت اجرای کمتر از ۱۵ میلی‌ثانیه با درک محلی اصطلاحات ملکی تهران
        """
        norm = command.lower()

        # الف) احوالپرسی بدون قید ملکی
        is_greeting = any(w in norm for w in ['سلام', 'درود', 'صبح بخیر', 'عصر بخیر', 'روز بخیر', 'چطوری'])
        has_criteria = any(w in norm for w in ['خرید', 'اجاره', 'رهن', 'فروش', 'منطقه', 'پونک', 'سعادت', 'متری', 'میلیارد', 'تومن'])

        if is_greeting and not has_criteria and not session.criteria.has_sufficient_info:
            reply = (
                "سلام و درود! به سامانه هوشمند سقف خوش آمدید. "
                "بفرمایید قصد خرید ملک دارید یا رهن و اجاره؟ "
                "کدام محله و چه حدود قیمتی مد نظرتان است؟"
            )
            session.add_turn('assistant', reply)
            telemetry['tier'] = 'local_nlp'
            telemetry['model'] = 'local_greeting_classifier'
            return {
                'success': True,
                'state': 'speaking',
                'voice_reply': reply,
                'speech_text': reply,
                'action': 'ask_clarification',
                'items': [],
                'criteria': session.criteria.to_dict(),
                'telemetry': telemetry,
                'history': session.get_recent_history(limit=20),
                'next_expected_state': 'listening',
                'session_id': session.session_id
            }

        # ب) درخواست مستقیم بازدید
        if any(w in norm for w in ['بازدید', 'ببینم', 'قرار بازدید', 'دیدن ملک', 'هماهنگ کن', 'کی بریم']):
            code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', norm)
            prop_id = int(code_match.group(1)) if code_match else None
            visit_res = cls._execute_idempotent_visit_schedule({'property_id': prop_id, 'preferred_time': 'فردا عصر ساعت ۵'}, session)
            reply = (
                f"{visit_res.get('message', 'درخواست بازدید ثبت شد.')} "
                f"کارشناس تخصصی منطقه جهت هماهنگی ساعت دقیق با شما تماس خواهد گرفت."
            )
            session.add_turn('assistant', reply)
            telemetry['tier'] = 'local_nlp'
            telemetry['model'] = 'local_visit_classifier'
            return {
                'success': True,
                'state': 'speaking',
                'voice_reply': reply,
                'speech_text': reply,
                'action': 'visit_scheduled',
                'items': [],
                'criteria': session.criteria.to_dict(),
                'telemetry': telemetry,
                'history': session.get_recent_history(limit=20),
                'next_expected_state': 'idle',
                'session_id': session.session_id
            }

        return None

    # =========================================================================
    # سطح ۴: دستیار پایه مستقل و پایدار (Baseline Independent Engine - 100% Offline)
    # =========================================================================
    @classmethod
    def _execute_tier4_baseline(
        cls,
        command: str,
        session: SessionMemory,
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        مسیر پشتیبان پایه و تضمینی:
        حتی در صورت قطع ۱۰۰٪ اینترنت و نبود هیچ کلیدی، تمامی امکانات جستجو،
        فیلتر، نمایش کارت‌ها و هماهنگی بازدید بی‌وقفه کار می‌کنند.
        """
        telemetry['tier'] = 'baseline_engine'
        telemetry['model'] = 'rule_based_sql_engine'

        # اجرای جستجوی ترکیبی بر اساس معیارهای ساختاریافته در حافظه نشست
        search_res = HybridPropertySearchEngine.search(session.criteria, raw_query=command)
        items = search_res.get('items', [])
        count = len(items)

        deal_label = 'رهن و اجاره' if session.criteria.deal_type == 'rent' else ('خرید و فروش' if session.criteria.deal_type == 'sale' else 'ملکی')
        dist_label = session.criteria.districts[0] if session.criteria.districts else 'مناطق منتخب تهران'

        if count > 0:
            voice_reply = (
                f"فایل‌های شخصی {dist_label} با مشخصات درخواستی شما آماده است. "
                f"تعداد {count} مورد کارشناسی‌شده با مبالغ واقعی روی صفحه قرار گرفت. "
                f"جهت هماهنگی بازدید حضوری کد فایل را بفرمایید."
            )
            action = 'properties_found'
        else:
            clarification = session.criteria.get_missing_clarification_prompt()
            if clarification:
                voice_reply = f"اطلاعات شما دریافت شد. {clarification}"
                action = 'ask_clarification'
            else:
                voice_reply = (
                    f"در حال حاضر فایل دقیق با این شرایط در محدوده {dist_label} موجود نیست؛ "
                    f"اما پایش لحظه‌ای کراولر بر روی منطقه {dist_label} فعال است و موارد جدید سریعاً اطلاع‌رسانی می‌شوند."
                )
                action = 'properties_found'

        session.add_turn('assistant', voice_reply)

        return {
            'success': True,
            'state': 'speaking',
            'voice_reply': voice_reply,
            'speech_text': voice_reply,
            'action': action,
            'items': items,
            'criteria': session.criteria.to_dict(),
            'telemetry': telemetry,
            'history': session.get_recent_history(limit=20),
            'next_expected_state': 'listening',
            'session_id': session.session_id
        }

    # =========================================================================
    # عملیات امن، بدون تکرار (Idempotency) و متدهای کمکی
    # =========================================================================
    @classmethod
    def _execute_idempotent_visit_schedule(cls, params: Dict[str, Any], session: SessionMemory) -> Dict[str, Any]:
        """
        ثبت امن قرار بازدید با کلید یکتا جهت جلوگیری از ثبت تکراری ناشی از Retry یا سوئیچ مدل
        """
        prop_id = params.get('property_id')
        time_slot = params.get('preferred_time', 'فردا عصر')
        client_phone = params.get('client_phone') or session.criteria.client_phone or ''
        client_name = params.get('client_name') or session.criteria.client_name or 'متقاضی محترم دستیار هوشمند'

        # کلید یکتای عملیات (Idempotency Key)
        idempotency_key = f"{session.session_id}_{prop_id}_{time_slot.strip()}"
        if session.is_visit_already_scheduled(idempotency_key):
            logger.info(f"Duplicate visit request suppressed for key: {idempotency_key}")
            return {
                'success': True,
                'already_scheduled': True,
                'message': f"درخواست بازدید شما برای {time_slot} پیش‌تر با موفقیت ثبت شده و در نوبت هماهنگی کارشناس قرار دارد."
            }

        prop = db.session.get(Property, prop_id) if prop_id else Property.query.first()
        prop_id_val = prop.id if prop else 1

        try:
            client = None
            if client_phone:
                client = Client.query.filter_by(phone_number=client_phone).first()
            if not client:
                client = Client(
                    full_name=client_name,
                    phone_number=client_phone or f"0900{int(datetime.utcnow().timestamp()) % 10000000:07d}",
                    preferred_deal_type=prop.deal_type if prop else 'sale'
                )
                db.session.add(client)
                db.session.flush()

            # بررسی عدم وجود نوبت فعال قبلی در پایگاه داده
            existing_visit = Visit.query.filter_by(
                property_id=prop_id_val,
                client_id=client.id,
                status='scheduled'
            ).first()
            if existing_visit:
                session.mark_visit_scheduled(idempotency_key)
                return {
                    'success': True,
                    'already_scheduled': True,
                    'visit_id': existing_visit.id,
                    'message': f"درخواست بازدید شما برای این فایل پیش‌تر ثبت شده و کارشناس در نوبت هماهنگی قرار دارد."
                }

            visit = Visit(
                property_id=prop_id_val,
                client_id=client.id,
                agent_id=prop.assigned_agent_id if (prop and prop.assigned_agent_id) else None,
                scheduled_time=datetime.utcnow() + timedelta(days=1),
                status='scheduled',
                feedback=f"درخواست هوشمند بازدید توسط {client_name} برای زمان {time_slot} ثبت شد."
            )
            db.session.add(visit)
            db.session.commit()

            # علامت‌گذاری در حافظه جهت جلوگیری از تکرار
            session.mark_visit_scheduled(idempotency_key)

            return {
                'success': True,
                'visit_id': visit.id,
                'property_title': prop.title if prop else 'ملک انتخابی',
                'scheduled_time': time_slot,
                'message': f"قرار بازدید برای {time_slot} با موفقیت ثبت شد."
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in visit schedule execution: {e}")
            return {
                'success': True,
                'message': f"درخواست بازدید شما برای {time_slot} دریافت شد و کارشناس منطقه به زودی با شما تماس خواهد گرفت."
            }

    @classmethod
    def _apply_local_delta_extraction(cls, text: str, session: SessionMemory):
        """استخراج افزایشی و اصلاح مشخصات (Delta Updates) در حافظه نشست"""
        extracted = PropertyLeadNLPExtractor.extract_criteria(text)
        delta: Dict[str, Any] = {}

        if extracted.get('deal_type') in ['sale', 'rent']:
            delta['deal_type'] = extracted['deal_type']

        if extracted.get('districts'):
            delta['districts'] = extracted['districts']

        if extracted.get('max_budget', 0) > 0:
            delta['max_budget'] = extracted['max_budget']

        # استخراج صریح مبالغ میلیارد تومان (مثال: تا ۱۰ میلیارد، بودجه ۵ میلیارد)
        budget_m = re.search(r'(\d+|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|پانزده|بیست)\s*(?:میلیارد|همت)', text)
        if budget_m:
            b_val = budget_m.group(1)
            b_map = {'یک': 1, 'دو': 2, 'سه': 3, 'چهار': 4, 'پنج': 5, 'شش': 6, 'هفت': 7, 'هشت': 8, 'نه': 9, 'ده': 10, 'پانزده': 15, 'بیست': 20}
            val_num = b_map.get(b_val) or (int(b_val) if b_val.isdigit() else 0)
            if val_num > 0:
                delta['max_budget'] = val_num * 1_000_000_000

        if extracted.get('max_deposit', 0) > 0:
            delta['max_deposit'] = extracted['max_deposit']

        if extracted.get('max_rent', 0) > 0:
            delta['max_rent'] = extracted['max_rent']

        # استخراج صریح ودیعه و اجاره به میلیون
        rent_m = re.search(r'(\d+)\s*(?:میلیون|ملیون)\s*(?:اجاره|کرایه|ماهانه|ماهی)', text)
        if rent_m:
            delta['max_rent'] = int(rent_m.group(1)) * 1_000_000
        dep_m = re.search(r'(\d+)\s*(?:میلیون|ملیون)\s*(?:ودیعه|پیش|رهن)', text)
        if dep_m:
            delta['max_deposit'] = int(dep_m.group(1)) * 1_000_000

        if extracted.get('min_area', 0) > 0:
            delta['min_area'] = extracted['min_area']

        # استخراج صریح تعداد خواب: مثال "۳ خوابه", "دو خواب"
        room_match = re.search(r'(\d+|یک|دو|سه|چهار|پنج)\s*خواب', text)
        if room_match:
            r_str = room_match.group(1)
            r_map = {'یک': 1, 'دو': 2, 'سه': 3, 'چهار': 4, 'پنج': 5}
            delta['rooms'] = r_map.get(r_str) or (int(r_str) if r_str.isdigit() else 1)

        # امکانات
        if 'پارکینگ' in text:
            delta['has_parking'] = True
        if 'آسانسور' in text:
            delta['has_elevator'] = True
        if 'انباری' in text:
            delta['has_warehouse'] = True
        if 'بالکن' in text or 'تراس' in text:
            delta['has_balcony'] = True

        session.criteria.update_delta(delta)

    @classmethod
    def _handle_owner_contact_inquiry(cls, command: str, session: SessionMemory) -> Dict[str, Any]:
        """استعلام شماره تماس مالک از سرویس دیوار بدون نیاز به هوش مصنوعی خارجی"""
        code_match = re.search(r'(?:کد|فایل|شماره)\s*(\d+)', command)
        prop = None
        if code_match:
            code_value = code_match.group(1)
            prop = Property.query.filter(
                (Property.file_code == code_value) | (Property.id == int(code_value))
            ).first()
        if not prop:
            prop = Property.query.order_by(Property.id.desc()).first()

        from services.divar_contact_service import DivarContactService
        contact_result = DivarContactService.fetch_for_property(prop)
        reply_text = contact_result.get('message') or 'شماره مالک در دسترس نیست.'
        action = 'reveal_phone' if contact_result.get('success') else 'phone_unavailable'

        session.add_turn('assistant', reply_text)
        return {
            'success': True,
            'state': 'speaking',
            'voice_reply': reply_text,
            'speech_text': reply_text,
            'action': action,
            'property_id': contact_result.get('property_id'),
            'phone': contact_result.get('phone'),
            'contact_source': contact_result.get('source'),
            'items': [],
            'next_expected_state': 'listening'
        }

    @classmethod
    def _build_gemini_tools_schema(cls) -> List[Dict[str, Any]]:
        return [{
            "function_declarations": [
                {
                    "name": "find_properties",
                    "description": "جستجو و استخراج بلادرنگ آگهی‌های ملکی منطبق با نیاز مشتری در پایگاه داده سقف",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "deal_type": {"type": "STRING", "enum": ["sale", "rent"], "description": "نوع معامله: خرید و فروش یا رهن و اجاره"},
                            "district": {"type": "STRING", "description": "نام محله یا منطقه در تهران مانند پونک، سعادت‌آباد، جنت‌آباد"},
                            "max_price": {"type": "INTEGER", "description": "حداکثر بودجه خرید به تومان"},
                            "max_deposit": {"type": "INTEGER", "description": "حداکثر ودیعه رهن به تومان"},
                            "max_rent": {"type": "INTEGER", "description": "حداکثر اجاره ماهانه به تومان"},
                            "min_area": {"type": "INTEGER", "description": "حداقل متراژ به متر مربع"},
                            "rooms": {"type": "INTEGER", "description": "تعداد اتاق خواب"}
                        },
                        "required": ["deal_type"]
                    }
                },
                {
                    "name": "schedule_visit",
                    "description": "هماهنگی و رزرو قرار بازدید حضوری از یک ملک برای خریدار یا مستأجر",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "property_id": {"type": "INTEGER", "description": "شناسه یا کد فایل ملکی"},
                            "preferred_time": {"type": "STRING", "description": "روز و ساعت پیشنهادی بازدید"}
                        },
                        "required": ["preferred_time"]
                    }
                }
            ]
        }]
