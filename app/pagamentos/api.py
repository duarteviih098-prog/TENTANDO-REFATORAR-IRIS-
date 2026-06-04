"""APIs JSON de pagamentos (live search, vencimentos, anexos)."""
import json
from datetime import timedelta
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_money, br_now, parse_num
from app.shared.months import normalize_month_reference
from app.shared.payments import payment_status_is_paid
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import row_get_value, row_to_dict

from flask import jsonify, request

from app.auth.decorators import require_permission
from app.auth.tenancy import company_where, owned_by_current_company
from app.db import execute, query_all, query_one
from app.db.schema import select_existing_columns
from app.pagamentos.services import build_payment_attachment_items, ensure_pagamentos_valid_ids
from app.storage import (
    ATTACHMENT_GROUPS,
    TENANT_UPLOAD_ROOT,
    UPLOAD_PAG,
    backup_company_data,
    resolve_local_path,
    sync_payment_attachments,
)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


@require_permission('view_pagamentos')
def api_search():
    """Live search genérico usado pelo iris-live-search.js."""
    module = request.args.get('module', '').strip()
    q = (request.args.get('q') or '').strip()
    limit = min(int(request.args.get('limit') or 30), 100)
    where_sql, params = company_where('pagamentos')
    params = list(params)

    if module == 'pagamentos-mes':
        rows = query_all(
            f'SELECT DISTINCT pagamento_mes FROM pagamentos{where_sql}'
            f" AND pagamento_mes IS NOT NULL AND pagamento_mes != ''"
            f' ORDER BY pagamento_mes DESC LIMIT {limit}',
            tuple(params),
        )
        meses = [r['pagamento_mes'] for r in rows if q.lower() in (r['pagamento_mes'] or '').lower()]
        return jsonify({'ok': True, 'results': [{'value': m, 'label': m} for m in meses]})

    if module == 'pagamentos':
        params.append(f'%{q}%')
        rows = query_all(
            f'SELECT DISTINCT fornecedor FROM pagamentos{where_sql}'
            f' AND fornecedor ILIKE ? ORDER BY fornecedor LIMIT {limit}',
            tuple(params),
        )
        return jsonify({'ok': True, 'results': [{'value': r['fornecedor'], 'label': r['fornecedor']} for r in rows]})

    return jsonify({'ok': False, 'results': [], 'error': 'Módulo não encontrado'})


@require_permission('view_pagamentos')
def api_pagamentos_vencimentos():
    where_sql, params = company_where('pagamentos')
    cols = select_existing_columns('pagamentos', ['id', 'fornecedor', 'valor', 'data_vencimento', 'status', 'pagamento_mes'])
    rows = query_all(f'SELECT {cols} FROM pagamentos{where_sql} ORDER BY id DESC LIMIT 500', tuple(params))
    hoje = br_now()
    hoje_str = hoje.strftime('%d/%m/%Y')
    amanha_str = (hoje + timedelta(days=1)).strftime('%d/%m/%Y')
    alertas = []
    for r in rows:
        venc = str(row_get_value(r, 'data_vencimento', '') or '').strip()
        status = str(row_get_value(r, 'status', '') or '').strip().lower()
        if not venc or status == 'sim':
            continue
        if venc in (hoje_str, amanha_str):
            alertas.append({
                'id': row_get_value(r, 'id', ''),
                'fornecedor': row_get_value(r, 'fornecedor', '') or 'Sem fornecedor',
                'valor': br_money(parse_num(row_get_value(r, 'valor', 0))),
                'vencimento': venc,
                'hoje': venc == hoje_str,
            })
    return jsonify({'ok': True, 'alertas': alertas})


@require_permission('view_pagamentos')
def api_pagamentos_totais_gerais():
    where_sql, params = company_where('pagamentos')
    tipo = (request.args.get('tipo') or '').strip().lower()
    extra = ''
    extra_params = list(params)
    if tipo in ('gasto', 'investimento'):
        extra = ' AND lower(COALESCE(tipo_lancamento,?)) = ?'
        extra_params += ['gasto', tipo]
    rows = query_all(f'SELECT valor FROM pagamentos{where_sql}{extra}', tuple(extra_params))
    total = sum(parse_num(row_get_value(r, 'valor', 0)) for r in rows)
    return jsonify({'ok': True, 'total': total, 'total_fmt': br_money(total), 'tipo': tipo or 'todos'})


