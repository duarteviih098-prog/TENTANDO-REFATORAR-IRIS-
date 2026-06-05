"""Auditoria extra de segurança — rotas públicas, CSRF e isolamento."""
import json
import uuid

from werkzeug.security import generate_password_hash


def test_unauthenticated_api_delete_redirects_or_blocks(client):
    response = client.post('/api/os/delete', json={'ids': [1]}, follow_redirects=False)
    assert response.status_code in (302, 303, 403)


def test_unauthenticated_protected_pages_redirect_login(client):
    for path in ('/pagamentos/lancamentos', '/usuarios', '/api/os/1'):
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (302, 303, 403, 404)


def test_health_does_not_leak_secrets(client):
    response = client.get('/health')
    assert response.status_code in (200, 503)
    body = response.get_data(as_text=True).lower()
    assert 'secret' not in body
    assert 'password' not in body
    assert 'service_role' not in body


def test_os_image_blocks_without_token_or_session(client):
    from app.db import execute

    suffix = uuid.uuid4().hex[:6]
    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Img-{suffix}', 'C', f'img-{suffix}.local'),
    )
    os_id = execute(
        """INSERT INTO os_ordens(numero_os, data, sistema, status, finalizada, empresa_id, imagens)
           VALUES ('IMG-1','01/06/2026','ETA','Aberta','Não',?,'[]')""",
        (empresa_id,),
    )
    response = client.get(f'/os/imagem/{os_id}/0')
    assert response.status_code == 403


def test_controle_json_still_requires_login(client):
    response = client.post(
        '/controle/movimentar',
        json={'bomba_id': 1, 'acao': 'estoque'},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303, 400, 403)


def test_controle_json_with_session_requires_edit_permission(client):
    from app.auth.constants import ALL_PERMISSIONS
    from app.db import execute

    suffix = uuid.uuid4().hex[:6]
    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Ctrl-{suffix}', 'C', f'ctrl-{suffix}.local'),
    )
    view_only = [p for p in ALL_PERMISSIONS if p != 'edit_controle']
    user_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES ('V','v@test.local',?,?,?,1,'01/01/2026',?,0)""",
        (generate_password_hash('x'), 'padrao', json.dumps(view_only), empresa_id),
    )
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['empresa_id'] = empresa_id
    client.get('/login')
    response = client.post('/controle/movimentar', json={'bomba_id': 999, 'acao': 'estoque'})
    assert response.status_code in (302, 403)


def test_sql_injection_search_does_not_crash(admin_session, client):
    response = client.get('/os/lista?q=%27%20OR%201%3D1--')
    assert response.status_code == 200


def test_session_cookie_httponly_config(flask_app):
    assert flask_app.config.get('SESSION_COOKIE_HTTPONLY') is True


def test_max_upload_limit_configured(flask_app):
    assert flask_app.config.get('MAX_CONTENT_LENGTH', 0) >= 5 * 1024 * 1024


def test_api_delete_blocks_without_csrf_even_when_logged_in(admin_session, client):
    response = client.post('/api/os/delete', json={'ids': [1]})
    assert response.status_code == 403


def test_controle_json_accepts_without_csrf_when_logged_in(admin_session, client):
    """Documenta exceção intencional: /controle/* JSON não exige CSRF (só sessão + permissão)."""
    response = client.post('/controle/movimentar', json={'bomba_id': 999, 'acao': 'estoque'})
    assert response.status_code != 403
