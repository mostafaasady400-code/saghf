from .workflow import VerificationError, snapshot_hash


def recheck_reviewed_listing(store, case_id, *, cdp_url):
    # Fail before opening a page unless an authorized human has reviewed it.
    row = store.require_review(case_id)
    from crawler.divar_authenticated_http import AuthenticatedDivarHTTP
    from crawler.parsers.divar_native_detail import parse_native_detail
    transport = AuthenticatedDivarHTTP(cdp_url=cdp_url)
    try:
        transport.connect()
        page = transport._page  # Only the transport-owned page, never user tabs.
        response = page.goto('https://divar.ir/v/' + row['token'], wait_until='domcontentloaded', timeout=20000)
        if response is None or response.status != 200:
            store.record_listing_check(case_id, {}, active=False)
            raise VerificationError('listing_unavailable')
        page.wait_for_selector('h1', timeout=8000)
        payload = transport.fetch_detail_json(row['token'])
        if payload.get('source_removed'):
            store.record_listing_check(case_id, {}, active=False)
            return False
        detail = parse_native_detail(payload)
        web = payload.get('webengage') or {}
        snapshot = {'token': row['token'], 'title': page.locator('h1').first.inner_text().strip(),
                    'district': web.get('district'), 'area': detail.get('area'),
                    'deal_type': web.get('category')}
        # Unknown schema must not be treated as a positive match.
        snapshot_hash(snapshot)
        return store.record_listing_check(case_id, snapshot, active=True)
    except Exception:
        # Failed/unknown live checks cannot leave an earlier approval active.
        store.record_listing_check(case_id, {}, active=False)
        raise VerificationError('live_listing_check_unconfirmed') from None
    finally:
        transport.close()
