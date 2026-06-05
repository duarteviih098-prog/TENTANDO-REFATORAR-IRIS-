"""Fixtures compartilhadas de teste."""
import os

import pytest


def _clear_schema_cache(*tables):
    from app.db import schema as db_schema

    if tables:
        for table in tables:
            db_schema._TABLE_COLUMNS_CACHE.pop(table, None)
            stale = [k for k in db_schema._TABLE_COLUMN_CACHE if k[0] == table]
            for key in stale:
                db_schema._TABLE_COLUMN_CACHE.pop(key, None)
    else:
        db_schema._TABLE_COLUMNS_CACHE.clear()
        db_schema._TABLE_COLUMN_CACHE.clear()


def ensure_minimal_test_schema():
    """Tabelas base para testes de tenancy (SQLite local sem seed)."""
    from app.db import execute

    execute(
        """CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT DEFAULT '',
            cidade TEXT DEFAULT '',
            dominio_email TEXT DEFAULT '',
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT ''
        )"""
    )
    execute(
        """CREATE TABLE IF NOT EXISTS os_ordens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_os TEXT DEFAULT '',
            status TEXT DEFAULT '',
            finalizada TEXT DEFAULT '',
            empresa_id INTEGER,
            data TEXT DEFAULT ''
        )"""
    )
    _clear_schema_cache('empresas', 'os_ordens')


@pytest.fixture(scope='session')
def flask_app():
    os.environ.setdefault('SECRET_KEY', 'test-secret-key-with-32-chars-minimum-ok')
    from app import app as application
    application.config.update(TESTING=True)
    ensure_minimal_test_schema()
    return application


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
