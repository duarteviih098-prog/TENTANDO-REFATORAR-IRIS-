"""Configuração de conexão (SQLite local / Postgres Supabase)."""
import os
import threading

from app.config import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / 'app.db'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
SUPABASE_DB_HOST = os.getenv('SUPABASE_DB_HOST', '').strip()
SUPABASE_DB_PORT = int(os.getenv('SUPABASE_DB_PORT', '5432') or 5432)
SUPABASE_DB_NAME = os.getenv('SUPABASE_DB_NAME', 'postgres').strip()
SUPABASE_DB_USER = os.getenv('SUPABASE_DB_USER', '').strip()
SUPABASE_DB_PASSWORD = os.getenv('SUPABASE_DB_PASSWORD', '').strip()
USE_POSTGRES = bool(DATABASE_URL or SUPABASE_DB_PASSWORD)

DB_POOL = None
DB_POOL_LOCK = threading.Lock()
