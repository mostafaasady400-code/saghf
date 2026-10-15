"""Private, office-scoped Telegram CRM views and one-use follow-up actions."""
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit

from sqlalchemy import case, or_
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from database.db import db
from database.models import Agent, Client, Interaction, MatchRecord, Property, Visit
from telegram_bot.office_access import OfficeAction, OfficeMembership, principal_for

log = logging.getLogger(__name__)
TODAY = 'میزکار امروز'
CLIENTS = 'مشتریان'
PROPERTIES = 'فایل‌های ملک'
MATCHES = 'تطبیق هوشمند'
FOLLOWUPS = 'پیگیری و بازدید'
REPORTS = 'دفتر و گزارش‌ها'
MENU = (TODAY, CLIENTS, PROPERTIES, MATCHES, FOLLOWUPS, REPORTS)
CANCEL = 'لغو عملیات'
PAGE_SIZE = 5
TEHRAN = timezone(timedelta(hours=3, minutes=30))
STATUS_LABELS = {'available': 'موجود', 'reserved': 'رزرو', 'sold': 'واگذار شده',
                 'archived': 'بایگانی', 'needs_followup': 'نیازمند پیگیری',
                 'raw_crawled': 'بررسی نشده', 'verified': 'تأیید شده'}
ACTION_TTL = timedelta(minutes=30)
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _safe(value, limit=700):
    return escape(str(value if value is not None else 'ثبت نشده')[:limit])


def _when(value):
    if value is None:
        return 'ثبت نشده'
    return value.replace(tzinfo=timezone.utc).astimezone(TEHRAN).strftime('%Y-%m-%d %H:%M')


def _link(url):
    try:
        parsed = urlsplit(url or '')
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password:
            return '\n<a href="' + escape(url, quote=True) + '">لینک آگهی</a>'
    except ValueError:
        pass
    return ''


def office_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2, is_persistent=False, one_time_keyboard=False)
    for offset in range(0, len(MENU), 2):
        markup.row(*(KeyboardButton(label) for label in MENU[offset:offset + 2]))
    markup.row(KeyboardButton('پنل مشتری'))
    return markup


def _inline(rows=()):
    markup = InlineKeyboardMarkup(row_width=2)
    for row in rows:
        markup.row(*(InlineKeyboardButton(text=label, callback_data=data) for label, data in row))
    return markup


