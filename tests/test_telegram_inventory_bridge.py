from unittest.mock import patch

import pytest

from tests.test_telegram_extraction_jobs import payload
from tests.test_telegram_customer_panel import crm_app, records, CUSTOMER, item_for


def test_bridge_forwards_filters_to_existing_website_service():
    from telegram_bot.inventory_bridge import refresh_inventory
    def service(**kwargs):
        kwargs['report'].update(is_live=True, source_status='partial')
        return []
    with patch('services.on_demand_extractor.InstantOnDemandExtractor.scrape_and_persist_live', side_effect=service) as execute:
        report = refresh_inventory(dict(payload(), max_rent=0))
    assert report['service'] == 'website_on_demand'
    assert execute.call_args.kwargs['districts'] == ['پونک']
    assert execute.call_args.kwargs['min_area'] == 70
    assert execute.call_args.kwargs['max_area'] == 90
    assert execute.call_args.kwargs['max_rent'] == 0
    assert execute.call_args.kwargs['max_duration_seconds'] == 180


def test_bridge_does_not_call_alternative_crawler_after_failure():
    from telegram_bot.inventory_bridge import refresh_inventory
    with patch('services.on_demand_extractor.InstantOnDemandExtractor.scrape_and_persist_live', side_effect=ConnectionError()), patch('services.search_run_service.SearchRunService.execute') as alternate:
        with pytest.raises(ConnectionError):
            refresh_inventory(payload())
    alternate.assert_not_called()


def test_website_public_inventory_visible_but_office_inventory_stays_private(records):
    from database.db import db
    from telegram_bot.customer_panel import _source_visible
    lead = records[CUSTOMER]['lead']
    row = records[102]['property']
    assert not _source_visible(item_for(row), lead)
    row.source = 'divar'
    row.assigned_agent_id = None
    row.description = 'مالک هستم'
    db.session.commit()
    assert _source_visible(item_for(row), lead)
    row.source_url = 'https://example.com/v/test'
    db.session.commit()
    assert not _source_visible(item_for(row), lead)
