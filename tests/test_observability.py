"""Testes P1 — observabilidade."""
def test_request_id_header(client):
    response = client.get('/health')
    assert response.status_code in (200, 503)
    assert response.headers.get('X-Request-ID')


def test_health_json_shape(client):
    response = client.get('/health')
    data = response.get_json()
    assert 'status' in data
    assert 'db' in data
