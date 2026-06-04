"""Smoke tests — import do app e rotas críticas."""
import pytest


@pytest.fixture(scope='module')
def flask_app():
    from app import app as application
    application.config.update(TESTING=True)
    return application


def test_app_imports():
    from app import app
    assert app is not None


def test_health_route(flask_app):
    client = flask_app.test_client()
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_data(as_text=True).strip().lower() in ('ok', '"ok"')


def test_route_count_stable(flask_app):
    rules = {r.rule for r in flask_app.url_map.iter_rules()}
    assert '/login' in rules
    assert '/iris/chat' in rules
    assert '/api/search' in rules
    assert len(rules) >= 160
