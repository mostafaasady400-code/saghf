import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from crawler.divar_health_watcher import DivarHealthWatcher

def test_check_token_status_invalid():
    tok, st = DivarHealthWatcher.check_token_status("short")
    assert st == 'invalid'

def test_check_token_status_mock_alive():
    with patch('requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        tok, st = DivarHealthWatcher.check_token_status("gaTestAliveToken")
        assert tok == "gaTestAliveToken"
        assert st == 'alive'

def test_check_token_status_mock_deleted():
    with patch('requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=404)
        tok, st = DivarHealthWatcher.check_token_status("gaTestDeletedToken")
        assert tok == "gaTestDeletedToken"
        assert st == 'deleted'

def test_sync_all_endpoint_exists():
    app = create_app()
    client = app.test_client()
    with patch.object(DivarHealthWatcher, 'sync_all_database_listings', return_value={'total_checked': 10, 'alive': 8, 'deleted': 2, 'errors': 0}):
        res = client.post('/crawler/divar-status/sync-all')
        assert res.status_code == 200
        data = res.get_json()
        assert data['success'] is True
        assert 'metrics' in data
        assert data['metrics']['alive'] == 8
