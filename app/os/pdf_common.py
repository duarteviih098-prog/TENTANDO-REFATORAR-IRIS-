"""Helpers compartilhados do módulo PDF de O.S."""
import os
import threading


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


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


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def _flask_app():
    from app.runtime import flask_app
    return flask_app()


def _bg():
    from app.runtime import BACKGROUND_COMPANY_CONTEXT
    return BACKGROUND_COMPANY_CONTEXT


# PDF PERFORMANCE
_PDF_IMAGE_CACHE = {}
_PDF_IMAGE_CACHE_LOCK = threading.Lock()
_PDF_BYTES_CACHE = {}
_PDF_CACHE_LOCK = threading.Lock()
PDF_CACHE_TTL_SECONDS = int(os.getenv('PDF_CACHE_TTL_SECONDS', '600') or 600)
PDF_IMAGE_TIMEOUT_SECONDS = int(os.getenv('PDF_IMAGE_TIMEOUT_SECONDS', '5') or 5)
PDF_IMAGE_SIZE_PX = int(os.getenv('PDF_IMAGE_SIZE_PX', '200') or 200)
PDF_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MAX_IMAGES_PER_OS', '3') or 3)
PDF_MONTH_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MONTH_MAX_IMAGES_PER_OS', '2') or 2)
PDF_MONTH_MAX_OS = int(os.getenv('PDF_MONTH_MAX_OS', '80') or 80)
PDF_MONTH_BATCH_SIZE = int(os.getenv('PDF_MONTH_BATCH_SIZE', '20') or 20)

