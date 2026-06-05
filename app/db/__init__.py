"""Camada de banco de dados IRIS."""
from app.db.connection import get_conn
from app.db.migration_runner import apply_pending_migrations, migration_status
from app.db.migrations import ensure_db, ensure_indexes
from app.db.queries import execute, executemany, query_all, query_one, reset_postgres_id_sequence
from app.db.schema import ensure_column, table_columns, table_has_column
from app.db.settings import DB_PATH, USE_POSTGRES

__all__ = [
    'DB_PATH',
    'USE_POSTGRES',
    'get_conn',
    'query_all',
    'query_one',
    'execute',
    'executemany',
    'reset_postgres_id_sequence',
    'table_columns',
    'table_has_column',
    'ensure_column',
    'apply_pending_migrations',
    'ensure_db',
    'ensure_indexes',
    'migration_status',
]
