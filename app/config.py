"""Configuração central do IRIS (env + Flask)."""
import os
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP_TIMEZONE = os.getenv('APP_TIMEZONE', 'America/Sao_Paulo')
SESSION_IDLE_MINUTES = int(os.getenv('SESSION_IDLE_MINUTES', '120') or 120)

_INSECURE_SECRET_KEYS = frozenset({'', 'gg-web-app', 'dev', 'change-me', 'changeme'})


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


def validate_production_config(secret_key):
    """Falha cedo se produção estiver com configuração insegura."""
    if not is_production_env():
        return
    key = str(secret_key or '').strip()
    if key in _INSECURE_SECRET_KEYS or len(key) < 32:
        raise RuntimeError(
            'SECRET_KEY insegura ou ausente em produção. '
            'Defina SECRET_KEY com pelo menos 32 caracteres aleatórios no Render.'
        )


class Config:
    """Defaults carregados de variáveis de ambiente."""

    SECRET_KEY = os.getenv('SECRET_KEY', 'gg-web-app')

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '0').strip().lower() in (
        '1', 'true', 'yes', 'on',
    )
    SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', 'iris_session')
    SESSION_COOKIE_PATH = '/'
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv('SESSION_DAYS', '7') or 7))

    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', '20') or 20) * 1024 * 1024
    SEND_FILE_MAX_AGE_DEFAULT = 0

    TEMPLATES_AUTO_RELOAD = True
