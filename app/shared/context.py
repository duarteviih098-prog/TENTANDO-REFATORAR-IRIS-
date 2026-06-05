"""Variáveis globais de template (layout compartilhado)."""
from flask import request

from app.auth import (
    PERMISSION_LABELS,
    current_company,
    current_company_id,
    current_user_is_super_admin,
    get_current_user,
    list_companies,
    user_has,
)
from app.auth.services import _get_user_permissions
from app.shared.cache import cached_result
from app.shared.queries import fetch_sistemas_map


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)

def inject_globals():
    user = get_current_user()
    is_super = current_user_is_super_admin(user)
    company_id = current_company_id()
    company = current_company()
    path = request.path or ''
    # Sistemas/equipamentos é usado principalmente nos formulários. Cache curto evita
    # SELECT DISTINCT em várias tabelas a cada troca de aba.
    sistemas_map = cached_result(
        f'sistemas_map:{company_id}',
        fetch_sistemas_map,
        ttl=300,
    )
    companies_list = cached_result('companies:active', lambda: list_companies(active_only=True), ttl=300) if is_super else []
    from app.combustivel.constants import COMBUSTIVEL_VINCULOS
    return {
        'request_path': path,
        'app_name': 'IRIS',
        'sistemas_map': sistemas_map,
        'comb_vinculos': COMBUSTIVEL_VINCULOS,
        'current_user': user,
        'can': user_has,
        'user_has': user_has,
        'permission_labels': PERMISSION_LABELS,
        'current_company_id': company_id,
        'current_company': company,
        'companies': companies_list,
        'is_super_admin': is_super,
        'current_user_permissions': _get_user_permissions(user),
    }
