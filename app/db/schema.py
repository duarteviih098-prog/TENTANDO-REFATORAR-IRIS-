"""Introspecção de schema e colunas."""
from app.db import settings
from app.db.connection import get_conn
from app.db.queries import execute
from app.db.utils import row_get_value

USE_POSTGRES = settings.USE_POSTGRES

_TABLE_COLUMN_CACHE = {}
_TABLE_COLUMNS_CACHE = {}

def table_columns(table):
    """Retorna as colunas reais de uma tabela, com cache.

    Importante para Supabase/PostgreSQL: nem todo backup antigo tem exatamente
    as mesmas colunas que o app espera. A dashboard e os filtros usam isso para
    não quebrar com UndefinedColumn.
    """
    table = str(table or '').strip()
    if not table:
        return set()
    if table in _TABLE_COLUMNS_CACHE:
        return _TABLE_COLUMNS_CACHE[table]
    cols = set()
    conn = None
    try:
        conn = get_conn()
        rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
        for r in rows:
            name = row_get_value(r, 'name', '')
            if name:
                cols.add(str(name))
    except Exception:
        cols = set()
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    _TABLE_COLUMNS_CACHE[table] = cols
    return cols

def select_existing_columns(table, desired, fallback='id'):
    """Monta SELECT só com colunas existentes.

    desired pode ser lista/tupla ou string separada por vírgula.
    """
    if isinstance(desired, str):
        desired_cols = [c.strip() for c in desired.split(',') if c.strip()]
    else:
        desired_cols = [str(c).strip() for c in (desired or []) if str(c).strip()]
    existing = table_columns(table)
    cols = [c for c in desired_cols if c in existing]
    if not cols:
        if fallback and fallback in existing:
            cols = [fallback]
        else:
            cols = ['*']
    return ','.join(cols)

def table_has_column(table, column):
    cache_key = (str(table), str(column))
    if cache_key in _TABLE_COLUMN_CACHE:
        return _TABLE_COLUMN_CACHE[cache_key]
    result = str(column) in table_columns(table)
    _TABLE_COLUMN_CACHE[cache_key] = result
    return result


def ensure_column(table, column, ddl):
    """Adiciona coluna se não existir. Funciona em SQLite e PostgreSQL."""
    if table_has_column(table, column):
        return
    try:
        if settings.USE_POSTGRES:
            execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}')
        else:
            conn = get_conn()
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
            conn.commit()
            conn.close()
        # Limpa cache para que table_has_column reflita a nova coluna
        _TABLE_COLUMN_CACHE.pop((str(table), str(column)), None)
        _TABLE_COLUMNS_CACHE.pop(str(table), None)
    except Exception as exc:
        print(f'ensure_column({table}.{column}) falhou:', exc)
