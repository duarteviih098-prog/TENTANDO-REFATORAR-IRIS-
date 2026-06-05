"""Testes de migrations em Postgres (rodar no job CI com service container)."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv('DATABASE_URL', '').strip().startswith('postgres'),
    reason='Requer DATABASE_URL Postgres (job CI postgres)',
)


def test_postgres_migrations_apply_on_empty_db():
    from app.db import migration_status, query_one
    from app.db.migration_runner import apply_pending_migrations

    apply_pending_migrations()
    status = migration_status()
    assert '001' in status['applied']
    assert status['pending'] == []
    row = query_one(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='empresas'"
    )
    assert row is not None


def test_postgres_baseline_stamp_on_existing_schema():
    from app.db import execute, migration_status, query_one
    from app.db.migration_runner import apply_pending_migrations

    execute(
        """CREATE TABLE IF NOT EXISTS empresas (
            id SERIAL PRIMARY KEY, nome TEXT, cidade TEXT, dominio_email TEXT,
            ativo INTEGER DEFAULT 1, criado_em TEXT DEFAULT ''
        )"""
    )
    execute(
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, nome TEXT, email TEXT UNIQUE, senha_hash TEXT,
            perfil TEXT, permissions TEXT, ativo INTEGER, criado_em TEXT,
            empresa_id INTEGER, is_super_admin INTEGER DEFAULT 0
        )"""
    )
    execute('DELETE FROM schema_migrations WHERE version=?', ('001',))
    apply_pending_migrations()
    status = migration_status()
    assert '001' in status['applied']
    row = query_one("SELECT version FROM schema_migrations WHERE version=?", ('001',))
    assert row is not None