class OfficeFlow:
    def __init__(self, bot, app_provider):
        self.bot, self.app_provider = bot, app_provider

    @staticmethod
    def _private(message, user=None):
        user = user or getattr(message, 'from_user', None)
        return bool(message and user and not user.is_bot and message.chat.type == 'private'
                    and str(message.chat.id) == str(user.id))

    def enabled(self, message):
        if not self._private(message):
            return False
        text = (message.text or '').strip()
        if text.split(' ', 1)[0] == '/office' or text == 'میزکار املاک':
            return True
        if text in ('/start', '/customer', 'پنل مشتری'):
            try:
                with self.app_provider().app_context():
                    principal = principal_for(message.from_user.id)
                    if principal:
                        OfficeMembership.query.filter_by(id=principal.membership_id).update({'panel_mode': 'customer'})
                        db.session.commit()
            except Exception:
                log.warning('Office panel switch unavailable', exc_info=False)
            return False
        if text.startswith('/start ') or (text.startswith('/') and text not in ('/start', '/help', '/cancel', '/menu')):
            return False
        try:
            with self.app_provider().app_context():
                principal = principal_for(message.from_user.id)
                if not principal:
                    return text in (*MENU, CANCEL)
                member = db.session.get(OfficeMembership, principal.membership_id)
                return member.panel_mode != 'customer'
        except Exception:
            log.warning('Office routing unavailable', exc_info=False)
            return False

    @staticmethod
    def clients(principal):
        return Client.query.filter(Client.assigned_agent_id.in_(principal.agent_ids))

    @staticmethod
    def properties(principal):
        return Property.query.filter(Property.assigned_agent_id.in_(principal.agent_ids))

    def interactions(self, principal):
        return Interaction.query.filter(
            Interaction.client_id.in_(self.clients(principal).with_entities(Client.id)),
            or_(Interaction.property_id.is_(None), Interaction.property_id.in_(self.properties(principal).with_entities(Property.id))),
            or_(Interaction.agent_id.is_(None), Interaction.agent_id.in_(principal.agent_ids)))

    def visits(self, principal):
        return Visit.query.filter(
            Visit.client_id.in_(self.clients(principal).with_entities(Client.id)),
            Visit.property_id.in_(self.properties(principal).with_entities(Property.id)),
            or_(Visit.agent_id.is_(None), Visit.agent_id.in_(principal.agent_ids)))

    def matches(self, principal):
        return MatchRecord.query.filter(
            MatchRecord.client_id.in_(self.clients(principal).with_entities(Client.id)),
            or_(MatchRecord.property_id.is_(None), MatchRecord.property_id.in_(self.properties(principal).with_entities(Property.id))))

    def _send(self, chat_id, text, rows=None, menu=False):
        self.bot.send_message(chat_id, text, parse_mode='HTML', disable_web_page_preview=True,
                              reply_markup=office_keyboard() if menu else _inline(rows or [[('میزکار', 'office:today')]]))

    def _deny(self, chat_id):
        self._send(chat_id, 'دسترسی به پنل املاک یا این پرونده مجاز نیست. عضویت فعال و تخصیص صریح پرونده لازم است.', rows=[])

    def _cancel(self, principal):
        OfficeAction.query.filter_by(membership_id=principal.membership_id, consumed=False).update(
            {'consumed': True, 'stage': 'cancelled'}, synchronize_session=False)
        db.session.commit()

    def handle(self, message):
        if not self._private(message):
            return
        try:
            with self.app_provider().app_context():
                principal = principal_for(message.from_user.id)
                if not principal:
                    return self._deny(message.chat.id)
                text = (message.text or '').strip()
                if text in ('/cancel', '/menu', CANCEL):
                    from telegram_bot.operations import restore_menu_button
                    restore_menu_button(self.bot, message.chat.id)
                    self._cancel(principal)
                    return self.today(message.chat.id, principal)
                routes = {CLIENTS: lambda: self.list_clients(message.chat.id, principal),
                          PROPERTIES: lambda: self.list_properties(message.chat.id, principal),
                          MATCHES: lambda: self.list_matches(message.chat.id, principal),
                          FOLLOWUPS: lambda: self.followups(message.chat.id, principal),
                          REPORTS: lambda: self.reports(message.chat.id, principal)}
                if text in (TODAY, '/office', 'میزکار املاک', '/start', '/help'):
                    from telegram_bot.operations import restore_menu_button
                    restore_menu_button(self.bot, message.chat.id)
                    OfficeMembership.query.filter_by(id=principal.membership_id).update({'panel_mode': 'office'})
                    self._cancel(principal)
                    return self.today(message.chat.id, principal)
                if text in routes:
                    self._cancel(principal)
                    return routes[text]()
                action = (OfficeAction.query.filter_by(membership_id=principal.membership_id, consumed=False, stage='input')
                          .filter(OfficeAction.expires_at > datetime.utcnow())
                          .order_by(OfficeAction.created_at.desc()).first())
                if action:
                    return self.input_action(message.chat.id, principal, action, text)
                self._send(message.chat.id, 'یکی از بخش‌های پنل را انتخاب کنید. برای شروع دوباره /office را بفرستید.', menu=True)
        except Exception as exc:
            with self.app_provider().app_context():
                from telegram_bot.telemetry import record_event
                record_event('office_error')
            log.warning('Office message failed: %s', type(exc).__name__)
            self._send(message.chat.id, 'خواندن یا ثبت اطلاعات انجام نشد؛ عملیات را دوباره بررسی کنید. تغییر ناقص ثبت نمی‌شود.', menu=True)

    def callback(self, call):
        message, user = getattr(call, 'message', None), getattr(call, 'from_user', None)
        try:
            self.bot.answer_callback_query(call.id)
        except Exception:
            pass
        if not self._private(message, user):
            return
        data = getattr(call, 'data', '') or ''
        if not data.startswith('office:') or len(data) > 64:
            return
        try:
            with self.app_provider().app_context():
                principal = principal_for(user.id)
                if not principal:
                    return self._deny(message.chat.id)
                parts = data.split(':')
                command, args = parts[1], parts[2:]
                if command in ('today', 'reports', 'cancel') and not args:
                    if command == 'cancel':
                        self._cancel(principal)
                    return self.reports(message.chat.id, principal) if command == 'reports' else self.today(message.chat.id, principal)
                if command in ('clients', 'properties', 'matches', 'followups', 'overdue', 'visits') and len(args) == 1:
                    page = int(args[0])
                    if not 0 <= page <= 100000:
                        raise ValueError('invalid_page')
                    routes = {'clients': self.list_clients, 'properties': self.list_properties,
                              'matches': self.list_matches, 'followups': self.followups, 'visits': self.list_visits,
                              'overdue': lambda chat, principal, page: self.followups(chat, principal, page, overdue_only=True)}
                    return routes[command](message.chat.id, principal, page)
                if command in ('client', 'property') and len(args) == 1:
                    target_id = self._id(args[0])
                    return (self.client_detail if command == 'client' else self.property_detail)(message.chat.id, principal, target_id)
                if command in ('call', 'remind', 'resolve', 'visit_offer') and len(args) == 1:
                    return self.start_action(message.chat.id, principal, command, self._id(args[0]))
                if command == 'visit_status' and len(args) == 2 and args[1] in ('completed', 'cancelled', 'no_show'):
                    return self.start_action(message.chat.id, principal, 'visit_status', self._id(args[0]), args[1])
                if command == 'status' and len(args) == 2 and args[1] in STATUS_LABELS:
                    if args[1] not in ('available', 'reserved', 'sold', 'archived', 'needs_followup'):
                        raise ValueError('invalid_status')
                    return self.start_action(message.chat.id, principal, 'status', self._id(args[0]), args[1])
                if command == 'confirm' and len(args) == 1 and re.fullmatch('[0-9a-f]{24}', args[0]):
                    return self.confirm_action(message.chat.id, principal, args[0])
                raise ValueError('invalid_callback')
        except (ValueError, PermissionError):
            self._deny(message.chat.id)
        except Exception as exc:
            with self.app_provider().app_context():
                from telegram_bot.telemetry import record_event
                record_event('office_error')
            log.warning('Office callback failed: %s', type(exc).__name__)
            self._send(message.chat.id, 'عملیات انجام نشد؛ از میزکار دوباره تلاش کنید. تغییر ناقص ثبت نمی‌شود.')

    @staticmethod
    def _id(value):
        if not value.isascii() or not value.isdigit() or not 0 < int(value) < 2 ** 63:
            raise ValueError('invalid_id')
        return int(value)

    def today(self, chat_id, principal):
        now = datetime.utcnow()
        local_day = now.replace(tzinfo=timezone.utc).astimezone(TEHRAN).date()
        start = datetime.combine(local_day, datetime.min.time(), TEHRAN).astimezone(timezone.utc).replace(tzinfo=None)
        end = start + timedelta(days=1)
        interactions = self.interactions(principal)
        pending = interactions.filter(Interaction.outcome == 'pending').count()
        overdue = interactions.filter(Interaction.next_followup_date <= now, Interaction.outcome.in_(('pending', 'call_back'))).count()
        visits_today = self.visits(principal).filter(Visit.scheduled_time >= start, Visit.scheduled_time < end, Visit.status == 'scheduled').count()
        active_files = self.properties(principal).filter(Property.status.in_(('available', 'verified'))).count()
        open_clients = self.clients(principal).filter(~Client.lead_status.in_(('contract_won', 'lost'))).count()
        self._send(chat_id, f'پنل املاک | {_safe(principal.office_key)}\n'
                   f"دسترسی: {'مدیر همین دفتر' if principal.office_role == 'manager' else 'فقط پرونده‌های خودتان'}\n\n"
                   f'مشتریان فعال: {open_clients}\nفایل‌های فعال: {active_files}\nپیگیری عقب‌افتاده: {overdue}\n'
                   f'درخواست‌های در انتظار رسیدگی: {pending}\nبازدید قطعی امروز: {visits_today}\n'
                   'تمام شمارش‌ها از CRM و فقط در محدوده دسترسی شماست. ساعت‌ها به وقت تهران نمایش داده می‌شود.\nاعلان خودکار خاموش است؛ کارهای امروز را همین‌جا بررسی کنید.', menu=True)
        self._send(chat_id, 'دسترسی سریع به کارهای امروز', [[('پیگیری‌های عقب‌افتاده', 'office:overdue:0'), ('بازدیدها', 'office:visits:0')], [('درخواست‌های منتظر رسیدگی', 'office:followups:0')],
            [('مشتریان', 'office:clients:0'), ('تطبیق هوشمند', 'office:matches:0')]])

    @staticmethod
    def _page_rows(query, page):
        total = query.count()
        page = min(page, max(0, (total - 1) // PAGE_SIZE))
        return query.offset(page * PAGE_SIZE).limit(PAGE_SIZE).all(), total, page

    @staticmethod
    def _navigation(namespace, page, total):
        row = []
        if page:
            row.append(('قبلی', f'office:{namespace}:{page - 1}'))
        if (page + 1) * PAGE_SIZE < total:
            row.append(('بعدی', f'office:{namespace}:{page + 1}'))
        return ([row] if row else []) + [[('میزکار', 'office:today')]]

    def list_clients(self, chat_id, principal, page=0):
        records, total, page = self._page_rows(self.clients(principal).order_by(Client.updated_at.desc(), Client.id.desc()), page)
        lines, rows = [f'مشتریان | {total} پرونده | صفحه {page + 1}'], []
        for row in records:
            lines.append(f'#{row.id} · {_safe(row.full_name, 90)} · {_safe(row.lead_status, 30)}')
            rows.append([(f'پرونده مشتری #{row.id}', f'office:client:{row.id}')])
        self._send(chat_id, '\n'.join(lines) if records else 'هنوز مشتری تخصیص‌یافته‌ای در این بخش ندارید.', rows + self._navigation('clients', page, total))

    def client_detail(self, chat_id, principal, target_id):
        client = self.clients(principal).filter(Client.id == target_id).first()
        if not client:
            raise PermissionError('client_out_of_scope')
        recent = self.interactions(principal).filter(Interaction.client_id == client.id).order_by(Interaction.created_at.desc()).limit(3).all()
        text = (f'پرونده مشتری #{client.id}\n{_safe(client.full_name)}\nشماره: {_safe(client.phone_number, 40)}\n'
                f"نوع نیاز: {'خرید' if client.preferred_deal_type == 'sale' else 'رهن و اجاره'}\n"
                f'محدوده: {_safe("، ".join(client.preferred_districts or []), 180)}\n'
                f'متراژ: {client.min_area or 0} تا {client.max_area or 0}\nخواب: {client.min_rooms or 0}\n'
                f'بودجه خرید: {client.max_budget or 0:,} | ودیعه: {client.max_deposit or 0:,} | اجاره: {client.max_rent or 0:,} تومان\n'
                f'وضعیت: {_safe(client.lead_status)}')
        for item in recent:
            text += f'\n\n{_when(item.created_at)} · {_safe(item.type, 30)}\n{_safe(item.summary, 300)}'
        self._send(chat_id, text, [[('ثبت تماس', f'office:call:{client.id}'), ('ثبت یادآوری', f'office:remind:{client.id}')],
                                  [('مشتریان', 'office:clients:0'), ('میزکار', 'office:today')]])

    def list_properties(self, chat_id, principal, page=0):
        records, total, page = self._page_rows(self.properties(principal).order_by(Property.updated_at.desc(), Property.id.desc()), page)
        lines, rows = [f'فایل‌های ملک | {total} فایل | صفحه {page + 1}'], []
        for row in records:
            lines.append(f'#{row.id} · {_safe(row.title, 100)} · {_safe(STATUS_LABELS.get(row.status, row.status), 30)}')
            rows.append([(f'مشاهده فایل #{row.id}', f'office:property:{row.id}')])
        self._send(chat_id, '\n'.join(lines) if records else 'هنوز فایل ملکی تخصیص‌یافته‌ای ندارید.', rows + self._navigation('properties', page, total))

    def property_detail(self, chat_id, principal, target_id):
        prop = self.properties(principal).filter(Property.id == target_id).first()
        if not prop:
            raise PermissionError('property_out_of_scope')
        text = (f'فایل #{prop.id}\n{_safe(prop.title)}\nمحدوده: {_safe(prop.district)}\n'
                f'متراژ: {prop.area} | خواب: {prop.rooms}\nوضعیت: {_safe(STATUS_LABELS.get(prop.status, prop.status))}\n'
                f'قیمت خرید: {prop.total_price or 0:,} | ودیعه: {prop.deposit or 0:,} | اجاره: {prop.monthly_rent or 0:,} تومان\n'
                f'آخرین تغییر: {_when(prop.updated_at)}' + _link(prop.source_url))
        statuses = ('available', 'reserved', 'sold', 'archived', 'needs_followup')
        buttons = [(STATUS_LABELS[status], f'office:status:{prop.id}:{status}') for status in statuses]
        rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
        self._send(chat_id, text, rows + [[('فایل‌های ملک', 'office:properties:0'), ('میزکار', 'office:today')]])

    def list_matches(self, chat_id, principal, page=0):
        records, total, page = self._page_rows(self.matches(principal).order_by(MatchRecord.created_at.desc(), MatchRecord.id.desc()), page)
        lines, rows = [f'تطبیق‌های ثبت‌شده واقعی | {total} مورد | صفحه {page + 1}'], []
        for match in records:
            lines.append(f'\nمشتری #{match.client_id} · امتیاز ثبت‌شده: {match.match_score}\n{_safe(match.item_title, 130)}')
            if match.property_id:
                rows.append([(f'فایل #{match.property_id}', f'office:property:{match.property_id}'),
                             (f'مشتری #{match.client_id}', f'office:client:{match.client_id}')])
                lines[-1] += _link(match.property.source_url)
            elif match.listing:
                lines[-1] += _link(getattr(match.listing, 'source_url', None) or getattr(match.listing, 'url', None))
                rows.append([(f'مشتری #{match.client_id}', f'office:client:{match.client_id}')])
        self._send(chat_id, '\n'.join(lines) if records else 'هنوز تطبیق ثبت‌شده‌ای در محدوده شما نیست؛ پیشنهاد ساختگی نمایش داده نمی‌شود.',
                   rows + self._navigation('matches', page, total))

    def followups(self, chat_id, principal, page=0, overdue_only=False):
        query = self.interactions(principal).filter(Interaction.outcome.in_(('pending', 'call_back')))
        if overdue_only:
            query = query.filter(Interaction.next_followup_date <= datetime.utcnow())
        records, total, page = self._page_rows(query.order_by(case((Interaction.next_followup_date <= datetime.utcnow(),0),else_=1),Interaction.next_followup_date.asc(),Interaction.id.desc()), page)
        lines, rows = [f'{"پیگیری‌های عقب‌افتاده" if overdue_only else "پیگیری و درخواست‌ها"} | {total} مورد | صفحه {page + 1}'], []
        labels = {'saghf_support': 'درخواست پشتیبانی', 'saghf_visit': 'درخواست هماهنگی بازدید',
                  'office_reminder': 'یادآوری', 'call': 'تماس'}
        for item in records:
            lines.append(f'\n#{item.id} · {_safe(labels.get(item.type, item.type), 50)} · مشتری #{item.client_id}\n'
                         f'{_safe(item.summary, 250)}\nموعد: {_when(item.next_followup_date)} | {_safe(item.outcome, 30)}')
            from telegram_bot.decision_support import DecisionStore
            preference=DecisionStore().preference(item.id)
            if preference:
                starts,ends=[datetime.fromisoformat(value).astimezone(TEHRAN) for value in preference]
                lines.append(f'ترجیح زمانی مشتری: {starts:%Y/%m/%d %H:%M} تا {ends:%H:%M} تهران؛ قطعی نیست.')
            row = [(f'مشتری #{item.client_id}', f'office:client:{item.client_id}')]
            if item.outcome in ('pending', 'call_back'):
                row.append(('ثبت رسیدگی', f'office:resolve:{item.id}'))
            if item.type == 'saghf_visit' and item.outcome == 'pending' and item.property_id:
                rows.append([('پیشنهاد زمان بازدید', f'office:visit_offer:{item.id}')])
            rows.append(row)
        if not records:
            lines.append('پیگیری یا درخواست در انتظاری برای پرونده‌های شما ثبت نشده است.')
        lines.append('\nدرخواست بازدید مشتری صرفاً درخواست هماهنگی است؛ بازدید قطعی محسوب نمی‌شود.')
        self._send(chat_id, '\n'.join(lines), rows + [[('همه پیگیری‌های باز', 'office:followups:0'), ('بازدیدهای قطعی CRM', 'office:visits:0')]] + self._navigation('overdue' if overdue_only else 'followups', page, total))

    def list_visits(self, chat_id, principal, page=0):
        records, total, page = self._page_rows(self.visits(principal).order_by(case((Visit.status == 'scheduled',0),else_=1),case((Visit.status == 'scheduled',Visit.scheduled_time),else_=None).asc(),Visit.scheduled_time.desc(),Visit.id.desc()), page)
        lines, rows = [f'بازدیدهای واقعی CRM | {total} مورد | صفحه {page + 1}'], []
        for item in records:
            lines.append(f'#{item.id} · {_when(item.scheduled_time)} · {_safe(item.status, 30)}\n'
                         f'مشتری #{item.client_id} | فایل #{item.property_id}')
            rows.append([(f'مشتری #{item.client_id}', f'office:client:{item.client_id}'),
                         (f'فایل #{item.property_id}', f'office:property:{item.property_id}')])
            if item.status == 'scheduled':
                rows.append([('لغو بازدید', f'office:visit_status:{item.id}:cancelled')])
                if item.scheduled_time <= datetime.utcnow():
                    rows.append([('انجام شد', f'office:visit_status:{item.id}:completed'),
                                 ('عدم حضور', f'office:visit_status:{item.id}:no_show')])
        self._send(chat_id, '\n'.join(lines) if records else 'هیچ بازدید قطعی در CRM برای محدوده شما ثبت نشده است.',
                   rows + [[('پیگیری‌ها', 'office:followups:0')]] + self._navigation('visits', page, total))

    def reports(self, chat_id, principal):
        text = (f'دفتر و گزارش‌ها | {_safe(principal.office_key)}\n'
                f'مشتریان: {self.clients(principal).count()}\nفایل‌ها: {self.properties(principal).count()}\n'
                f'تطبیق‌های ثبت‌شده: {self.matches(principal).count()}\nبازدیدهای ثبت‌شده: {self.visits(principal).count()}')
        if principal.office_role == 'manager':
            text += '\n\nمشاوران فعال همین دفتر:'
            for agent in Agent.query.filter(Agent.id.in_(principal.agent_ids)).order_by(Agent.id).limit(30).all():
                client_count = self.clients(principal).filter(Client.assigned_agent_id == agent.id).count()
                property_count = self.properties(principal).filter(Property.assigned_agent_id == agent.id).count()
                text += f'\n{_safe(agent.name, 80)} · {client_count} مشتری · {property_count} فایل'
        else:
            text += '\nاین گزارش فقط پرونده‌های تخصیص‌یافته به خودتان را شامل می‌شود.'
        text += '\nمدیریت کاربران کل سامانه و تنظیمات فنی در این پنل در دسترس نیست.'
        self._send(chat_id, text, [[('میزکار', 'office:today')]])

    def _target(self, principal, kind, target_id):
        if kind in ('call', 'remind'):
            target = self.clients(principal).filter(Client.id == target_id).with_for_update().first()
        elif kind == 'status':
            target = self.properties(principal).filter(Property.id == target_id).with_for_update().first()
        elif kind in ('resolve', 'visit_offer'):
            target = self.interactions(principal).filter(Interaction.id == target_id).with_for_update().first()
        elif kind == 'visit_status':
            target = self.visits(principal).filter(Visit.id == target_id).with_for_update().first()
        else:
            raise ValueError('unknown_action')
        if not target:
            raise PermissionError('target_out_of_scope')
        return target

    def start_action(self, chat_id, principal, kind, target_id, status=None):
        target = self._target(principal, kind, target_id)
        if kind == 'resolve' and target.outcome not in ('pending', 'call_back'):
            return self._send(chat_id, 'این مورد قبلاً رسیدگی شده است.')
        payload = {'office_key': principal.office_key, 'actor_agent_id': principal.agent_id}
        if kind == 'status':
            payload.update(status=status, previous=target.status)
        if kind == 'resolve':
            payload['previous'] = target.outcome
        if kind == 'visit_offer' and (target.type != 'saghf_visit' or target.outcome != 'pending' or not target.property_id):
            raise ValueError('visit_request_required')
        if kind == 'visit_status':
            if target.status != 'scheduled' or status not in ('completed', 'cancelled', 'no_show'):
                raise ValueError('invalid_visit_status')
            if status != 'cancelled' and target.scheduled_time > datetime.utcnow():
                raise ValueError('visit_not_due')
            payload.update(status=status, previous=target.status)
        # Opening another form invalidates all older uncommitted actions for this member.
        OfficeAction.query.filter_by(membership_id=principal.membership_id, consumed=False).update(
            {'consumed': True, 'stage': 'cancelled'}, synchronize_session=False)
        action = OfficeAction(token=secrets.token_hex(12), membership_id=principal.membership_id,
                              kind=kind, target_id=target_id, payload=json.dumps(payload, ensure_ascii=False),
                              stage='input' if kind in ('call', 'remind', 'visit_offer') else 'confirm',
                              expires_at=datetime.utcnow() + ACTION_TTL)
        db.session.add(action)
        db.session.commit()
        if kind == 'call':
            return self._send(chat_id, 'خلاصه و نتیجه تماس را در یک پیام بنویسید (۳ تا ۱۰۰۰ نویسه).\nتا تأیید نهایی، تماسی ثبت نمی‌شود.',
                              [[('لغو', 'office:cancel')]])
        if kind in ('remind', 'visit_offer'):
            return self._send(chat_id, 'تاریخ میلادی، ساعت تهران و توضیح را در یک پیام بنویسید:\n'
                              '<code>YYYY-MM-DD HH:MM | توضیح پیگیری</code>\n'
                              + ('زمان بازدید باید تا ۶۰ روز آینده باشد؛ مشتری نیز باید زمان را تأیید کند.' if kind == 'visit_offer' else
                               'موعد باید در آینده و حداکثر تا یک سال دیگر باشد؛ تا تأیید نهایی ثبت نمی‌شود.'),
                              [[('لغو', 'office:cancel')]])
        return self._confirmation(chat_id, action)

    def _confirmation(self, chat_id, action):
        payload = json.loads(action.payload)
        if action.kind == 'status':
            text = f'تغییر وضعیت واقعی فایل #{action.target_id} به «{STATUS_LABELS[payload["status"]]}» را تأیید می‌کنید؟'
        elif action.kind == 'resolve':
            text = f'رسیدگی به پیگیری #{action.target_id} ثبت شود؟\nاین اقدام بازدید قطعی ایجاد نمی‌کند.'
        elif action.kind == 'visit_status':
            text = f'وضعیت بازدید #{action.target_id} به «{_safe(payload["status"])}» تغییر کند؟'
        elif action.kind == 'visit_offer':
            text = f'زمان بازدید درخواست #{action.target_id}: {_when(datetime.fromisoformat(payload["date"]))} تهران\nبرای مشاهده و تأیید مشتری در «پیگیری و بازدید» ثبت شود؟ هیچ اعلان خودکاری ارسال نمی‌شود؛ بازدید هنوز قطعی نیست.'
        elif action.kind == 'remind':
            text = f'یادآوری مشتری #{action.target_id}\nموعد تهران: {_when(datetime.fromisoformat(payload["date"]))}\n{_safe(payload["summary"], 1000)}\nثبت شود؟'
        else:
            text = f'ثبت تماس مشتری #{action.target_id}\n{_safe(payload["summary"], 1000)}\nتأیید می‌کنید؟'
        self._send(chat_id, text, [[('تأیید ثبت', f'office:confirm:{action.token}'), ('لغو', 'office:cancel')]])

    def input_action(self, chat_id, principal, action, text):
        self._target(principal, action.kind, action.target_id)
        payload = json.loads(action.payload)
        if payload.get('office_key') != principal.office_key or payload.get('actor_agent_id') != principal.agent_id:
            raise PermissionError('membership_changed')
        try:
            summary = text.strip()
            if action.kind in ('remind', 'visit_offer'):
                date_text, summary = text.split('|', 1)
                local_date = datetime.strptime(date_text.strip().translate(DIGITS), '%Y-%m-%d %H:%M').replace(tzinfo=TEHRAN)
                due = local_date.astimezone(timezone.utc).replace(tzinfo=None)
                if not datetime.utcnow() < due <= datetime.utcnow() + timedelta(days=60 if action.kind == 'visit_offer' else 365):
                    raise ValueError('date_range')
                payload['date'] = due.isoformat()
            summary = summary.strip()
            if not 3 <= len(summary) <= 1000 or any(ord(char) < 32 and char not in '\n\t' for char in summary):
                raise ValueError('invalid_summary')
            payload['summary'] = summary
        except (ValueError, TypeError):
            return self._send(chat_id, 'ورودی معتبر نیست. توضیح باید ۳ تا ۱۰۰۰ نویسه باشد؛ یادآوری باید با قالب '
                              '<code>YYYY-MM-DD HH:MM | توضیح</code> و موعد آینده به وقت تهران ارسال شود.',
                              [[('لغو', 'office:cancel')]])
        action.payload, action.stage = json.dumps(payload, ensure_ascii=False), 'confirm'
        db.session.commit()
        self._confirmation(chat_id, action)

    def confirm_action(self, chat_id, principal, token):
        action = OfficeAction.query.filter_by(token=token, membership_id=principal.membership_id).first()
        if not action:
            raise PermissionError('foreign_confirmation')
        target = self._target(principal, action.kind, action.target_id)
        if action.consumed:
            return self._send(chat_id, 'این عملیات قبلاً ثبت یا لغو شده است؛ ثبت تکراری انجام نشد.')
        if action.stage != 'confirm' or action.expires_at <= datetime.utcnow():
            return self._send(chat_id, 'مهلت یا مرحله تأیید معتبر نیست؛ عملیات را از پرونده دوباره شروع کنید.')
        payload = json.loads(action.payload)
        if payload.get('office_key') != principal.office_key or payload.get('actor_agent_id') != principal.agent_id:
            raise PermissionError('membership_changed')
        if action.kind in ('remind', 'visit_offer') and datetime.fromisoformat(payload['date']) <= datetime.utcnow():
            return self._send(chat_id, 'موعد یادآوری گذشته است؛ دوباره با زمان آینده ثبت کنید.')
        # Atomic claim: two workers/replayed callbacks can never commit the same action twice.
        claimed = OfficeAction.query.filter_by(token=token, membership_id=principal.membership_id,
                                               consumed=False, stage='confirm').filter(
            OfficeAction.expires_at > datetime.utcnow()).update({'consumed': True, 'stage': 'done'}, synchronize_session=False)
        if claimed != 1:
            db.session.rollback()
            return self._send(chat_id, 'این عملیات قبلاً رسیدگی شده است.')
        if action.kind == 'status':
            changed = self.properties(principal).filter(Property.id == target.id, Property.status == payload['previous']).update(
                {'status': payload['status'], 'updated_at': datetime.utcnow()}, synchronize_session=False)
            if changed != 1:
                raise ValueError('property_changed')
        elif action.kind == 'resolve':
            changed = self.interactions(principal).filter(Interaction.id == target.id, Interaction.outcome == payload['previous']).update(
                {'outcome': 'resolved', 'next_followup_date': None}, synchronize_session=False)
            if changed != 1:
                raise ValueError('interaction_changed')
        elif action.kind == 'visit_offer':
            from telegram_bot.workflow import offer_visit
            offer_visit(principal, target, datetime.fromisoformat(payload['date']))
        elif action.kind == 'visit_status':
            if payload['status'] != 'cancelled' and target.scheduled_time > datetime.utcnow():
                raise ValueError('visit_not_due')
            changed = self.visits(principal).filter(Visit.id == target.id, Visit.status == payload['previous']).update(
                {'status': payload['status']}, synchronize_session=False)
            if changed != 1:
                raise ValueError('visit_changed')
            if payload['status'] == 'completed':
                from telegram_bot.workflow import customer_for_client, enqueue_message
                try:
                    lead = customer_for_client(target.client_id)
                except ValueError:
                    lead = None
                if lead:
                    enqueue_message(f'visit_review:{target.id}', lead.contact_key.split(':')[1], 'visit_review', target.id,
                        f'بازدید #{target.id} انجام‌شده ثبت شد. نتیجه برای شما چگونه بود؟',
                        [[('پسندیدم', f'workflow:liked:{target.id}'), ('مناسب نبود', f'workflow:not_suitable:{target.id}')]])
        else:
            db.session.add(Interaction(type='call' if action.kind == 'call' else 'office_reminder',
                                       target_type='client', target_id=target.id, client_id=target.id,
                                       agent_id=principal.agent_id, summary=payload['summary'],
                                       outcome='recorded' if action.kind == 'call' else 'pending',
                                       next_followup_date=datetime.fromisoformat(payload['date']) if action.kind == 'remind' else None))
        from telegram_bot.workflow import audit
        audit(principal.telegram_id, 'office_'+action.kind, target.id, state=payload.get('status'), agent_id=principal.agent_id)
        db.session.commit()
        self._send(chat_id, 'ثبت شد. عملیات تکراری دوباره ثبت نمی‌شود.',
                   [[('پیگیری‌ها', 'office:followups:0'), ('میزکار', 'office:today')]])


def register_office_flow(bot, app_provider):
    """Register before CustomerFlow; callbacks always re-check the database principal."""
    flow = OfficeFlow(bot, app_provider)
    bot.register_message_handler(flow.handle, func=flow.enabled, content_types=['text'])
    bot.register_callback_query_handler(flow.callback, func=lambda call: (getattr(call, 'data', '') or '').startswith('office:'))
    return flow
