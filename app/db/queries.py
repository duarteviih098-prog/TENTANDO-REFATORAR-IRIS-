"""API de consultas e escrita."""
import re

from app.db import settings
from app.db.connection import DictCursor, get_conn
from app.db.dialect import (
    _insert_can_return_id,
    _is_insert_without_returning,
    _normalize_pg_sql,
)

USE_POSTGRES = settings.USE_POSTGRES


def _notify_write():
    try:
        from app.shared.cache import clear_view_cache
        clear_view_cache()
    except Exception:
        pass

def reset_postgres_id_sequence(table_name, id_column='id'):
    """Sincroniza a sequence do Postgres com MAX(id). Evita duplicate key em imports/backups."""
    if not settings.USE_POSTGRES:
        return False
    table_name = str(table_name or '').strip()
    id_column = str(id_column or 'id').strip()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table_name) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', id_column):
        return False
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT pg_get_serial_sequence(%s, %s) AS seq", (table_name, id_column))
        row = cur.fetchone()
        seq = row['seq'] if row and 'seq' in row.keys() else None
        if not seq:
            conn.commit()
            return False
        cur.execute(f"SELECT COALESCE(MAX({id_column}), 0) AS max_id FROM {table_name}")
        row = cur.fetchone()
        max_id = int((row['max_id'] if row and 'max_id' in row.keys() else 0) or 0)
        cur.execute("SELECT setval(%s, %s, %s)", (seq, max_id + 1, False))
        conn.commit()
        return True
    except Exception as exc:
        try: conn.rollback()
        except Exception: pass
        print(f'reset_postgres_id_sequence falhou em {table_name}:', exc)
        return False
    finally:
        try: conn.close()
        except Exception: pass


def _maybe_reset_sequence_from_duplicate_error(exc):
    msg = str(exc or '')
    m = re.search(r'unique constraint "([A-Za-z0-9_]+)_pkey"', msg)
    if m:
        return reset_postgres_id_sequence(m.group(1))
    return False

def query_one(sql, params=()):
    conn = get_conn()
    try:
        if settings.USE_POSTGRES:
            sql2, params2, kind = _normalize_pg_sql(sql, params)
            if kind == 'noop':
                return None
            raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
            raw_cur.execute(sql2, params2)
            return raw_cur.fetchone()
        else:
            return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def query_all(sql, params=()):
    conn = get_conn()
    try:
        if settings.USE_POSTGRES:
            sql2, params2, kind = _normalize_pg_sql(sql, params)
            if kind == 'noop':
                return []
            raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
            raw_cur.execute(sql2, params2)
            return raw_cur.fetchall()
        else:
            return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_conn()
    try:
        if settings.USE_POSTGRES:
            sql2, params2, kind = _normalize_pg_sql(sql, params)
            # Usa cursor RAW — sql2 já normalizado, sem double-processing
            if kind == 'noop':
                raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
                raw_cur.execute(sql2, params2)
                conn.commit()
                rid = None
            elif _is_insert_without_returning(sql2):
                raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
                if _insert_can_return_id(sql2):
                    try:
                        raw_cur.execute(sql2.rstrip().rstrip(';') + ' RETURNING id', params2)
                        row = raw_cur.fetchone()
                        rid = row['id'] if row and 'id' in (row.keys() if hasattr(row,'keys') else []) else None
                    except Exception as exc:
                        conn.rollback()
                        if _maybe_reset_sequence_from_duplicate_error(exc):
                            raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
                            raw_cur.execute(sql2.rstrip().rstrip(';') + ' RETURNING id', params2)
                            row = raw_cur.fetchone()
                            rid = row['id'] if row and 'id' in (row.keys() if hasattr(row,'keys') else []) else None
                        else:
                            raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
                            raw_cur.execute(sql2, params2)
                            rid = None
                else:
                    raw_cur.execute(sql2, params2)
                    rid = None
                conn.commit()
            else:
                raw_cur = conn._raw.cursor(cursor_factory=DictCursor)
                raw_cur.execute(sql2, params2)
                conn.commit()
                rid = None
        else:
            cur = conn.execute(sql, params)
            conn.commit()
            rid = cur.lastrowid
    finally:
        conn.close()
    _notify_write()
    return rid


def executemany(sql, rows):
    conn = get_conn()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    _notify_write()
