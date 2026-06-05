"""Persistência de tokens de reset e tentativas de login (multi-instância)."""
import time

from app.db import execute, query_one
from app.shared.formatters import now_str


def ensure_auth_security_tables():
    from app.db import settings

    if settings.USE_POSTGRES:
        execute("""CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL,
            created_at TEXT DEFAULT ''
        )""")
        execute("""CREATE TABLE IF NOT EXISTS login_attempts (
            ip TEXT PRIMARY KEY,
            attempt_count INTEGER DEFAULT 0,
            first_at DOUBLE PRECISION NOT NULL,
            blocked_until DOUBLE PRECISION DEFAULT 0
        )""")
    else:
        execute("""CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at TEXT DEFAULT ''
        )""")
        execute("""CREATE TABLE IF NOT EXISTS login_attempts (
            ip TEXT PRIMARY KEY,
            attempt_count INTEGER DEFAULT 0,
            first_at REAL NOT NULL,
            blocked_until REAL DEFAULT 0
        )""")


def cleanup_password_reset_tokens(now_ts=None):
    now_ts = float(now_ts or time.time())
    execute('DELETE FROM password_reset_tokens WHERE expires_at < ?', (now_ts,))


def save_password_reset_token(token, email, expires_at):
    cleanup_password_reset_tokens()
    execute(
        'INSERT INTO password_reset_tokens (token, email, expires_at, created_at) VALUES (?,?,?,?)',
        (token, email, float(expires_at), now_str()),
    )


def get_password_reset_token(token):
    cleanup_password_reset_tokens()
    row = query_one(
        'SELECT token, email, expires_at FROM password_reset_tokens WHERE token=?',
        (token,),
    )
    if not row:
        return None
    return {'email': row['email'], 'expires_at': float(row['expires_at'])}


def delete_password_reset_token(token):
    execute('DELETE FROM password_reset_tokens WHERE token=?', (token,))


def get_login_attempt(ip):
    row = query_one(
        'SELECT ip, attempt_count, first_at, blocked_until FROM login_attempts WHERE ip=?',
        (ip,),
    )
    if not row:
        return None
    return {
        'count': int(row['attempt_count'] or 0),
        'first_at': float(row['first_at'] or 0),
        'blocked_until': float(row['blocked_until'] or 0),
    }


def upsert_login_attempt(ip, count, first_at, blocked_until=0):
    if get_login_attempt(ip):
        execute(
            'UPDATE login_attempts SET attempt_count=?, first_at=?, blocked_until=? WHERE ip=?',
            (int(count), float(first_at), float(blocked_until or 0), ip),
        )
    else:
        execute(
            'INSERT INTO login_attempts (ip, attempt_count, first_at, blocked_until) VALUES (?,?,?,?)',
            (ip, int(count), float(first_at), float(blocked_until or 0)),
        )


def delete_login_attempt(ip):
    execute('DELETE FROM login_attempts WHERE ip=?', (ip,))
