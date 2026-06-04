"""Pool PostgreSQL e conexão SQLite/Postgres."""
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

def _get_pg_pool():
    """Cria e reutiliza um pool pequeno de conexões PostgreSQL.

    Isso evita abrir uma conexão nova com o Supabase para cada SELECT.
    No Render Free isso é a diferença entre segundos e timeout.
    """
    if settings.DB_POOL is not None:
        return settings.DB_POOL
    if psycopg2 is None or SimpleConnectionPool is None:
        raise RuntimeError('psycopg2-binary não está instalado. Adicione psycopg2-binary no requirements.txt.')
    with settings.DB_POOL_LOCK:
        if settings.DB_POOL is None:
            if settings.DATABASE_URL:
                settings.DB_POOL = SimpleConnectionPool(
                    minconn=1,
                    maxconn=int(os.getenv('DB_POOL_MAXCONN', '4') or 4),
                    dsn=settings.DATABASE_URL,
                    cursor_factory=DictCursor,
                    connect_timeout=10,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                )
            else:
                settings.DB_POOL = SimpleConnectionPool(
                    minconn=1,
                    maxconn=int(os.getenv('DB_POOL_MAXCONN', '4') or 4),
                    host=settings.SUPABASE_DB_HOST,
                    port=settings.SUPABASE_DB_PORT,
                    dbname=settings.SUPABASE_DB_NAME,
                    user=settings.SUPABASE_DB_USER,
                    password=settings.SUPABASE_DB_PASSWORD,
                    sslmode='require',
                    cursor_factory=DictCursor,
                    connect_timeout=10,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                )
    return settings.DB_POOL


def _pg_getconn():
    return _get_pg_pool().getconn()


def _pg_putconn(conn):
    try:
        _get_pg_pool().putconn(conn)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


class _PostgresCursorCompat:
    def __init__(self, conn, cursor=None):
        self._conn = conn
        self._cursor = cursor or conn._raw.cursor(cursor_factory=DictCursor)
        self.lastrowid = None

    def execute(self, sql, params=()):
        sql2, params2, kind = _normalize_pg_sql(sql, params)
        if kind == 'noop':
            self._cursor.execute(sql2, params2)
            return self
        self._cursor.execute(sql2, params2)
        self.lastrowid = None
        return self

    def executemany(self, sql, seq_of_params):
        sql2, _, kind = _normalize_pg_sql(sql, ())
        if kind == 'noop':
            return self
        self._cursor.executemany(sql2, list(seq_of_params or []))
        self.lastrowid = None
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass

    def __iter__(self):
        return iter(self._cursor)


class _PostgresConnectionCompat:
    def __init__(self):
        self._raw = _pg_getconn()
        self._closed = False

    def cursor(self):
        return _PostgresCursorCompat(self)

    def execute(self, sql, params=()):
        """Normaliza e executa — usado por fetch_sistemas_map e outros que chamam conn.execute diretamente."""
        cur = _PostgresCursorCompat(self)
        return cur.execute(sql, params)

    def executemany(self, sql, rows):
        cur = self.cursor()
        return cur.executemany(sql, rows)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if settings.USE_POSTGRES:
            try:
                self._raw.rollback()
            except Exception:
                pass
            _pg_putconn(self._raw)
        else:
            self._raw.close()


def get_conn():
    if settings.USE_POSTGRES:
        return _PostgresConnectionCompat()

    conn = sqlite3.connect(settings.DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA cache_size=-32000')
    conn.execute('PRAGMA busy_timeout=12000')
    return conn
