"""Regras de negócio do estoque de bombas (controle)."""
from datetime import datetime, timedelta
from app.exports.excel import excel_rows_from_upload
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, parse_br_date
from app.shared.queries import list_page
from app.shared.rows import first_of, row_get_value, row_matches_month, row_to_dict

from app.auth import company_and, company_where, current_company_id
from app.db import execute, query_all, query_one


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)

def company_and(table):
    from app.auth import company_and as fn
    return fn(table)

def compute_bomba_delivery(data, existing=None):
    payload = {k: str(v or '').strip() for k, v in (existing or {}).items()}
    payload.update({k: str(v or '').strip() for k, v in data.items()})
    localizacao = (payload.get('localizacao') or 'estoque').strip().lower()
    if localizacao not in ('estoque', 'conserto', 'retirada'):
        localizacao = 'estoque'
    payload['localizacao'] = localizacao
    payload['em_estoque'] = 'Sim' if localizacao == 'estoque' else ''
    payload['em_conserto'] = 'Sim' if localizacao == 'conserto' else ''
    payload['destino_retirada'] = payload.get('destino_retirada', '').strip() if localizacao == 'retirada' else ''

    abertura = parse_br_date(payload.get('data_abertura')) or datetime.now()
    payload['data_abertura'] = abertura.strftime('%d/%m/%Y')

    previsao = parse_br_date(payload.get('previsao_entrega'))
    if not previsao:
        previsao = abertura + timedelta(days=1)
    payload['previsao_entrega'] = previsao.strftime('%d/%m/%Y')

    recebido = parse_br_date(payload.get('recebido_em')) or parse_br_date(payload.get('data_entrega'))
    if recebido:
        payload['recebido_em'] = recebido.strftime('%d/%m/%Y')
        payload['data_entrega'] = recebido.strftime('%d/%m/%Y')
    else:
        payload['recebido_em'] = ''

    hoje = br_now().date()
    previsao_date = previsao.date()
    status_informado = (payload.get('status_entrega') or '').strip()
    if recebido:
        status_entrega = 'Entregue'
    elif previsao_date < hoje:
        status_entrega = 'Em atraso'
    else:
        status_entrega = 'Em andamento'
    payload['status_entrega'] = status_entrega if not status_informado or status_informado.lower() != 'manual' else status_informado

    status_base = (payload.get('status') or '').strip()
    if localizacao == 'retirada':
        payload['status'] = 'Retirada de estoque'
    elif not status_base:
        payload['status'] = 'Em estoque' if localizacao == 'estoque' else 'Em conserto'
    elif status_entrega == 'Entregue' and localizacao == 'estoque':
        payload['status'] = 'Em estoque'
    elif localizacao == 'conserto' and status_entrega in ('Em andamento', 'Em atraso'):
        payload['status'] = 'Em conserto'
    return payload


