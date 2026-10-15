import pytest
from crawler.text_phone_miner import TextPhoneMiner

def test_standard_english_digits():
    text = "آپارتمان ۷۰ متری تخلیه، تماس با مالک مستقیم: 09123456780"
    res = TextPhoneMiner.mine_phone(text)
    assert res is not None
    assert res['phone'] == '09123456780'
    assert res['source'] == 'text_miner'

def test_persian_digits_with_dash():
    text = "فروش فوری توسط مالک شخصی شماره تماس: ۰۹۱۲-۹۸۷-۶۵۴۳"
    res = TextPhoneMiner.mine_phone(text)
    assert res is not None
    assert res['phone'] == '09129876543'

def test_obfuscated_with_letter_o():
    text = "جهت هماهنگی بازدید به شماره o9358241953 پیام دهید"
    res = TextPhoneMiner.mine_phone(text)
    assert res is not None
    assert res['phone'] == '09358241953'

def test_repeat_phrases():
    text = "مالک هستم شماره من ۰۹۱۲ سه تا ۵ هشتاد و دو ۱۱ است"
    # سه تا ۵ -> 555
    res = TextPhoneMiner.mine_phone(text)
    assert res is not None
    assert res['phone'].startswith('0912555')

def test_fake_and_dummy_numbers_rejected():
    text = "شماره فیک 09111111111 یا تست 09123456789"
    res = TextPhoneMiner.mine_phone(text)
    assert res is None

def test_empty_or_no_phone():
    text = "آپارتمان ۸۰ متری نورگیر عالی بدون شماره"
    res = TextPhoneMiner.mine_phone(text)
    assert res is None

def test_mine_all_phones():
    text = "شماره اول 09129876543 و شماره دوم 09361112233 تماس بگیرید"
    phones = TextPhoneMiner.mine_all_phones(text)
    assert '09129876543' in phones
    assert '09361112233' in phones
