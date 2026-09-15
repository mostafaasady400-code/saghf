import urllib.parse
from datetime import datetime
from database.db import db
from database.models import Property, Interaction, Owner

class OmniMessengerService:
    """
    سرویس جامع استعلام خودکار وضعیت آگهی از طریق پیام‌رسان‌های تلگرام، واتساپ، بله، ایتا و روبیکا
    """

    PLATFORMS = {
        'whatsapp': {
            'name': 'واتساپ',
            'latin': 'WhatsApp',
            'color': '#25D366',
            'icon': '💬'
        },
        'telegram': {
            'name': 'تلگرام',
            'latin': 'Telegram',
            'color': '#229ED9',
            'icon': '✈️'
        },
        'bale': {
            'name': 'بله',
            'latin': 'Bale',
            'color': '#18b368',
            'icon': '🌿'
        },
        'eitaa': {
            'name': 'ایتا',
            'latin': 'Eitaa',
            'color': '#e67e22',
            'icon': '🟠'
        },
        'rubika': {
            'name': 'روبیکا',
            'latin': 'Rubika',
            'color': '#8b5cf6',
            'icon': '🟣'
        }
    }

    @staticmethod
    def normalize_phone(phone_str: str) -> str:
        """تبدیل شماره به فرمت استاندارد ۱۰ رقمی بدون صفر اول (مثلاً 9121234567)"""
        if not phone_str:
            return ""
        digits = "".join([c for c in phone_str if c.isdigit()])
        if digits.startswith("98") and len(digits) == 12:
            return digits[2:]
        if digits.startswith("0") and len(digits) == 11:
            return digits[1:]
        return digits

    @classmethod
    def generate_inquiry_message(cls, prop: Property) -> str:
        """
        تولید متن پیام مودبانه، حرفه‌ای و کوتاه به زبان فارسی
        جهت استعلام موجودی یا واگذاری ملک
        """
        owner_name = prop.owner.full_name if (prop.owner and prop.owner.full_name) else "مالک محترم"
        deal_label = "فروش" if prop.deal_type == "sale" else "رهن و اجاره"

        if prop.deal_type == "sale":
            price_txt = f"{prop.total_price:,} تومان" if prop.total_price else "توافقی"
        else:
            price_txt = f"ودیعه: {prop.deposit:,} | اجاره: {prop.monthly_rent:,} تومان"

        msg = (
            f"سلام و احترام {owner_name} گرامی،\n"
            f"از دپارتمان تخصصی املاک سقف خدمت شما پیام می‌فرستیم.\n\n"
            f"در خصوص فایل ملکی شما:\n"
            f"📌 «{prop.title}»\n"
            f"📍 {prop.district} | {prop.area} متر | {deal_label}\n"
            f"💰 {price_txt}\n\n"
            f"جهت معرفی دقیق به مشتریان و به‌روزرسانی وضعیت در سامانه سقف، لطفاً وضعیت ملک را مشخص فرمایید:\n"
            f"ارسال عدد ۱: ملک کماکان «موجود» است\n"
            f"ارسال عدد ۲: ملک «واگذار / فروخته» شده است\n\n"
            f"با تشکر و احترام - املاک سقف 🏛️"
        )
        return msg

    @classmethod
    def get_platform_links(cls, phone: str, message: str, source_url: str = None) -> dict:
        """
        تولید لینک‌های مستقیم ورود و ارسال پیام در هر ۵ پیام‌رسان
        """
        clean_9 = cls.normalize_phone(phone)
        encoded_msg = urllib.parse.quote(message)
        
        links = {}
        
        if clean_9:
            int_phone = f"98{clean_9}"
            local_phone = f"0{clean_9}"
            
            # 1. WhatsApp
            links['whatsapp'] = {
                'title': 'ارسال در واتساپ',
                'url': f"https://wa.me/{int_phone}?text={encoded_msg}",
                'icon': '💬',
                'color': cls.PLATFORMS['whatsapp']['color']
            }
            # 2. Telegram
            links['telegram'] = {
                'title': 'ارسال در تلگرام',
                'url': f"https://t.me/+{int_phone}",
                'icon': '✈️',
                'color': cls.PLATFORMS['telegram']['color']
            }
            # 3. Bale
            links['bale'] = {
                'title': 'ارسال در بله',
                'url': f"https://ble.ir/+{int_phone}",
                'icon': '🌿',
                'color': cls.PLATFORMS['bale']['color']
            }
            # 4. Eitaa
            links['eitaa'] = {
                'title': 'ارسال در ایتا',
                'url': f"https://eitaa.com/+{int_phone}",
                'icon': '🟠',
                'color': cls.PLATFORMS['eitaa']['color']
            }
            # 5. Rubika
            links['rubika'] = {
                'title': 'ارسال در روبیکا',
                'url': f"https://rubika.ir/+{int_phone}",
                'icon': '🟣',
                'color': cls.PLATFORMS['rubika']['color']
            }
        else:
            # اگر شماره مستقیم در متن نبوده و محفوظ در دیوار است
            for p_key, p_val in cls.PLATFORMS.items():
                links[p_key] = {
                    'title': f"ارسال در {p_val['name']}",
                    'url': source_url or "#",
                    'is_fallback': True,
                    'icon': p_val['icon'],
                    'color': p_val['color']
                }
                
        return links

    @classmethod
    def generate_inquiry_package(cls, property_id: int) -> dict:
        """
        تهیه بسته کامل استعلام برای فرانت‌اند شامل متن، شماره، و دیپ‌لینک‌های ۵ پیام‌رسان
        """
        prop = Property.query.get(property_id)
        if not prop:
            return {'error': 'ملک یافت نشد'}

        phone = prop.owner.phone_number if prop.owner else ""
        message = cls.generate_inquiry_message(prop)
        links = cls.get_platform_links(phone, message, prop.source_url)

        return {
            'property_id': prop.id,
            'title': prop.title,
            'district': prop.district,
            'deal_type': prop.deal_type,
            'phone': phone,
            'has_direct_phone': bool(phone and phone.startswith('09')),
            'message': message,
            'source_url': prop.source_url,
            'links': links,
            'inquiry_status': prop.inquiry_status,
            'last_inquiry_at': prop.last_inquiry_at.strftime('%Y-%m-%d %H:%M') if prop.last_inquiry_at else None,
            'age_in_days': prop.age_in_days
        }

    @classmethod
    def mark_inquiry_sent(cls, property_id: int, agent_id: int = None, platform: str = 'all') -> bool:
        """
        ثبت ارسال پیام استعلام در سیستم و تغییر وضعیت به در انتظار پاسخ
        """
        prop = Property.query.get(property_id)
        if not prop:
            return False

        prop.inquiry_status = 'waiting_reply'
        prop.last_inquiry_at = datetime.utcnow()

        # ثبت لاگ تعامل در CRM
        interaction = Interaction(
            type='whatsapp',
            target_type='owner',
            owner_id=prop.owner_id,
            property_id=prop.id,
            agent_id=agent_id,
            summary=f"ارسال پیام استعلام خودکار موجودی ملک از طریق {cls.PLATFORMS.get(platform, {}).get('name', 'پیام‌رسان‌ها')}",
            outcome='call_back'
        )
        db.session.add(interaction)
        db.session.commit()
        return True

    @classmethod
    def handle_owner_response(cls, property_id: int, response_code: str, platform: str = 'messenger', notes: str = None) -> dict:
        """
        پردازش پاسخ مالک و اعمال تغییرات روی وضعیت ملک در دیتابیس:
        - اگر ۱ یا available: تایید موجودی، صفر شدن تایمر ۷ روزه و بازگشت به فایل‌های فعال
        - اگر ۲ یا sold/archived: بایگانی قطعی ملک و خروج از چرخه فعال
        """
        prop = Property.query.get(property_id)
        if not prop:
            return {'success': False, 'error': 'ملک یافت نشد'}

        resp_clean = str(response_code).strip().lower()
        platform_name = cls.PLATFORMS.get(platform, {}).get('name', platform)

        if resp_clean in ['1', 'available', 'موجود', 'active']:
            prop.reactivate()
            summary = f"پاسخ مالک از {platform_name}: ملک کماکان موجود است. تمدید دوره ۷ روزه و بازگشت به لیست فعال."
            outcome = 'interested'
            status_result = 'available'
            user_msg = 'موجودی ملک تایید شد؛ تایمر ۷ روزه صفر شد و فایل در لیست املاک فعال قرار گرفت.'
        elif resp_clean in ['2', 'sold', 'واگذار', 'archived', 'فروخته']:
            prop.archive(reason='sold')
            summary = f"پاسخ مالک از {platform_name}: ملک واگذار یا فروخته شده است. بایگانی قطعی از چرخه فعال."
            outcome = 'rejected'
            status_result = 'archived'
            user_msg = 'ملک به عنوان واگذارشده/ناموجود ثبت گردید و به صورت قطعی بایگانی شد.'
        else:
            summary = f"پاسخ متفرقه مالک از {platform_name}: {notes or response_code}"
            outcome = 'call_back'
            status_result = prop.status
            user_msg = 'پاسخ مالک ثبت شد.'

        # ثبت در جدول تعاملات
        interaction = Interaction(
            type='whatsapp',
            target_type='owner',
            owner_id=prop.owner_id,
            property_id=prop.id,
            summary=summary,
            outcome=outcome
        )
        db.session.add(interaction)
        db.session.commit()

        return {
            'success': True,
            'property_id': prop.id,
            'status': status_result,
            'inquiry_status': prop.inquiry_status,
            'message': user_msg
        }
