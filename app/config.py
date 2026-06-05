"""Configuração central do IRIS (env + Flask)."""
import hashlib
import os
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP_TIMEZONE = os.getenv('APP_TIMEZONE', 'America/Sao_Paulo')
SESSION_IDLE_MINUTES = int(os.getenv('SESSION_IDLE_MINUTES', '120') or 120)

_INSECURE_SECRET_KEYS = frozenset({'', 'gg-web-app', 'dev', 'change-me', 'changeme'})
_SECRET_KEY_ENV_NAMES = ('SECRET_KEY', 'FLASK_SECRET_KEY')


def is_production_env():
    """Detecta ambiente de produção (Render, DATABASE_URL remoto, flag explícita)."""
    if os.getenv('IRIS_PRODUCTION', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return True
    if os.getenv('RENDER', '').strip().lower() in ('true', '1', 'yes'):
        return True
    if os.getenv('FLASK_ENV', '').strip().lower() == 'production':
        return True
    db_url = os.getenv('DATABASE_URL', '').strip()
    return bool(db_url and not db_url.startswith('sqlite'))


def resolve_secret_key():
    """SECRET_KEY explícita ou derivada estável no Render (migração legado sem SECRET_KEY)."""
    for name in _SECRET_KEY_ENV_NAMES:
        key = os.getenv(name, '').strip()
        if key and key not in _INSECURE_SECRET_KEYS and len(key) >= 32:
            return key
    if is_production_env():
        service_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
        if len(service_key) >= 32:
            return hashlib.sha256(f'iris-v1:{service_key}'.encode('utf-8')).hexdigest()
    raw = os.getenv('SECRET_KEY', os.getenv('FLASK_SECRET_KEY', 'gg-web-app')).strip()
    return raw or 'gg-web-app'


def _validate_database_url():
    url = os.getenv('DATABASE_URL', '').strip()
    if not url or url.startswith('sqlite'):
        return
    if url.startswith(('postgresql://', 'postgres://')) and '@' not in url.split('://', 1)[1]:
        raise RuntimeError(
            'DATABASE_URL inválida no Render: falta @ entre senha e host. '
            'No Supabase: Connect → URI → postgresql://usuario:senha@host:5432/postgres'
        )


def validate_production_config(secret_key):
    """Falha cedo se produção estiver com configuração insegura."""
    if not is_production_env():
        return
    key = str(secret_key or '').strip()
    if key in _INSECURE_SECRET_KEYS or len(key) < 32:
        key = resolve_secret_key()
    if key in _INSECURE_SECRET_KEYS or len(key) < 32:
        raise RuntimeError(
            'SECRET_KEY insegura ou ausente em produção. '
            'No Render, adicione SECRET_KEY (32+ caracteres) ou mantenha SUPABASE_SERVICE_ROLE_KEY configurada.'
        )
    if not os.getenv('DATABASE_URL', '').strip():
        raise RuntimeError(
            'DATABASE_URL obrigatória em produção. Configure o Postgres/Supabase no Render.'
        )
    _validate_database_url()
    if not os.getenv('SUPABASE_URL', '').strip():
        raise RuntimeError(
            'SUPABASE_URL obrigatória em produção para anexos e storage.'
        )
    if not os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip():
        raise RuntimeError(
            'SUPABASE_SERVICE_ROLE_KEY obrigatória em produção.'
        )


def session_cookie_secure():
    """HTTPS-only cookies em produção, salvo override explícito."""
    explicit = os.getenv('SESSION_COOKIE_SECURE', '').strip().lower()
    if explicit in ('0', 'false', 'no', 'off'):
        return False
    if explicit in ('1', 'true', 'yes', 'on'):
        return True
    return is_production_env()


class Config:
    """Defaults carregados de variáveis de ambiente."""

    SECRET_KEY = resolve_secret_key()

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = session_cookie_secure()
    SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', 'iris_session')
    SESSION_COOKIE_PATH = '/'
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv('SESSION_DAYS', '7') or 7))

    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', '20') or 20) * 1024 * 1024
    SEND_FILE_MAX_AGE_DEFAULT = 0

    TEMPLATES_AUTO_RELOAD = True
