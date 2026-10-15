import pytest
from app import create_app
from services.property_valuation import get_meta_data, ValuationSessionManager

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_meta_endpoint_contract(client):
    res = client.get('/properties/api/valuation/meta')
    assert res.status_code == 200
    data = res.get_json()
    assert data['brand_name'] == 'سامانه هوشمند املاک سقف'
    assert isinstance(data['property_types'], list)
    assert any(p['value'] == 'apartment' and p['enabled'] for p in data['property_types'])
    assert isinstance(data['areas'], list)
    assert any(a['value'] == 'پونک' for a in data['areas'])
    assert data['otp_length'] == 5
    assert data['otp_resend_cooldown'] == 90
    assert data['model_ready'] is True

def test_full_mim_workflow_and_formula(client):
    # 1. Create Session
    specs = {
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 85,
        'property_age': 2,
        'rooms': 2,
        'floor': 3,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True,
        'is_renovated': False,
        'is_luxury': False
    }
    s_res = client.post('/properties/api/valuation/sessions', json=specs)
    assert s_res.status_code == 201
    sid = s_res.get_json()['session_id']
    assert sid

    # 2. Send OTP
    o_res = client.post(f'/properties/api/valuation/sessions/{sid}/otp', json={
        'phone': '09334002027',
        'intent': 'owner_sell'
    })
    assert o_res.status_code == 200
    otp_data = o_res.get_json()
    assert otp_data['sent'] is True
    assert otp_data['masked_phone'] == '0933***027'
    code = otp_data['debug_code']
    assert len(code) == 5

    # 3. Invalid OTP rejected
    err_res = client.post(f'/properties/api/valuation/sessions/{sid}/verify', json={'code': '00000'})
    assert err_res.status_code == 400

    # 4. Valid OTP verified and calculated
    v_res = client.post(f'/properties/api/valuation/sessions/{sid}/verify', json={'code': code})
    assert v_res.status_code == 200
    res_data = v_res.get_json()

    # Verify mathematical formula & structure
    assert res_data['area'] == 'پونک'
    assert res_data['size_sqm'] == 85.0
    assert res_data['total']['avg'] > 0
    assert res_data['total']['min'] <= res_data['total']['avg'] <= res_data['total']['max']
    assert res_data['per_meter']['min'] <= res_data['per_meter']['avg'] <= res_data['per_meter']['max']
    # تضمین قطعی قیمت واقعی پونک (حداقل متری ۳۰۰ میلیون تومان طبق دستور مستقیم کاربر و معاملات روز)
    assert res_data['per_meter']['avg'] >= 300_000_000

    # Rates
    rates = res_data['rates']
    assert rates['available'] is True
    assert rates['usd_rate'] > 0
    assert rates['gold_rate'] > 0
    assert rates['equivalent_usd'] > 0
    assert rates['equivalent_gold_grams'] > 0

    # Result endpoint
    r_res = client.get(f'/properties/api/valuation/sessions/{sid}/result')
    assert r_res.status_code == 200

    # 5. Expert Request
    exp_res = client.post(f'/properties/api/valuation/sessions/{sid}/expert-request', json={'note': 'کارشناسی دقیق'})
    assert exp_res.status_code == 200
    assert exp_res.get_json()['success'] is True


def test_telegram_otp_dispatch_and_polling_flow(client):
    """تست اختصاصی اعتبارسنجی از طریق تلگرام و پولینگ وضعیت سشن"""
    specs = {
        'property_type': 'apartment',
        'area': 'سعادت‌آباد',
        'size_sqm': 110,
        'property_age': 1,
        'rooms': 2,
        'floor': 4,
        'total_floors': 6,
        'floor_units': 2,
        'parking_count': 2,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True,
        'is_renovated': False,
        'is_luxury': True
    }
    s_res = client.post('/properties/api/valuation/sessions', json=specs)
    assert s_res.status_code == 201
    sid = s_res.get_json()['session_id']

    # 1. Request OTP via Telegram
    o_res = client.post(f'/properties/api/valuation/sessions/{sid}/otp', json={
        'phone': '09334002027',
        'intent': 'owner_sell',
        'method': 'telegram'
    })
    assert o_res.status_code == 200
    otp_data = o_res.get_json()
    assert otp_data['sent'] is True
    assert otp_data['delivery_method'] == 'telegram'
    assert 'telegram_link' in otp_data
    assert f'val_{sid}' in otp_data['telegram_link']

    # 2. Check Session Status (Polling Endpoint)
    st_res = client.get(f'/properties/api/valuation/sessions/{sid}/status')
    assert st_res.status_code == 200
    status_data = st_res.get_json()
    assert status_data['is_verified'] is False
    assert status_data['delivery_method'] == 'telegram'

    # 3. Verify OTP
    code = otp_data['debug_code']
    v_res = client.post(f'/properties/api/valuation/sessions/{sid}/verify', json={'code': code})
    assert v_res.status_code == 200

    # 4. Check status after verification
    st_res_after = client.get(f'/properties/api/valuation/sessions/{sid}/status')
    assert st_res_after.status_code == 200
    assert st_res_after.get_json()['is_verified'] is True


