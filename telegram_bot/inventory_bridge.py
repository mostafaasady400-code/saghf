"""Telegram adapter to the existing website extractor; owns no crawler/session."""


def refresh_inventory(criteria):
    # Same business service as routes/properties.py. The worker has a database
    # context only: no dependency on the web process, browser, or a new transport.
    from services.on_demand_extractor import InstantOnDemandExtractor
    report = {'service': 'website_on_demand', 'is_live': False,
              'coverage_status': 'incomplete'}
    InstantOnDemandExtractor.scrape_and_persist_live(
        deal_type=criteria['deal_type'],
        districts=list(criteria.get('preferred_districts') or []),
        min_area=criteria.get('min_area'), max_area=criteria.get('max_area'),
        max_budget=criteria.get('max_budget'),
        max_deposit=criteria.get('max_deposit'), max_rent=criteria.get('max_rent'),
        limit=30, max_duration_seconds=180, report=report,
    )
    # Service saves its results into the shared DB. Never interpret a transport
    # failure or an unverified empty response as successful live coverage.
    if not report.get('is_live'):
        raise RuntimeError('website_extraction_unverified')
    return report
