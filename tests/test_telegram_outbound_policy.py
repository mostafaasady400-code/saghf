"""No network: all Telegram transport calls are intercepted in these tests."""
from types import SimpleNamespace as N
from unittest.mock import MagicMock, patch
import pytest
from telebot import apihelper
from telebot.types import Message, CallbackQuery
from telegram_bot.outbound_policy import ReplyOnlyTeleBot, human_request, matching_response


def request():
    return N(from_user=N(id=777, is_bot=False), chat=N(id=777, type='private'))


@pytest.fixture
def bot():
    return ReplyOnlyTeleBot('123:UNIT_TEST_ONLY')


@pytest.mark.parametrize('method,args', [('send_message',(777,'text')), ('send_photo',(777,'photo')),
    ('send_document',(777,'doc')), ('send_media_group',(777,[])), ('forward_message',(777,888,1)),
    ('copy_message',(777,888,1)), ('edit_message_text',('text',))])
def test_no_background_transport_of_any_kind(bot, method, args):
    with patch.object(apihelper, '_make_request') as network:
        with pytest.raises(PermissionError): getattr(bot, method)(*args)
        network.assert_not_called()


def test_only_same_chat_reply_allowed_and_scope_expires(bot):
    with patch.object(apihelper, 'send_message', return_value={'message_id':1,'date':1,'chat':{'id':777,'type':'private'}}) as network:
        with human_request(request()):
            bot.send_message(777,'reply')
            with pytest.raises(PermissionError): bot.send_message(888,'cross user')
        with pytest.raises(PermissionError): bot.send_message(777,'late send')
        assert network.call_count == 1


def test_media_requires_explicit_matching_scope(bot):
    @matching_response
    def render(): bot.send_photo(777,'photo')
    with patch.object(apihelper,'send_photo', return_value={'message_id':1,'date':1,'chat':{'id':777,'type':'private'}}) as network:
        with human_request(request()):
            with pytest.raises(PermissionError): bot.send_photo(777,'photo')
            render()
            with pytest.raises(PermissionError): bot.send_photo(777,'photo')
        assert network.call_count == 1


def test_dispatcher_processes_each_human_update_in_own_scope(bot):
    seen=[]
    bot.send_message=MagicMock()
    @bot.message_handler(func=lambda message: True)
    def handler(message):
        from telegram_bot.outbound_policy import _request_chat
        seen.append(_request_chat.get())
    messages=[Message.de_json({'message_id':1,'date':1,'from':{'id':x,'is_bot':False,'first_name':'test'},'chat':{'id':x,'type':'private'},'text':'/menu'}) for x in (777,888)]
    bot.process_new_messages(messages)
    assert seen == ['777','888']
    from telegram_bot.outbound_policy import _request_chat
    assert _request_chat.get() is None


def test_adapter_and_notifier_do_not_even_acquire_sender():
    from services.omnichannel.telegram_adapter import TelegramAdapter
    from telegram_bot.notifier import send_property_alert, send_property_media_group
    adapter=TelegramAdapter()
    with patch.object(adapter,'_get_bot') as sender, patch('telegram_bot.notifier.get_bot') as notifier:
        assert adapter.send_text('777','text')['suppressed']
        assert adapter.send_property_package('777',{},'text')['suppressed']
        assert send_property_alert(N(),777) is False
        assert send_property_media_group(N(),777)['suppressed']
        sender.assert_not_called(); notifier.assert_not_called()


def test_callback_reply_scope_is_bound_to_actor(bot):
    from telegram_bot.outbound_policy import _request_chat
    seen=[]
    bot.register_callback_query_handler(lambda call: seen.append(_request_chat.get()), func=lambda call: True)
    call=CallbackQuery.de_json({'id':'q','chat_instance':'x','from':{'id':777,'is_bot':False,'first_name':'test'},
        'message':{'message_id':1,'date':1,'from':{'id':123,'is_bot':True,'first_name':'bot'},'chat':{'id':777,'type':'private'}},'data':'customer:home'})
    bot.process_new_callback_query([call])
    assert seen==['777'] and _request_chat.get() is None


def test_telegram_dispatcher_has_no_cross_platform_fallback():
    from services.omnichannel.dispatcher import omnichannel_dispatcher
    with patch.object(omnichannel_dispatcher,'get_adapter') as adapter:
        assert omnichannel_dispatcher.dispatch_to_lead(N(active_messenger='telegram'),[{}]) == []
        assert omnichannel_dispatcher.dispatch_direct_message('777','text')['suppressed']
        adapter.assert_not_called()


def test_administrator_alerts_and_owner_onboarding_are_disabled():
    from telegram_bot.admin_alerts import send_gold_property_alert, send_green_lead_alert
    from services.nurturing_engine import NurturingEngine
    with patch('telegram_bot.admin_alerts._get_bot') as sender:
        assert send_gold_property_alert(N(),target_chat_id='777') is False
        assert send_green_lead_alert(N(),target_chat_id='777') is False
        assert NurturingEngine.handle_owner_onboarding(N(),N())['suppressed']
        sender.assert_not_called()


def test_network_failure_closes_request_scope(bot):
    from telegram_bot.outbound_policy import _request_chat, _matching
    with patch.object(apihelper, 'send_message', side_effect=ConnectionError('offline')) as network:
        with pytest.raises(ConnectionError):
            with human_request(request()):
                bot.send_message(777, 'reply')
        assert _request_chat.get() is None and _matching.get() is False
        with pytest.raises(PermissionError):
            bot.send_message(777, 'background retry')
        assert network.call_count == 1


def test_failed_matching_renderer_does_not_leave_media_permission(bot):
    @matching_response
    def render():
        raise ValueError('render failed')
    with patch.object(apihelper, '_make_request') as network:
        with human_request(request()):
            with pytest.raises(ValueError):
                render()
            with pytest.raises(PermissionError):
                bot.send_photo(777, 'photo')
        network.assert_not_called()


def test_background_thread_cannot_inherit_human_send_permission(bot):
    from concurrent.futures import ThreadPoolExecutor
    with patch.object(apihelper, '_make_request') as network:
        with human_request(request()), ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(bot.send_message, 777, 'unsolicited')
            with pytest.raises(PermissionError):
                result.result(timeout=5)
        network.assert_not_called()


@pytest.mark.parametrize('actor,chat,kind', [(888,777,'private'), (777,777,'group')])
def test_foreign_or_group_context_cannot_send(bot, actor, chat, kind):
    event = N(from_user=N(id=actor,is_bot=False),chat=N(id=chat,type=kind))
    with patch.object(apihelper, '_make_request') as network:
        with human_request(event), pytest.raises(PermissionError):
            bot.send_message(chat, 'reply')
        network.assert_not_called()