def fetch_bombas_counts():
    """Contadores de bombas sem puxar a tabela inteira."""
    try:
        where_sql, params = company_where('bombas')
        row = query_one(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN lower(COALESCE(localizacao,''))='estoque' THEN 1 ELSE 0 END) AS em_estoque,
                SUM(CASE WHEN lower(COALESCE(localizacao,''))='conserto' THEN 1 ELSE 0 END) AS em_conserto,
                SUM(CASE WHEN lower(COALESCE(localizacao,''))='retirada' THEN 1 ELSE 0 END) AS retiradas,
                SUM(CASE WHEN lower(COALESCE(status_entrega,''))='em atraso' THEN 1 ELSE 0 END) AS atrasadas
            FROM bombas
            """ + where_sql,
            tuple(params)
        ) or {}
        return {
            'total': int(row_get_value(row, 'total', 0) or 0),
            'em_estoque': int(row_get_value(row, 'em_estoque', 0) or 0),
            'em_conserto': int(row_get_value(row, 'em_conserto', 0) or 0),
            'retiradas': int(row_get_value(row, 'retiradas', 0) or 0),
            'atrasadas': int(row_get_value(row, 'atrasadas', 0) or 0),
        }
    except Exception:
        rows = list_page('bombas')
        total = len(rows)
        em_estoque = sum(1 for r in rows if str(row_get_value(r, 'localizacao', '') or '').lower() == 'estoque')
        em_conserto = sum(1 for r in rows if str(row_get_value(r, 'localizacao', '') or '').lower() == 'conserto')
        retiradas = sum(1 for r in rows if str(row_get_value(r, 'localizacao', '') or '').lower() == 'retirada')
        atrasadas = sum(1 for r in rows if str(row_get_value(r, 'status_entrega', '') or '').lower() == 'em atraso')
        return {'total': total, 'em_estoque': em_estoque, 'em_conserto': em_conserto, 'retiradas': retiradas, 'atrasadas': atrasadas}


def save_bomba(data, rid=None):
    existing = row_to_dict(query_one('SELECT * FROM bombas WHERE id=?', (rid,))) if rid else {}
    raw = data.to_dict(flat=True) if hasattr(data, 'to_dict') else dict(data)
    payload = compute_bomba_delivery(raw, existing)
    payload['tipo'] = payload.get('tipo') or 'Bomba'
    payload['nome'] = payload.get('nome') or payload.get('equipamento') or ''
    payload['descricao'] = payload.get('descricao') or payload.get('obs') or payload.get('observacoes') or ''
    payload['observacoes'] = payload.get('observacoes') or payload.get('obs') or ''
    payload['data_entrada'] = payload.get('data_entrada') or payload.get('data_abertura')
    payload['data_estimada'] = payload.get('data_estimada') or payload.get('previsao_entrega')
    fields = ['tipo','nome','modelo','descricao','fornecedor','sistema','equipamento','valor','orcamento','em_estoque','em_conserto','data_entrada','data_estimada','data_entrega','status','observacoes','localizacao','pedido_aberto','previsao_entrega','status_entrega','data_abertura','recebido_em','obs','destino_retirada','local_id','empresa_id']
    payload['empresa_id'] = current_company_id()
    vals = [payload.get(k,'') for k in fields]
    if rid:
        execute(f"UPDATE bombas SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals+[rid])
    else:
        execute(f"INSERT INTO bombas({','.join(fields)}) VALUES ({','.join('?'*len(fields))})", vals)


def import_controle_excel(file_storage):
    headers, rows = excel_rows_from_upload(file_storage)
    inserted = 0
    for row in rows:
        localizacao = first_of(row, 'localizacao', 'aba', 'tipo_local', 'estoque_ou_conserto').lower()
        if localizacao not in ('estoque','conserto','retirada'):
            if first_of(row, 'em_conserto', 'conserto').strip().lower() in ('sim','s','1','true','x'): localizacao = 'conserto'
            else: localizacao = 'estoque'
        payload = {
            'equipamento': first_of(row, 'equipamento', 'nome', 'ativo'),
            'nome': first_of(row, 'equipamento', 'nome', 'ativo'),
            'modelo': first_of(row, 'modelo'),
            'obs': first_of(row, 'obs', 'observacoes', 'observacao'),
            'observacoes': first_of(row, 'observacoes', 'observacao', 'obs'),
            'valor': first_of(row, 'valor'),
            'pedido_aberto': first_of(row, 'pedido_aberto', 'pedido', 'pedidoaberto'),
            'orcamento': first_of(row, 'orcamento', 'orçamento'),
            'previsao_entrega': first_of(row, 'previsao_entrega', 'previsao', 'entrega_prevista'),
            'status_entrega': first_of(row, 'status_entrega'),
            'status': first_of(row, 'status'),
            'fornecedor': first_of(row, 'fornecedor'),
            'em_estoque': first_of(row, 'em_estoque', 'estoque'),
            'em_conserto': first_of(row, 'em_conserto', 'conserto'),
            'localizacao': localizacao,
            'data_abertura': first_of(row, 'data_abertura', 'abertura', 'data_entrada', 'entrada'),
            'recebido_em': first_of(row, 'recebido_em', 'data_recebimento', 'recebido'),
        }
        if localizacao == 'estoque' and not payload['em_estoque']:
            payload['em_estoque'] = 'Sim'
        if localizacao == 'conserto' and not payload['em_conserto']:
            payload['em_conserto'] = 'Sim'
        if not any(payload.values()):
            continue
        save_bomba(payload)
        inserted += 1
    return inserted