@require_permission('view_pagamentos')
def api_pagamentos_get(rid):
    ensure_pagamentos_valid_ids()
    row = row_to_dict(query_one('SELECT * FROM pagamentos WHERE id=?', (rid,))) or {}
    if not row or not owned_by_current_company('pagamentos', rid):
        return jsonify({'ok': False, 'error': 'Pagamento não encontrado.'}), 404
    row['id'] = int(row.get('id') or rid)
    row['status'] = 'Sim' if payment_status_is_paid(row.get('status')) else 'Não'
    row['valor_num'] = parse_num(row.get('valor'))
    row['month_ref'] = normalize_month_reference(row.get('pagamento_mes'))
    row = sync_payment_attachments(row, persist_db=True)
    row['attachments_all'] = build_payment_attachment_items(row)
    row['ok'] = True
    return jsonify(row)


@require_permission('edit_pagamentos')
def api_pagamentos_attachment_delete():
    payload = request.get_json(silent=True) or {}
    rid = payload.get('id')
    grupo = str(payload.get('group') or '').strip().lower()
    idx = payload.get('index')
    if not str(rid).isdigit() or grupo not in ATTACHMENT_GROUPS or not str(idx).lstrip('-').isdigit():
        return jsonify({'ok': False, 'error': 'Parâmetros inválidos.'}), 400
    rid = int(rid)
    idx = int(idx)
    key = ATTACHMENT_GROUPS[grupo]
    row = sync_payment_attachments(rid, persist_db=True)
    if not row or not owned_by_current_company('pagamentos', rid):
        return jsonify({'ok': False, 'error': 'Pagamento não encontrado.'}), 404
    anexos = list((row or {}).get(key) or [])
    if idx < 0 or idx >= len(anexos):
        return jsonify({'ok': False, 'error': 'Anexo não encontrado.'}), 404
    removed = anexos.pop(idx)
    execute(f'UPDATE pagamentos SET {key}=? WHERE id=?', (json.dumps(anexos, ensure_ascii=False), rid))
    try:
        full = resolve_local_path(removed)
        if full and full.exists() and full.is_file() and (str(full).startswith(str(UPLOAD_PAG)) or str(full).startswith(str(TENANT_UPLOAD_ROOT))):
            full.unlink(missing_ok=True)
    except Exception:
        pass
    clear_view_cache()
    refreshed = row_to_dict(query_one('SELECT * FROM pagamentos WHERE id=?', (rid,))) or {}
    return jsonify({'ok': True, 'attachments': build_payment_attachment_items(refreshed)})


@require_permission('edit_pagamentos')
def api_pagamentos_mark_paid():
    ensure_pagamentos_valid_ids()
    payload = request.get_json(silent=True) or {}
    ids = [_safe_int_id(x) for x in (payload.get('ids') or [])]
    ids = [x for x in ids if x and owned_by_current_company('pagamentos', x)]
    if not ids:
        return jsonify({'ok': False, 'error': 'Nenhum pagamento válido selecionado.'}), 400
    placeholders = ','.join('?' * len(ids))
    execute(f"UPDATE pagamentos SET status='Sim' WHERE id IN ({placeholders})", ids)
    clear_view_cache()
    return jsonify({'ok': True, 'updated': len(ids)})


def register_api_routes(app):
    rules = [
        ('/api/search', 'api_search', api_search, ['GET']),
        ('/api/pagamentos/vencimentos', 'api_pagamentos_vencimentos', api_pagamentos_vencimentos, ['GET']),
        ('/api/pagamentos/totais-gerais', 'api_pagamentos_totais_gerais', api_pagamentos_totais_gerais, ['GET']),
        ('/api/pagamentos/<int:rid>', 'api_pagamentos_get', api_pagamentos_get, ['GET']),
        ('/api/pagamentos/attachment/delete', 'api_pagamentos_attachment_delete', api_pagamentos_attachment_delete, ['POST']),
        ('/api/pagamentos/mark-paid', 'api_pagamentos_mark_paid', api_pagamentos_mark_paid, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
