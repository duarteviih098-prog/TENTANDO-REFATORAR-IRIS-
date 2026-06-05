"""Helpers compartilhados das rotas Campo."""
from app.auth import owned_by_current_company, user_has


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin(user=None):
    from app.auth import current_user_is_super_admin as fn
    return fn(user)


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def company_and(table):
    from app.auth import company_and as fn
    return fn(table)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def get_conn():
    from app.db import get_conn as fn
    return fn()


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_db():
    from app.db import ensure_db as fn
    return fn()


def tenant_upload_dir(kind, empresa_id=None):
    from app.storage import tenant_upload_dir as fn
    return fn(kind, empresa_id)


def company_folder_name(empresa_id=None):
    from app.storage import company_folder_name as fn
    return fn(empresa_id)


def ensure_company_storage(empresa_id=None):
    from app.storage import ensure_company_storage as fn
    return fn(empresa_id)


def load_whatsapp_templates(empresa_id=None):
    from app.storage import load_whatsapp_templates as fn
    return fn(empresa_id)


def save_whatsapp_templates(items, empresa_id=None):
    from app.storage import save_whatsapp_templates as fn
    return fn(items, empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)


def _flask_app():
    from app.runtime import flask_app
    return flask_app()

