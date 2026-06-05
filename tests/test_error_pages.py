"""Testes P2 — páginas de erro."""
def test_404_page_when_logged_in(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['empresa_id'] = 1
    response = client.get('/pagina-que-nao-existe-iris-test')
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert 'Página não encontrada' in body
    assert '404' in body


def test_403_json_api(client):
    response = client.post('/api/controle/delete', json={'ids': [1]})
    assert response.status_code in (403, 401, 302)
    if response.status_code == 403 and response.is_json:
        assert response.get_json().get('error')
