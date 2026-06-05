"""Smoke tests — import do app e rotas críticas."""


def test_app_imports():
    from app import app
    assert app is not None


def test_health_route(flask_app):
    client = flask_app.test_client()
    response = client.get('/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data.get('status') == 'ok'
    assert data.get('db') == 'ok'


def test_route_count_stable(flask_app):
    rules = {r.rule for r in flask_app.url_map.iter_rules()}
    assert '/login' in rules
    assert '/iris/chat' in rules
    assert '/api/search' in rules
    assert len(rules) >= 160
