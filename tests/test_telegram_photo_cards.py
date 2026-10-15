"""Photo cards use actual CDN images; transport is mocked."""
from unittest.mock import MagicMock
from telegram_bot.customer_panel import card


def item():
    return dict(title='آپارتمان',district='پونک',area=80,rooms=2,deal_type='rent',
        deposit=3000000000,monthly_rent=100000000,source_type='archive',id=1,
        source_url='https://divar.ir/v/test/token',images=['https://s100.divarcdn.com/static/test.jpg'])


def test_real_cdn_photo_and_caption_are_displayed():
    bot = MagicMock()
    card(bot,777,item())
    bot.send_photo.assert_called_once()
    assert bot.send_photo.call_args.args[1]==item()['images'][0]
    assert 'نتیجه زنده نیست' in bot.send_photo.call_args.kwargs['caption']
    bot.send_message.assert_not_called()


def test_photo_failure_has_truthful_text_fallback():
    bot = MagicMock()
    bot.send_photo.side_effect = ConnectionError('offline')
    card(bot,777,item())
    assert 'تصویر در دسترس نبود' in bot.send_message.call_args.args[1]


def test_untrusted_or_relative_image_is_not_fabricated():
    bot = MagicMock()
    data = item()
    data['images'] = ['http://127.0.0.1/private.jpg','/static/local.jpg','https://divarcdn.com.evil.example/a.jpg']
    card(bot,777,data)
    bot.send_photo.assert_not_called()
    assert 'تصویر قابل نمایش در دسترس نیست' in bot.send_message.call_args.args[1]

