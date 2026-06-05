"""Testes P2 — páginas de erro."""
import json

from werkzeug.security import generate_password_hash


def test_404_page_when_logged_in(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['empresa_id'] = 1
    response = client.get('/pagina-que-nao-existe-iris-test')
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert 'Página não encontrada' in body
    assert '404' in body
    assert 'Voltar ao início' in body


def test_403_page_when_logged_in_without_permission(client):
    from app.db import execute

    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES ('E403','C','e403.local',1,'01/01/2026')",
    )
    user_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES ('Sem Perm','sem@teste.local',?,?,?,1,'01/01/2026',?,0)""",
        (generate_password_hash('x'), 'user', json.dumps([]), empresa_id),
    )
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['empresa_id'] = empresa_id
    response = client.get('/pagamentos')
    assert response.status_code == 403
    body = response.get_data(as_text=True)
    assert 'Sem permissão' in body
    assert '403' in body


def test_403_json_api(client):
    response = client.post('/api/controle/delete', json={'ids': [1]})
    assert response.status_code in (403, 401, 302)
    if response.status_code == 403 and response.is_json:
        assert response.get_json().get('error')
