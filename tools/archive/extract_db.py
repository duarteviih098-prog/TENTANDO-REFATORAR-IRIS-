"""Extract DB layer from legacy.py into app/db/ (Module 2)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
lines = legacy_path.read_text(encoding='utf-8').splitlines(keepends=True)
DB = ROOT / 'app' / 'db'
DB.mkdir(exist_ok=True)


def grab(start, end):
    return ''.join(lines[start - 1:end])


(DB / 'settings.py').write_text(
    '''"""Configuração de conexão (SQLite local / Postgres Supabase)."""
import os
import threading

from app.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / 'app.db'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
SUPABASE_DB_HOST = os.getenv('SUPABASE_DB_HOST', 'aws-1-us-west-2.pooler.supabase.com').strip()
SUPABASE_DB_PORT = int(os.getenv('SUPABASE_DB_PORT', '5432') or 5432)
SUPABASE_DB_NAME = os.getenv('SUPABASE_DB_NAME', 'postgres').strip()
SUPABASE_DB_USER = os.getenv('SUPABASE_DB_USER', 'postgres.njbzfjbponspalirndqj').strip()
SUPABASE_DB_PASSWORD = os.getenv('SUPABASE_DB_PASSWORD', '').strip()
USE_POSTGRES = bool(DATABASE_URL or SUPABASE_DB_PASSWORD)

DB_POOL = None
DB_POOL_LOCK = threading.Lock()
''',
    encoding='utf-8',
)

(DB / 'utils.py').write_text(
    '''"""Utilitários internos da camada de banco."""


def row_get_value(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        try:
            return getattr(row, key)
        except Exception:
            return default
''',
    encoding='utf-8',
)

dialect = grab(3091, 3200)
dialect = dialect.replace('USE_POSTGRES', 'settings.USE_POSTGRES')
(DB / 'dialect.py').write_text(
    '''"""Tradução SQLite → PostgreSQL."""
import re

from app.db import settings

'''
    + dialect,
    encoding='utf-8',
)

# Patch _insert_can_return_id to lazy-import table_has_column
dialect_path = DB / 'dialect.py'
text = dialect_path.read_text(encoding='utf-8')
text = text.replace(
    '        return table_has_column(table, \'id\')',
    '        from app.db.schema import table_has_column\n        return table_has_column(table, \'id\')',
)
dialect_path.write_text(text, encoding='utf-8')

connection = grab(3203, 3349)
import re as _re
for old, new in [
    ('DB_POOL', 'settings.DB_POOL'),
    ('DB_POOL_LOCK', 'settings.DB_POOL_LOCK'),
    ('DATABASE_URL', 'settings.DATABASE_URL'),
    ('SUPABASE_DB_HOST', 'settings.SUPABASE_DB_HOST'),
    ('SUPABASE_DB_PORT', 'settings.SUPABASE_DB_PORT'),
    ('SUPABASE_DB_NAME', 'settings.SUPABASE_DB_NAME'),
    ('SUPABASE_DB_USER', 'settings.SUPABASE_DB_USER'),
    ('SUPABASE_DB_PASSWORD', 'settings.SUPABASE_DB_PASSWORD'),
    ('USE_POSTGRES', 'settings.USE_POSTGRES'),
    ('DB_PATH', 'settings.DB_PATH'),
]:
    connection = _re.sub(rf'\b{old}\b', new, connection)
connection = connection.replace('global settings.DB_POOL\n', '')
connection = connection.replace('settings.settings.', 'settings.')
connection = connection.replace("os.getenv('settings.DB_POOL_MAXCONN'", "os.getenv('DB_POOL_MAXCONN'")

(DB / 'connection.py').write_text(
    '''"""Pool PostgreSQL e conexão SQLite/Postgres."""
import os
import sqlite3
import threading

from app.db import settings
from app.db.dialect import _normalize_pg_sql

try:
    import psycopg2  # type: ignore
    from psycopg2.extras import DictCursor  # type: ignore
    from psycopg2.pool import SimpleConnectionPool  # type: ignore
except Exception:
    psycopg2 = None
    DictCursor = None
    SimpleConnectionPool = None

'''
    + connection,
    encoding='utf-8',
)

queries = grab(3369, 3480)
queries = queries.replace('USE_POSTGRES', 'settings.USE_POSTGRES')
queries = queries.replace('clear_view_cache()', '_notify_write()')
(DB / 'queries.py').write_text(
    '''"""API de consultas e escrita."""
import re

from app.db import settings
from app.db.connection import DictCursor, get_conn
from app.db.dialect import (
    _insert_can_return_id,
    _is_insert_without_returning,
    _maybe_reset_sequence_from_duplicate_error,
    _normalize_pg_sql,
)

USE_POSTGRES = settings.USE_POSTGRES


def _notify_write():
    try:
        from app import legacy
        legacy.clear_view_cache()
    except Exception:
        pass

'''
    + queries,
    encoding='utf-8',
)

schema = grab(1343, 1402) + '\n\n' + grab(3539, 3555)
schema = schema.replace('row_get_value', 'row_get_value')
schema = schema.replace('USE_POSTGRES', 'settings.USE_POSTGRES')
(DB / 'schema.py').write_text(
    '''"""Introspecção de schema e colunas."""
from app.db import settings
from app.db.connection import get_conn
from app.db.queries import execute
from app.db.utils import row_get_value

USE_POSTGRES = settings.USE_POSTGRES

'''
    + schema,
    encoding='utf-8',
)

migrations = grab(3671, 4036) + '\n\n' + grab(15151, 15181)
migrations = migrations.replace('USE_POSTGRES', 'settings.USE_POSTGRES')
migrations = migrations.replace(
    'def ensure_db():',
    'def ensure_db():\n    from app.legacy import COMBUSTIVEL_VINCULOS, _token_expira_str, now_str, row_to_dict',
    1,
)
(DB / 'migrations.py').write_text(
    '''"""Migrations leves (CREATE TABLE / colunas / índices)."""
from app.db import settings
from app.db.queries import execute, query_all
from app.db.schema import ensure_column

USE_POSTGRES = settings.USE_POSTGRES

'''
    + migrations,
    encoding='utf-8',
)

(DB / '__init__.py').write_text(
    '''"""Camada de banco de dados IRIS."""
from app.db.connection import get_conn
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
    'ensure_db',
    'ensure_indexes',
]
''',
    encoding='utf-8',
)

# Remove extracted blocks from legacy (reverse order to preserve line numbers roughly)
remove_ranges = [
    (15151, 15181),
    (3671, 4036),
    (3539, 3555),
    (3369, 3480),
    (3091, 3349),
    (1343, 1402),
    (290, 298),
    (255, 262),
]
for start, end in remove_ranges:
    del lines[start - 1:end]

legacy_path.write_text(''.join(lines), encoding='utf-8')
print('legacy.py lines after cut:', len(lines))

import_block = '''
from app.db import (
    DB_PATH,
    USE_POSTGRES,
    ensure_column,
    ensure_db,
    ensure_indexes,
    execute,
    executemany,
    get_conn,
    query_all,
    query_one,
    reset_postgres_id_sequence,
    table_columns,
    table_has_column,
)
from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE
'''

content = legacy_path.read_text(encoding='utf-8')
marker = 'from app.config import APP_TIMEZONE, PROJECT_ROOT, SESSION_IDLE_MINUTES'
if import_block.strip() not in content:
    content = content.replace(marker, marker + import_block)
    legacy_path.write_text(content, encoding='utf-8')

print('done')
