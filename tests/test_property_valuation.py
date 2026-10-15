import pytest
from unittest.mock import patch
from flask import Flask
from services.property_valuation import validate_input

def valid():
    return dict(district='پونک',area=85,age=0,rooms=2,parking_count=1,
        floor=3,total_floors=5,units_per_floor=2,document_type='TAK_BARG',features=['balcony'])

def test_all_reference_criteria_are_preserved():
    assert validate_input(valid()) == dict(valid(),property_type='apartment')

@pytest.mark.parametrize('field,value',[('area',None),('area',float('nan')),('area',float('inf')),('rooms',1.5),('age',-1),('parking_count',True),('document_type','bad'),('features',['bad']),('floor',6)])
def test_invalid_criteria_rejected(field,value):
    with pytest.raises(ValueError): validate_input(dict(valid(),**{field:value}))

def test_route_never_returns_fake_price():
    from routes.properties import properties_bp
    app=Flask(__name__); app.register_blueprint(properties_bp)
    with app.test_client() as client, patch('services.property_valuation.estimate_from_database', return_value={'status':'insufficient_data','estimate':None}):
        response=client.post('/properties/api/valuation/preview',json=valid())
        assert response.status_code==200
        assert response.json['status']=='insufficient_data'
        assert response.json['estimate'] is None
        assert client.post('/properties/api/valuation/preview',json={}).status_code==400

def sample(index, **changes):
    result=dict(source_url=f'https://divar.ir/v/test/token{index}',district='پونک',
        title='آپارتمان پونک',description='مالک هستم',property_type='apartment',deal_type='sale',
        area=85,total_price=8500000000,rooms=2,floor=3,total_floors=5,units_per_floor=2,
        build_year=1405,has_parking=True,has_elevator=True,has_balcony=True)
    result.update(changes);return result

def test_model_uses_real_comparables_not_fixed_price():
    from services.property_valuation import evaluate
    result=evaluate(validate_input(valid()),[sample(i) for i in range(6)])
    assert result['status']=='estimated'
    assert result['estimate']==8500000000
    assert result['range_low']<=result['estimate']<=result['range_high']
    assert result['is_live'] is False

def test_duplicate_ads_cannot_create_sufficient_sample():
    from services.property_valuation import evaluate
    result=evaluate(validate_input(valid()),[sample(1)]*10)
    assert result['sample_count']==1 and result['estimate'] is None

def test_wrong_neighborhood_deal_area_owner_or_url_rejected():
    from services.property_valuation import evaluate
    rows=[sample(1,district='سعادت آباد'),sample(2,deal_type='rent'),sample(3,area=200),
        sample(4,description='فایل شخصی کلید در اختیار'),sample(5,source_url='https://evil.example/v/test')]
    assert evaluate(validate_input(valid()),rows)['sample_count']==0

def test_single_extreme_outlier_does_not_move_median():
    from services.property_valuation import evaluate
    rows=[sample(i) for i in range(5)]+[sample(6,total_price=850000000000)]
    assert evaluate(validate_input(valid()),rows)['estimate']==8500000000

def test_database_query_is_isolated_and_read_only(tmp_path):
    from telegram_bot.runtime import create_crm_context
    from database.db import db
    from services.property_valuation import estimate_from_database
    class Config:
        TESTING=True
        SQLALCHEMY_DATABASE_URI='sqlite:///'+(tmp_path/'valuation.db').as_posix()
        SQLALCHEMY_TRACK_MODIFICATIONS=False
    app=create_crm_context(Config)
    with app.app_context():
        db.create_all()
        result=estimate_from_database(validate_input(valid()))
        assert result['estimate'] is None and result['sample_count']==0
