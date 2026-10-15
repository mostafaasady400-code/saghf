"""Telegram is pull-only: human request, same private chat, no background sends."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import telebot

_request_chat = ContextVar('telegram_request_chat', default=None)
_matching = ContextVar('telegram_matching_response', default=False)
_authorized_delivery = ContextVar('telegram_explicit_delivery', default=None)
POLICY_ERROR = 'telegram_automatic_delivery_disabled'


def automatic_sends_allowed():
    # Deliberately not configurable by environment, worker, admin or test mode.
    return False


@contextmanager
def human_request(message):
    user = getattr(message, 'from_user', None)
    chat = getattr(message, 'chat', None)
    recipient = str(chat.id) if (user and not user.is_bot and chat and
        chat.type == 'private' and chat.id == user.id) else None
    token = _request_chat.set(recipient)
    intent = _matching.set(False)
    try:
        yield
    finally:
        _matching.reset(intent)
        _request_chat.reset(token)


def matching_response(function):
    """Only the on-demand matching renderer opens the property-media scope."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _matching.set(True)
        try:
            return function(*args, **kwargs)
        finally:
            _matching.reset(token)
    return wrapped


class ReplyOnlyTeleBot(telebot.TeleBot):
    def __init__(self, *args, **kwargs):
        kwargs['threaded'] = False
        super().__init__(*args, **kwargs)

    def process_new_messages(self, messages):
        for message in messages:
            with human_request(message):
                super().process_new_messages([message])

    def process_new_callback_query(self, queries):
        for query in queries:
            message = getattr(query, 'message', None)
            user = getattr(query, 'from_user', None)
            # The message author is the bot; the callback actor is the human.
            from types import SimpleNamespace
            request = SimpleNamespace(from_user=user, chat=getattr(message, 'chat', None))
            with human_request(request):
                super().process_new_callback_query([query])


def _guard(method, name):
    signature = inspect.signature(method)
    @wraps(method)
    def guarded(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        chat_id = bound.arguments.get('chat_id')
        recipient = _request_chat.get()
        delivery = _authorized_delivery.get()
        if recipient is None and delivery is not None:
            if str(chat_id) != str(delivery['recipient']):
                raise PermissionError(POLICY_ERROR)
            if delivery['kind'] == 'daily_update':
                if name != 'send_message' or bound.arguments.get('text') != delivery['text']:
                    raise PermissionError('daily_notice_text_only')
            elif delivery['kind'] == 'search_result':
                if name not in ('send_message', 'send_photo', 'edit_message_text'):
                    raise PermissionError('explicit_search_delivery_only')
            else:
                raise PermissionError(POLICY_ERROR)
            if delivery['calls'] >= 20:
                raise PermissionError('delivery_limit_reached')
            delivery['calls'] += 1
            return method(self, *args, **kwargs)
        if recipient is None or str(chat_id) != recipient:
            raise PermissionError(POLICY_ERROR)
        if name.startswith(('forward_', 'copy_')) or (name.startswith('send_') and
                name not in ('send_message', 'send_chat_action') and not _matching.get()):
            raise PermissionError('telegram_property_display_requires_matching')
        return method(self, *args, **kwargs)
    return guarded


# Guard every SDK send/copy/forward/edit entry, including future installed methods.
for _name in dir(telebot.TeleBot):
    if _name.startswith(('send_', 'forward_', 'copy_', 'edit_message_')):
        _method = getattr(telebot.TeleBot, _name)
        if callable(_method):
            setattr(ReplyOnlyTeleBot, _name, _guard(_method, _name))
