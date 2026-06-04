"""APIs JSON genéricas por módulo (GET registro / DELETE em lote)."""
import json
from app.shared.cache import clear_view_cache
from app.shared.queries import reset_sqlite_sequence_if_empty
from app.shared.rows import row_to_dict

from flask import jsonify, request

from app.auth import module_view_permission, owned_by_current_company, user_has
from app.auth.tenancy import current_company_id
from app.combustivel.services import ensure_combustivel_valid_ids
from app.custos.services import ensure_custos_valid_ids
from app.db import execute
from app.pagamentos.services import build_payment_attachment_items
from app.storage import backup_company_data, sync_os_attachments, sync_payment_attachments


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


MODULE_TABLE = {
    'controle': 'bombas',
    'combustivel': 'combustivel',
    'pagamentos': 'pagamentos',
    'custos': 'custos',
    'os': 'os_ordens',
    'os_ativos': 'os_ativos',
}

DELETE_PERM = {
    'controle': 'delete_controle',
    'combustivel': 'delete_combustivel',
    'pagamentos': 'delete_pagamentos',
    'custos': 'delete_custos',
    'os': 'delete_os',
    'os_ativos': 'edit_os',
}


def api_get(module, rid):
    perm = module_view_permission(module)
    if perm and not user_has(perm):
        return jsonify({'error': 'sem permissão'}), 403
    if module == 'combustivel':
        ensure_combustivel_valid_ids()
    elif module == 'custos':
        ensure_custos_valid_ids()
    table = MODULE_TABLE.get(module)
    if not table:
        return jsonify({'error': 'módulo inválido'}), 404
    if not owned_by_current_company(table, rid):
        return jsonify({'error': 'não encontrado'}), 404
    row = row_to_dict(query_one(f'SELECT * FROM {table} WHERE id=?', (rid,)))
    if not row:
        return jsonify({'error': 'não encontrado'}), 404
    if module == 'pagamentos':
        row = sync_payment_attachments(row, persist_db=True)
        row['attachments_all'] = build_payment_attachment_items(row)
    if module == 'os':
        row = sync_os_attachments(row, persist_db=True)
        for key in ('imagens', 'orcamentos'):
            try:
                row[key] = row.get(key) if isinstance(row.get(key), list) else json.loads(row.get(key) or '[]')
            except Exception:
                row[key] = []
    return jsonify(row)


def api_delete(module):
    delete_perm = DELETE_PERM.get(module)
    if delete_perm and not user_has(delete_perm):
        return jsonify({'ok': False, 'error': 'sem permissão'}), 403
    if module == 'combustivel':
        ensure_combustivel_valid_ids()
    elif module == 'custos':
        ensure_custos_valid_ids()
    table = MODULE_TABLE.get(module)
    if not table:
        return jsonify({'ok': False}), 404
    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids', [])
    if ids:
        ids = [int(x) for x in ids if str(x).isdigit() and owned_by_current_company(table, int(x))]
        placeholders = ','.join('?' * len(ids))
        if placeholders:
            execute(f'DELETE FROM {table} WHERE id IN ({placeholders})', ids)
        if table == 'os_ordens':
            reset_sqlite_sequence_if_empty('os_ordens')
        backup_company_data(current_company_id())
        clear_view_cache()
    return jsonify({'ok': True})


def register_api_routes(app):
    app.add_url_rule('/api/<module>/<int:rid>', 'api_get', api_get, methods=['GET'])
    app.add_url_rule('/api/<module>/delete', 'api_delete', api_delete, methods=['POST'])