def test_telegram_bot_deep_link_and_callback(client):
    """تست اتصال مستقیم ربات تلگرام سقف (@saghf_bot) به سشن ارزیابی و تایید آنی"""
    specs = {
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 90,
        'property_age': 5,
        'rooms': 2,
        'floor': 2,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True
    }
    s_res = client.post('/properties/api/valuation/sessions', json=specs)
    sid = s_res.get_json()['session_id']

    # Send OTP
    client.post(f'/properties/api/valuation/sessions/{sid}/otp', json={
        'phone': '09334002027',
        'intent': 'owner_sell'
    })
    session = ValuationSessionManager.get_session(sid)
    otp_code = session['otp_code']
    assert session['is_verified'] is False

    # Simulate Telegram Bot callback query for auto-verification
    from telegram_bot.bot import get_bot
    bot = get_bot()
    assert bot is not None

    # Verify session via bot handler logic
    ValuationSessionManager.verify_otp(sid, otp_code)
    assert session['is_verified'] is True
    assert session['result'] is not None
    assert session['result']['total']['avg'] > 0


def test_realistic_multi_variable_valuation_scenarios(client):
    """
    تست سناریوهای چندمتغیره ارزیابی املاک:
    - بررسی قیمت پونک (حداقل متری ۳۰۰ میلیون تومان)
    - بررسی اثر سن بنا، آسانسور، پارکینگ، تراکم واحد و لوکس
    """
    from services.property_valuation import ValuationSessionManager

    # سناریو ۱: آپارتمان ۸۵ متری پونک ۲ سال ساخت طبقه ۳ با پارکینگ و آسانسور
    res1 = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 85,
        'property_age': 2,
        'rooms': 2,
        'floor': 3,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True
    })
    # در پونک هرگز کمتر از متری ۳۰۰ میلیون تومان نیست
    assert res1['per_meter']['avg'] >= 300_000_000
    assert 30_000_000_000 <= res1['total']['avg'] <= 40_000_000_000

    # سناریو ۲: همان آپارتمان اگر بدون آسانسور باشد باید ارزان‌تر باشد
    res2_no_elevator = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 85,
        'property_age': 2,
        'rooms': 2,
        'floor': 3,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': False,
        'has_storage': True,
        'has_balcony': True
    })
    assert res2_no_elevator['per_meter']['avg'] < res1['per_meter']['avg']
    assert res2_no_elevator['per_meter']['avg'] <= res1['per_meter']['avg'] * 0.85

    # سناریو ۳: همان آپارتمان اگر بدون پارکینگ باشد جریمه دارد
    res3_no_parking = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 85,
        'property_age': 2,
        'rooms': 2,
        'floor': 3,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 0,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True
    })
    assert res3_no_parking['per_meter']['avg'] < res1['per_meter']['avg']
    assert res3_no_parking['per_meter']['avg'] <= res1['per_meter']['avg'] * 0.92

    # سناریو ۴: واحد لوکس همیلا / پونک ۱۴۰ متری تک‌واحدی با امکانات لوکس
    res4_luxury = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'همیلا',
        'size_sqm': 140,
        'property_age': 0,
        'rooms': 3,
        'floor': 5,
        'total_floors': 6,
        'floor_units': 1,
        'parking_count': 2,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True,
        'is_luxury': True
    })
    assert res4_luxury['per_meter']['avg'] >= 500_000_000
    assert res4_luxury['total']['avg'] >= 70_000_000_000

    # سناریو ۵: سعادت‌آباد ۱۲۰ متری نوساز لوکس
    res5_saadat = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'سعادت‌آباد',
        'size_sqm': 120,
        'property_age': 1,
        'rooms': 2,
        'floor': 4,
        'total_floors': 6,
        'floor_units': 2,
        'parking_count': 2,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True,
        'is_luxury': True
    })
    assert res5_saadat['per_meter']['avg'] >= 700_000_000

    # سناریو ۶: پونک ۲۲ ساله طبقه ۳ بدون آسانسور و بدون پارکینگ (تضمین کف قطعی متری ۳۰۰ میلیون تومان)
    res6_poonak_floor = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 110,
        'property_age': 22,
        'rooms': 2,
        'floor': 3,
        'total_floors': 4,
        'floor_units': 2,
        'parking_count': 0,
        'sanad_type': 'TAK_BARG',
        'has_elevator': False,
        'has_storage': True,
        'has_balcony': False
    })
    # قانون قطعی پونک: تحت هیچ شرایطی متری زیر ۳۰۰ میلیون تومان محاسبه نمی‌شود
    assert res6_poonak_floor['per_meter']['avg'] >= 300_000_000
    assert res6_poonak_floor['total']['avg'] >= 33_000_000_000

    # سناریو ۷: پونک ۱۶ ساله ۶۶ متری بازسازی شده (تطبیق با آگهی واقعی پونک دیتابیس کد ۴)
    res7_poonak_renovated = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'پونک',
        'size_sqm': 66,
        'property_age': 16,
        'rooms': 1,
        'floor': 2,
        'total_floors': 4,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True,
        'is_renovated': True
    })
    assert 350_000_000 <= res7_poonak_renovated['per_meter']['avg'] <= 420_000_000
    assert 23_000_000_000 <= res7_poonak_renovated['total']['avg'] <= 28_000_000_000

    # سناریو ۸: جنت‌آباد جنوبی ۸۵ متری ۴ ساله استاندارد فول
    res8_janatabad = ValuationSessionManager.compute_valuation_result({
        'property_type': 'apartment',
        'area': 'جنت‌آباد جنوبی',
        'size_sqm': 85,
        'property_age': 4,
        'rooms': 2,
        'floor': 2,
        'total_floors': 5,
        'floor_units': 2,
        'parking_count': 1,
        'sanad_type': 'TAK_BARG',
        'has_elevator': True,
        'has_storage': True,
        'has_balcony': True
    })
    assert 380_000_000 <= res8_janatabad['per_meter']['avg'] <= 450_000_000


