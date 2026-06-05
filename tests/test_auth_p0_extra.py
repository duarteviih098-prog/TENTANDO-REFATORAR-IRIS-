"""Testes P0 extras: cookies, tenant, login."""
import os

import pytest


def test_session_cookie_secure_auto_in_production(monkeypatch):
    monkeypatch.delenv('SESSION_COOKIE_SECURE', raising=False)
    monkeypatch.setenv('RENDER', 'true')
    from importlib import reload
    import app.config as cfg
    reload(cfg)
    assert cfg.session_cookie_secure() is True


def test_session_cookie_secure_respects_explicit_off(monkeypatch):
    monkeypatch.setenv('SESSION_COOKIE_SECURE', '0')
    monkeypatch.setenv('RENDER', 'true')
    from importlib import reload
    import app.config as cfg
    reload(cfg)
    assert cfg.session_cookie_secure() is False


def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200
    assert 'login' in response.get_data(as_text=True).lower()


def test_owned_by_current_company_blocks_cross_tenant(flask_app):
    import uuid
    from app.auth.tenancy import owned_by_current_company
    from app.db import execute, query_one

    suffix = uuid.uuid4().hex[:8]
    e1 = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'T1-{suffix}', '', f't1-{suffix}.local'),
    )
    e2 = execute(
        "INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,1,'01/01/2026')",
        (f'T2-{suffix}', '', f't2-{suffix}.local'),
    )
    os_id = execute(
        "INSERT INTO os_ordens(numero_os, status, finalizada, empresa_id, data) VALUES ('999','Aberta','Não',?, '01/01/2026')",
        (e2,),
    )
    with flask_app.test_request_context('/'):
        from flask import session
        session['user_id'] = 1
        session['empresa_id'] = e1
        session['selected_empresa_id'] = e1
        assert owned_by_current_company('os_ordens', os_id) is False
    row = query_one('SELECT id FROM os_ordens WHERE id=?', (os_id,))
    assert row
