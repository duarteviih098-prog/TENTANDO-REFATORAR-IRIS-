"""Testes de segurança, tenant isolation e CSRF (cobertura completa)."""
import json
import uuid

import pytest
from werkzeug.security import generate_password_hash


def test_tenant_tables_cover_empresa_scoped_tables():
    from app.auth.constants import TENANT_TABLES

    required = {
        'os_ordens', 'pagamentos', 'inventario_itens', 'campo_tecnicos',
        'campo_eventos', 'push_subscriptions', 'audit_logs', 'pdf_jobs',
    }
    assert required.issubset(TENANT_TABLES)


def test_production_requires_database_url(monkeypatch):
    from app.config import validate_production_config

    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-key')
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        validate_production_config('x' * 40)


def test_production_requires_supabase_env(monkeypatch):
    from app.config import validate_production_config

    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@localhost/db')
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-key')
    with pytest.raises(RuntimeError, match='SUPABASE_URL'):
        validate_production_config('x' * 40)


def test_protected_route_redirects_without_session(client):
    response = client.get('/pagamentos', follow_redirects=False)
    assert response.status_code in (302, 303)
    assert '/login' in (response.headers.get('Location') or '')


def test_csrf_blocks_api_delete_without_token(admin_session, client):
    response = client.post('/api/os/delete', json={'ids': [1]})
    assert response.status_code == 403
    data = response.get_json()
    assert data.get('ok') is False or data.get('error')


def test_csrf_allows_api_with_header(admin_session, client):
    from app.db import execute, query_one

    os_id = execute(
        """INSERT INTO os_ordens(numero_os, data, sistema, status, finalizada, empresa_id)
           VALUES ('CSRF-1','01/06/2026','ETA','Aberta','Não',?)""",
        (admin_session['empresa_id'],),
    )
    response = client.post(
        '/api/os/delete',
        json={'ids': [os_id]},
        headers={'X-CSRF-Token': admin_session['csrf_token']},
    )
    assert response.status_code == 200
    assert response.get_json().get('ok') is True
    assert query_one('SELECT id FROM os_ordens WHERE id=?', (os_id,)) is None


def test_api_delete_ignores_cross_tenant_ids(admin_session, client):
    from app.db import execute, query_one

    suffix = uuid.uuid4().hex[:6]
    other_empresa = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Outra-{suffix}', 'C', f'out-{suffix}.local'),
    )
    foreign_os = execute(
        """INSERT INTO os_ordens(numero_os, data, sistema, status, finalizada, empresa_id)
           VALUES ('FOR-1','01/06/2026','ETA','Aberta','Não',?)""",
        (other_empresa,),
    )
    response = client.post(
        '/api/os/delete',
        json={'ids': [foreign_os]},
        headers={'X-CSRF-Token': admin_session['csrf_token']},
    )
    assert response.status_code == 200
    assert query_one('SELECT id FROM os_ordens WHERE id=?', (foreign_os,)) is not None


def test_api_get_returns_404_for_cross_tenant(admin_session, client):
    from app.db import execute

    suffix = uuid.uuid4().hex[:6]
    other_empresa = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Outra2-{suffix}', 'C', f'out2-{suffix}.local'),
    )
    foreign_os = execute(
        """INSERT INTO os_ordens(numero_os, data, sistema, status, finalizada, empresa_id)
           VALUES ('FOR-2','01/06/2026','ETA','Aberta','Não',?)""",
        (other_empresa,),
    )
    response = client.get(f'/api/os/{foreign_os}')
    assert response.status_code == 404


def test_login_blocks_after_max_attempts(flask_app, client, monkeypatch):
    from app.auth.security_store import delete_login_attempt
    from app.auth.services import LOGIN_MAX_ATTEMPTS

    ip = '203.0.113.50'
    monkeypatch.setattr('app.auth.routes._login_get_ip', lambda: ip)
    delete_login_attempt(ip)

    for _ in range(LOGIN_MAX_ATTEMPTS):
        client.post('/login', data={'email': 'nobody@test.local', 'senha': 'wrong'})

    from app.auth.services import _login_is_blocked

    with flask_app.test_request_context('/'):
        blocked, _remaining = _login_is_blocked(ip)
    assert blocked is True


def test_health_returns_503_when_db_fails(flask_app, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError('db down')

    monkeypatch.setattr('app.db.query_one', _boom)
    client = flask_app.test_client()
    response = client.get('/health')
    assert response.status_code == 503
    data = response.get_json()
    assert data.get('db') == 'fail'


def test_api_delete_requires_permission(client):
    from app.db import execute

    suffix = uuid.uuid4().hex[:6]
    empresa_id = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'Perm-{suffix}', 'C', f'perm-{suffix}.local'),
    )
    user_id = execute(
        """INSERT INTO users(nome,email,senha_hash,perfil,permissions,ativo,criado_em,empresa_id,is_super_admin)
           VALUES ('U','u@test.local',?,?,?,1,'01/01/2026',?,0)""",
        (generate_password_hash('x'), 'user', json.dumps([]), empresa_id),
    )
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['empresa_id'] = empresa_id
    client.get('/login')
    with client.session_transaction() as sess:
        csrf = sess.get('_csrf_token', '')
    response = client.post(
        '/api/os/delete',
        json={'ids': [1]},
        headers={'X-CSRF-Token': csrf},
    )
    assert response.status_code == 403
