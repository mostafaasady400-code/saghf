import io
import pytest
from PIL import Image, ImageDraw
from crawler.image_phone_miner import ImagePhoneMiner

def create_dummy_image():
    img = Image.new('RGB', (100, 100), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

def test_image_phone_miner_availability():
    # Should safely return boolean
    assert isinstance(ImagePhoneMiner.is_ocr_available(), bool)

def test_image_phone_miner_with_mock_engine():
    # Register a mock OCR engine returning a text with phone number
    ImagePhoneMiner.register_ocr_engine(lambda img: "تماس مستقیم با مالک: 09123456780")
    
    dummy_bytes = create_dummy_image()
    res = ImagePhoneMiner.process_image_bytes(dummy_bytes)
    assert res is not None
    assert res['phone'] == '09123456780'
    assert res['source'] == 'image_ocr'
    assert res['is_valid'] is True

def test_image_phone_miner_with_no_phone():
    ImagePhoneMiner.register_ocr_engine(lambda img: "تصویر اتاق خواب بدون متن و شماره")
    dummy_bytes = create_dummy_image()
    res = ImagePhoneMiner.process_image_bytes(dummy_bytes)
    assert res is None

def test_image_phone_miner_invalid_bytes():
    res = ImagePhoneMiner.process_image_bytes(b'not_an_image')
    assert res is None
