"""Migrations versionadas (P0) — substitui dependência só de ensure_db para schema base."""
import re
from pathlib import Path

from app.db import settings
from app.db.connection import get_conn
from app.db.dialect import _normalize_pg_sql
from app.db.queries import execute, query_all, query_one
from app.shared.formatters import now_str

VERSIONS_DIR = Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
BASELINE_MARKER_TABLES = ('empresas', 'users', 'os_ordens')


def _split_sql_file(text):
    """Divide dump em statements CREATE TABLE (ignora comentários vazios)."""
    chunks = re.split(r'\n(?=-- )', text.strip())
    statements = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith('--')]
        stmt = '\n'.join(lines).strip()
        if stmt.endswith(';'):
            stmt = stmt[:-1].strip()
        if stmt.upper().startswith('CREATE TABLE'):
            statements.append(stmt)
    return statements


def ensure_migration_table():
    if settings.USE_POSTGRES:
        execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT ''
            )"""
        )
    else:
        execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT ''
            )"""
        )


def _applied_versions():
    ensure_migration_table()
    try:
        rows = query_all('SELECT version FROM schema_migrations ORDER BY version')
        return {str(r['version']) for r in rows}
    except Exception:
        return set()


def _migration_files():
    suffix = 'postgres' if settings.USE_POSTGRES else 'sqlite'
    return sorted(VERSIONS_DIR.glob(f'*.{suffix}.sql'))


def _apply_sqlite_file(path):
    sql_text = path.read_text(encoding='utf-8')
    conn = get_conn()
    try:
        conn.executescript(sql_text)
        conn.commit()
    finally:
        conn.close()


def _apply_postgres_file(path):
    sql_text = path.read_text(encoding='utf-8')
    for stmt in _split_sql_file(sql_text):
        pg_sql, params, _kind = _normalize_pg_sql(stmt)
        execute(pg_sql, params)


def _database_has_baseline():
    """Banco já existia antes das migrations versionadas (ex.: staging Render)."""
    names = BASELINE_MARKER_TABLES
    if settings.USE_POSTGRES:
        row = query_one(
            "SELECT COUNT(*) AS n FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name IN (?, ?, ?)",
            names,
        )
    else:
        row = query_one(
            "SELECT COUNT(*) AS n FROM sqlite_master "
            "WHERE type='table' AND name IN (?, ?, ?)",
            names,
        )
    return int((row['n'] if row else 0) or 0) >= 2


def _stamp_migration(version):
    execute(
        'INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)',
        (version, now_str()),
    )


def apply_pending_migrations():
    """Aplica arquivos em migrations/versions/*.sql ainda não registrados."""
    applied = _applied_versions()
    for path in _migration_files():
        version = path.name.split('_', 1)[0]
        if version in applied:
            continue
        if version == '001' and _database_has_baseline():
            _stamp_migration(version)
            applied.add(version)
            continue
        if settings.USE_POSTGRES:
            _apply_postgres_file(path)
        else:
            _apply_sqlite_file(path)
        _stamp_migration(version)
        applied.add(version)


def migration_status():
    applied = sorted(_applied_versions())
    pending = []
    for path in _migration_files():
        version = path.name.split('_', 1)[0]
        if version not in applied:
            pending.append(path.name)
    return {'applied': applied, 'pending': pending}
