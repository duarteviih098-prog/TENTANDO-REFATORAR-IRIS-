"""Testes de configuração e segurança P0."""

import pytest
from app.config import validate_production_config


def test_production_rejects_weak_secret_key(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.delenv('IRIS_PRODUCTION', raising=False)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        validate_production_config('gg-web-app')


def test_production_accepts_strong_secret_key(monkeypatch):
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://user:pass@localhost/db')
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-key')
    validate_production_config('x' * 40)


def test_dev_allows_default_secret_key(monkeypatch):
    monkeypatch.delenv('RENDER', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('IRIS_PRODUCTION', raising=False)
    monkeypatch.setenv('FLASK_ENV', 'development')
    validate_production_config('gg-web-app')


def test_tenant_tables_include_inventario():
    from app.auth.constants import TENANT_TABLES
    assert 'inventario_itens' in TENANT_TABLES
    assert 'inventario_pedidos' in TENANT_TABLES
    assert 'campo_tecnicos' in TENANT_TABLES
    assert 'campo_eventos' in TENANT_TABLES
    assert 'push_subscriptions' in TENANT_TABLES
    assert 'audit_logs' in TENANT_TABLES


def test_password_reset_token_roundtrip(flask_app):
    from app.auth.security_store import (
        delete_password_reset_token,
        get_password_reset_token,
        save_password_reset_token,
    )

    token = 'test-token-' + ('a' * 20)
    save_password_reset_token(token, 'user@example.com', 9999999999.0)
    row = get_password_reset_token(token)
    assert row is not None
    assert row['email'] == 'user@example.com'
    delete_password_reset_token(token)
    assert get_password_reset_token(token) is None


def test_login_attempt_persistence(flask_app):
    from app.auth.security_store import delete_login_attempt, get_login_attempt, upsert_login_attempt

    ip = '127.0.0.99'
    delete_login_attempt(ip)
    upsert_login_attempt(ip, 2, 1000.0, 0)
    row = get_login_attempt(ip)
    assert row is not None
    assert row['count'] == 2
    delete_login_attempt(ip)
