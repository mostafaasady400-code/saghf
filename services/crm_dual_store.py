"""
هسته تفکیک و ذخیره‌سازی در دو پایگاه داده CRM مجزا (Dual CRM Store)
۱. CRM مالکین و املاک (Properties & Owners CRM)
۲. CRM مشتریان و متقاضیان (Buyers & Tenants CRM)
ثبت تراکنش‌های امن، لاگ تعاملات (Interaction) و مدیریت یکپارچه اطلاعات
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from database.db import db
from database.models import Owner, Property, Client, CustomerLead, Interaction

logger = logging.getLogger(__name__)

class DualCRMStore:
    """
    سرویس تفکیک و ذخیره‌سازی دوگانه در پایگاه داده CRM
    """

    @classmethod
    def store_owner_and_property(cls, payload: Dict[str, Any], channel: str = 'omnichannel', raw_text: str = '') -> Tuple[Owner, Property]:
        """
        ذخیره یا به‌روزرسانی اطلاعات در پایگاه داده CRM مالکین و املاک
        """
        phone = (payload.get('phone') or '').strip()
        full_name = payload.get('owner_name') or payload.get('full_name') or f"مالک {payload.get('district', 'سقف')}"
        district = payload.get('district') or 'منطقه ۵'
        city = payload.get('city') or 'تهران'
        title = payload.get('title') or f"ملک شخصی {district}"
        deal_type = payload.get('deal_type', 'rent')
        property_type = payload.get('property_type', 'apartment')

        area = int(payload.get('area') or 85)
        rooms = int(payload.get('rooms') or 2)
        floor = int(payload.get('floor') or 2)
        total_price = int(payload.get('total_price') or 0)
        deposit = int(payload.get('deposit') or 0)
        monthly_rent = int(payload.get('monthly_rent') or 0)

        has_parking = bool(payload.get('has_parking', False))
        has_elevator = bool(payload.get('has_elevator', False))
        has_warehouse = bool(payload.get('has_warehouse', False))
        has_balcony = bool(payload.get('has_balcony', False))
        features = payload.get('features') or []
        doc_status = payload.get('document_status', 'در دست بررسی')
        images = payload.get('images') or []

        # ۱. مدیریت رکورد مالک در جدول Owner
        owner = None
        if phone:
            owner = Owner.query.filter_by(phone_number=phone).first()

        if not owner:
            owner = Owner(
                full_name=full_name,
                phone_number=phone or f"OWNER-{int(datetime.utcnow().timestamp())}",
                urgency='high',
                flexibility='منعطف',
                notes=f"ثبت شده از درگاه ورودی {channel}. وضعیت مدارک: {doc_status}",
                created_at=datetime.utcnow()
            )
            db.session.add(owner)
            db.session.flush()
        else:
            if full_name and not owner.full_name.startswith('مالک '):
                pass
            elif full_name:
                owner.full_name = full_name
            owner.notes = (owner.notes or '') + f"\n[به‌روزرسانی {datetime.utcnow().strftime('%Y-%m-%d')} از {channel}]"

        # ۲. ایجاد رکورد ملک در جدول Property
        prop = Property(
            source=f'omnichannel_{channel}',
            title=title,
            deal_type=deal_type,
            property_type=property_type,
            city=city,
            district=district,
            total_price=total_price,
            deposit=deposit,
            monthly_rent=monthly_rent,
            area=area,
            rooms=rooms,
            floor=floor,
            has_parking=has_parking,
            has_elevator=has_elevator,
            has_warehouse=has_warehouse,
            has_balcony=has_balcony,
            status='verified',  # تایید اولیه برای فایل‌های ارسالی خود مالک
            owner_type='personal',
            is_personal_owner=True,
            owner_id=owner.id,
            description=f"ثبت خودکار از طریق {channel}. متادیتای سندی: {doc_status}.\nمتن اصلی پیام: {raw_text[:300] if raw_text else 'ندارد'}",
            created_at=datetime.utcnow()
        )
        prop.features = features
        if images:
            prop.images = images

        db.session.add(prop)
        db.session.flush()

        # تنظیم لینک مستقیم آگهی برای رعایت قانون AGENTS.md
        prop.source_url = f"http://127.0.0.1:5000/properties/{prop.id}"

        # ۳. ثبت در جدول Interaction
        interaction = Interaction(
            type=f"{channel}_message",
            target_type='owner',
            target_id=owner.id,
            owner_id=owner.id,
            property_id=prop.id,
            summary=f"دریافت و ثبت فایل ملکی کد {prop.file_code} از مالک در درگاه {channel}",
            outcome='registered',
            created_at=datetime.utcnow()
        )
        db.session.add(interaction)

        db.session.commit()
        logger.info(f"✅ Property {prop.id} ({prop.file_code}) and Owner {owner.id} saved in Owners CRM.")
        return owner, prop

    @classmethod
    def store_customer_lead(cls, payload: Dict[str, Any], channel: str = 'omnichannel', raw_text: str = '') -> Tuple[CustomerLead, Client]:
        """
        ذخیره یا به‌روزرسانی اطلاعات در پایگاه داده CRM متقاضیان و خریداران
        """
        phone = (payload.get('phone') or '').strip()
        full_name = payload.get('full_name') or f"متقاضی {channel}"
        deal_type = payload.get('deal_type', 'rent')
        districts = payload.get('preferred_districts') or ['منطقه ۵']
        features = payload.get('preferred_features') or []
        active_messenger = payload.get('active_messenger') or channel

        min_budget = int(payload.get('min_budget') or 0)
        max_budget = int(payload.get('max_budget') or 0)
        max_deposit = int(payload.get('max_deposit') or 0)
        max_rent = int(payload.get('max_rent') or 0)
        min_area = int(payload.get('min_area') or 0)
        max_area = int(payload.get('max_area') or 0)

        # ۱. ذخیره یا آپدیت در جدول CustomerLead
        lead = None
        if phone:
            lead = CustomerLead.query.filter_by(phone_number=phone).first()

        if not lead:
            lead = CustomerLead(
                phone_number=phone or f"LEAD-{int(datetime.utcnow().timestamp())}",
                full_name=full_name,
                deal_type=deal_type,
                min_budget=min_budget,
                max_budget=max_budget,
                max_deposit=max_deposit,
                max_rent=max_rent,
                min_area=min_area,
                active_messenger=active_messenger,
                last_interaction_at=datetime.utcnow(),
                created_at=datetime.utcnow()
            )
            lead.preferred_districts = districts
            lead.preferred_features = features
            db.session.add(lead)
            db.session.flush()
        else:
            lead.deal_type = deal_type
            lead.preferred_districts = districts
            lead.preferred_features = features
            if deal_type == 'sale' and max_budget > 0:
                lead.max_budget = max_budget
            else:
                if max_deposit > 0: lead.max_deposit = max_deposit
                if max_rent > 0: lead.max_rent = max_rent
            if min_area > 0: lead.min_area = min_area
            lead.active_messenger = active_messenger
            lead.last_interaction_at = datetime.utcnow()

        # ۲. همگام‌سازی با جدول پایپ‌لاین پیشرفته Client در CRM
        client = None
        if phone:
            client = Client.query.filter_by(phone_number=phone).first()

        if not client:
            client = Client(
                full_name=full_name,
                phone_number=phone or lead.phone_number,
                preferred_deal_type=deal_type,
                min_budget=min_budget,
                max_budget=max_budget,
                max_deposit=max_deposit,
                max_rent=max_rent,
                min_area=min_area,
                max_area=max_area,
                must_have_parking='پارکینگ' in features,
                must_have_elevator='آسانسور' in features,
                must_have_warehouse='انباری' in features,
                urgency='urgent',
                lead_status='new',
                notes=f"سرنخ ورودی از {channel}.\nپیام اولیه: {raw_text[:300] if raw_text else 'ندارد'}",
                created_at=datetime.utcnow()
            )
            client.preferred_districts = districts
            db.session.add(client)
            db.session.flush()
        else:
            client.preferred_deal_type = deal_type
            client.preferred_districts = districts
            if deal_type == 'sale' and max_budget > 0:
                client.max_budget = max_budget
            else:
                if max_deposit > 0: client.max_deposit = max_deposit
                if max_rent > 0: client.max_rent = max_rent
            if min_area > 0: client.min_area = min_area
            client.updated_at = datetime.utcnow()

        # ۳. ثبت تعامل در Interaction
        interaction = Interaction(
            type=f"{channel}_inbound",
            target_type='client',
            target_id=client.id,
            client_id=client.id,
            summary=f"ثبت تقاضای جدید ملک از درگاه {channel} برای مناطق {', '.join(districts)}",
            outcome='new_lead',
            created_at=datetime.utcnow()
        )
        db.session.add(interaction)

        db.session.commit()
        logger.info(f"✅ Lead {lead.id} and Client {client.id} saved in Buyers/Tenants CRM.")
        return lead, client

crm_dual_store = DualCRMStore()
