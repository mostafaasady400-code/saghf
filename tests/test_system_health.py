"""
Automated unit and integration test suite for Infrastructure & Service Health Monitoring.
Validates zero-mock telemetry, hardware probe accuracy, REST APIs, and Admin UI rendering.
"""

import pytest
from app import create_app
from services.system_health import SystemHealthService


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSystemHealth:
    def test_compute_metrics(self, app):
        with app.app_context():
            compute = SystemHealthService.get_compute_metrics()
            assert 'cpu' in compute
            assert 'ram' in compute
            assert 'disk' in compute
            assert 'os' in compute
            assert 'process' in compute

            # CPU validation
            assert 0.0 <= compute['cpu']['percent'] <= 100.0
            assert compute['cpu']['logical_cores'] >= 1

            # RAM validation
            assert compute['ram']['total_gb'] > 0.0
            assert 0.0 <= compute['ram']['percent'] <= 100.0

            # Disk validation
            assert compute['disk']['total_gb'] > 0.0
            assert compute['disk']['write_healthy'] is True

            # Process validation
            assert compute['process']['pid'] > 0
            assert compute['process']['rss_mb'] > 0.0

    def test_database_health(self, app):
        with app.app_context():
            db_stat = SystemHealthService.get_database_health()
            assert db_stat['status'] in ('healthy', 'degraded')
            assert db_stat['integrity_check'] == 'ok'
            assert db_stat['query_latency_ms'] >= 0.0
            assert 'counts' in db_stat
            assert db_stat['counts']['properties'] >= 0
            assert db_stat['counts']['clients'] >= 0

    def test_full_report_structure(self, app):
        with app.app_context():
            report = SystemHealthService.get_full_report()
            assert 'overall_status' in report
            assert report['overall_status'] in ('HEALTHY', 'DEGRADED', 'CRITICAL')
            assert 0.0 <= report['health_score'] <= 100.0
            assert isinstance(report['issues'], list)
            assert 'compute' in report
            assert 'database' in report
            assert 'bots' in report
            assert 'crawler' in report

    def test_api_health_endpoint(self, client):
        res = client.get('/api/health')
        assert res.status_code == 200
        data = res.get_json()
        assert data is not None
        assert 'status' in data
        assert data['status'] in ('healthy', 'degraded')
        assert 'uptime_seconds' in data
        assert 'services' in data
        assert 'database' in data['services']
        assert 'crawler_tier1' in data['services']

    def test_api_health_detailed_endpoint(self, client):
        res = client.get('/api/health/detailed')
        assert res.status_code == 200
        data = res.get_json()
        assert data is not None
        assert 'health_score' in data
        assert 'compute' in data
        assert 'database' in data
        assert 'bots' in data

    def test_admin_health_route_protection(self, client):
        # Unauthenticated request should redirect to admin login
        res = client.get('/admin/health')
        assert res.status_code == 302
        assert '/admin/login' in res.headers.get('Location', '')

    def test_admin_health_route_render(self, client):
        with client.session_transaction() as sess:
            sess['is_admin'] = True
            sess['admin_user'] = 'admin'

        res = client.get('/admin/health')
        assert res.status_code == 200
        html = res.get_data(as_text=True)
        assert 'پایش سلامت زیرساخت و منابع' in html
        assert 'ماتریس سلامت سرویس‌های عملیاتی' in html
        assert 'Zero-Mock' in html

    def test_admin_health_data_ajax(self, client):
        with client.session_transaction() as sess:
            sess['is_admin'] = True
            sess['admin_user'] = 'admin'

        res = client.get('/admin/health/data')
        assert res.status_code == 200
        data = res.get_json()
        assert data is not None
        assert 'health_score' in data
        assert 'compute' in data
