"""
موتور مرکزی پردازش چندکاناله و اتوماسیون پایپ‌لاین سقف (OmniChannel Processing Engine)
زیرساخت Dual-Engine بدون وابستگی انحصاری (Zero Vendor Lock-in)
ادغام هوشمند درگاه‌های ورودی، رونویسی گفتار STT، کلاسیفایر نقش LLM Router، تفکیک به دو CRM مجزا،
فالوآپ خودکار و هشدارهای تفکیک‌شده طلایی و سبز در تلگرام
"""

import os
import json
import logging
import threading
import urllib.request
from typing import Dict, Any, Optional

from database.db import db
from database.models import Property, Owner, CustomerLead, Client, CallRecord
from services.stt_service import stt_processor
from services.llm_router import SemanticLLMRouter
from services.crm_dual_store import DualCRMStore
from services.nurturing_engine import nurturing_engine
from telegram_bot.admin_alerts import send_gold_property_alert, send_green_lead_alert
from bale_bot.admin_alerts import send_bale_gold_property_alert, send_bale_green_lead_alert

logger = logging.getLogger(__name__)

class OmniChannelEngine:
    """
    موتور مستقل و دائمی پلتفرم سقف جهت پردازش رویدادهای چندکاناله
    """

    def __init__(self):
        self.n8n_webhook_url = os.getenv('N8N_OMNI_WEBHOOK_URL', '')

    @classmethod
    def ingest_interaction(
        cls,
        channel: str,
        sender_id: str,
        text: Optional[str] = None,
        content: Optional[str] = None,
        audio_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        متد کمکی و سریع جهت فراخوانی متمرکز پردازش رویداد ورودی
        """
        engine = cls()
        effective_content = text if text is not None else content
        return engine.process_incoming_interaction(
            channel=channel,
            sender_id=sender_id,
            content=effective_content,
            audio_url=audio_url,
            metadata=metadata
        )

    def process_incoming_interaction(
        self,
        channel: str,
        sender_id: str,
        content: Optional[str] = None,
        audio_url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        پردازش سرتاسری رویداد ورودی از هریک از درگاه‌های:
        voip, sms, telegram, whatsapp, bale, eitaa, rubika, instagram
        """
        metadata = metadata or {}
        metadata['channel'] = channel
        metadata['sender_id'] = sender_id

        # ۱. تبدیل صوت به متن (Speech-to-Text) در صورت وجود فایل صوتی مکالمه
        transcribed_text = ""
        stt_engine = 'none'
        if audio_url:
            stt_res = stt_processor.transcribe(audio_url_or_path=audio_url, fallback_text=content)
            transcribed_text = stt_res.get('text', '')
            stt_engine = stt_res.get('engine', 'unknown')

        effective_text = (transcribed_text or content or '').strip()

        # ۲. ثبت یا به‌روزرسانی رکورد تماس در جدول CallRecord در صورت دریافت از VoIP
        if channel in ['voip', 'call']:
            try:
                cid = metadata.get('call_id') or f"CALL-{sender_id}"
                call_rec = CallRecord.query.filter_by(call_id=cid).first()
                if not call_rec:
                    call_rec = CallRecord(
                        call_id=cid,
                        caller_phone=sender_id,
                        audio_url=audio_url,
                        transcribed_text=effective_text,
                        processing_status='processing',
                        duration_seconds=int(metadata.get('duration_seconds', 0))
                    )
                    db.session.add(call_rec)
                else:
                    call_rec.transcribed_text = effective_text
                    call_rec.duration_seconds = int(metadata.get('duration_seconds', call_rec.duration_seconds))
                    call_rec.processing_status = 'processing'
                db.session.commit()
            except Exception as e:
                logger.warning(f"Failed to record call log: {e}")
                db.session.rollback()

        # ۳. تحلیل معنایی و تشخیص نقش با LLM Router
        classification = SemanticLLMRouter.classify_and_extract(
            text=effective_text,
            sender_phone=sender_id,
            metadata=metadata
        )

        role = classification.get('role', 'lead')
        result_details = {}

        # ۴. تفکیک جریان کار بر اساس نقش (مالک vs متقاضی)
        if role == 'owner':
            owner_payload = classification.get('owner_payload') or {}
            owner_payload.setdefault('phone', sender_id)
            
            # ذخیره در CRM مالکین و املاک
            owner, prop = DualCRMStore.store_owner_and_property(
                payload=owner_payload,
                channel=channel,
                raw_text=effective_text
            )

            # ارسال پیام خوش‌آمد و درخواست تصاویر به مالک
            nurturing_res = nurturing_engine.handle_owner_onboarding(
                prop=prop,
                owner=owner,
                channel=channel
            )

            # ارسال لحظه‌ای آلارم طلایی لوکس به تلگرام و بله ادمین‌ها
            alert_sent = False
            bale_alert_sent = False
            try:
                alert_sent = send_gold_property_alert(prop, owner)
            except Exception as te:
                logger.error(f"Error triggering Telegram gold alert: {te}")
            try:
                bale_alert_sent = send_bale_gold_property_alert(prop, owner)
            except Exception as be:
                logger.error(f"Error triggering Bale gold alert: {be}")

            result_details = {
                'role': 'owner',
                'property_id': prop.id,
                'file_code': prop.file_code,
                'owner_id': owner.id,
                'owner_name': owner.full_name,
                'onboarding_status': nurturing_res.get('success', False),
                'telegram_alert_sent': alert_sent,
                'bale_alert_sent': bale_alert_sent
            }

        else:
            lead_payload = classification.get('lead_payload') or {}
            lead_payload.setdefault('phone', sender_id)
            lead_payload.setdefault('active_messenger', channel)

            # ذخیره در CRM مشتریان و متقاضیان
            lead, client = DualCRMStore.store_customer_lead(
                payload=lead_payload,
                channel=channel,
                raw_text=effective_text
            )

            # تطبیق هوشمند و ارسال ۳ فایل برتر با لینک معتبر
            dispatches = nurturing_engine.handle_lead_matching_and_dispatch(
                lead=lead,
                channel=channel
            )

            # ارسال لحظه‌ای آلارم سبز به تلگرام و بله ادمین‌ها
            alert_sent = False
            bale_alert_sent = False
            try:
                alert_sent = send_green_lead_alert(lead)
            except Exception as te:
                logger.error(f"Error triggering Telegram green alert: {te}")
            try:
                bale_alert_sent = send_bale_green_lead_alert(lead)
            except Exception as be:
                logger.error(f"Error triggering Bale green alert: {be}")

            result_details = {
                'role': 'lead',
                'lead_id': lead.id,
                'client_id': client.id,
                'matched_dispatches': len(dispatches),
                'telegram_alert_sent': alert_sent,
                'bale_alert_sent': bale_alert_sent
            }

        # ۵. فوروارد موازی و ناهمگام به n8n (در صورت فعال بودن وب‌هوک n8n)
        self._async_forward_to_n8n({
            'channel': channel,
            'sender_id': sender_id,
            'text': effective_text,
            'classification': classification,
            'result': result_details
        })

        return {
            'success': True,
            'channel': channel,
            'sender_id': sender_id,
            'stt_engine': stt_engine,
            'role': role,
            'classification': classification,
            'details': result_details
        }

    def _async_forward_to_n8n(self, payload: Dict[str, Any]):
        """
        ارسال غیرمسدودکننده به n8n Cloud / Self-hosted
        اگر سرور n8n در دسترس نباشد یا اشتراک منقضی شده باشد، هیچ تاثیری بر عملکرد سقف نخواهد گذاشت.
        """
        if not self.n8n_webhook_url:
            return

        def _worker():
            try:
                data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                req = urllib.request.Request(
                    self.n8n_webhook_url,
                    data=data_bytes,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
            except Exception as e:
                logger.debug(f"n8n async forward skipped or failed: {e}")

        threading.Thread(target=_worker, daemon=True).start()

omnichannel_engine = OmniChannelEngine()
