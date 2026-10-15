"""Exact live-extraction contract on isolated SQLite; no network or production writes."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from tests.test_telegram_customer_flow import app
from database.db import db
from database.models import Property
from crawler.schemas import NormalizedPropertySchema
from services.on_demand_extractor import instant_extractor, LiveExtractionError


def schema(source_id='unit_exact', **values):
    fields = dict(source='divar',source_id=source_id,source_url='https://divar.ir/v/unit/'+source_id,
        title='آپارتمان پونک',description='مالک هستم',deal_type='rent',property_type='apartment',
        city='تهران',district='پونک',area=80,rooms=2,deposit=500000000,monthly_rent=0,
        is_personal_owner=True)
    fields.update(values)
    return NormalizedPropertySchema(**fields)


def crawler_mock(items):
    crawler = MagicMock()
    crawler.fetch_listings.return_value = items
    crawler.last_fetch_report = {}
    return crawler


def test_exact_bounds_and_zero_rent_are_forwarded_and_enforced(app):
    crawler = crawler_mock([schema('valid'),schema('outside',area=95),schema('wrong_rent',monthly_rent=15000000)])
    report = {}
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        items = instant_extractor.scrape_and_persist_live(deal_type='rent',districts=['پونک'],
            min_area=70,max_area=90,max_deposit=500000000,max_rent=0,report=report)
    assert [item.source_id for item in items]==['valid']
    assert crawler.fetch_listings.call_args.kwargs['min_area']==70
    assert crawler.fetch_listings.call_args.kwargs['max_area']==90
    assert crawler.fetch_listings.call_args.kwargs['max_rent']==0
    assert Property.query.count()==1
    assert report['matched_count']==1 and report['coverage_status']=='incomplete'


def test_connection_exception_is_explicit_and_safe(app):
    crawler = crawler_mock([])
    crawler.fetch_listings.side_effect = ConnectionError('sensitive-cookie-value')
    report={}
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        with pytest.raises(LiveExtractionError) as error:
            instant_extractor.scrape_and_persist_live(deal_type='rent',report=report)
    assert str(error.value)=='connection_failed'
    assert 'sensitive' not in str(report)
    assert report['is_live'] is False
    assert Property.query.count()==0


def test_empty_fetch_is_unverified_not_success(app):
    crawler=crawler_mock([])
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        with pytest.raises(LiveExtractionError,match='empty_unverified'):
            instant_extractor.scrape_and_persist_live(deal_type='rent')


def test_post_filter_rejects_wrong_deal_and_district(app):
    crawler=crawler_mock([schema('different',district='مرزداران'),schema('sale',deal_type='sale',total_price=4000000000)])
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        assert instant_extractor.scrape_and_persist_live(deal_type='rent',districts=['پونک'])==[]
    assert Property.query.count()==0


def test_backfill_no_longer_calls_purge():
    import ast
    path=Path(__file__).parents[1]/'crawler'/'regional_incremental_engine.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    function=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='run_7_day_backfill')
    assert not any(isinstance(node,ast.Attribute) and node.attr=='purge_any_non_region_2_5' for node in ast.walk(function))


def test_unknown_or_intermediary_cannot_be_persisted_as_owner(app):
    crawler=crawler_mock([schema('unknown',is_personal_owner=False),schema('broker',description='مالک مستقیم هستم')])
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        assert instant_extractor.scrape_and_persist_live(deal_type='rent')==[]
    assert Property.query.count()==0


def test_old_cached_row_outside_filters_is_not_live_match(app):
    db.session.add(Property(source='divar',source_id='cached',title='آپارتمان پونک',description='مالک هستم',
        district='پونک',city='تهران',area=120,rooms=2,deal_type='rent',is_personal_owner=True))
    db.session.commit()
    crawler=crawler_mock([schema('cached')])
    report={}
    with patch('services.on_demand_extractor.HybridDivarCrawler',return_value=crawler):
        assert instant_extractor.scrape_and_persist_live(deal_type='rent',min_area=70,max_area=90,report=report)==[]
    assert report['reused_count']==1 and report['matched_count']==0
