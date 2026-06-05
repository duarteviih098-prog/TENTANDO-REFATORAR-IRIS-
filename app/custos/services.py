from app.exports.excel import excel_rows_from_upload
from app.shared.months import month_or_current
from app.shared.queries import ensure_valid_ids_for_table
from app.shared.rows import first_of

"""Regras de negócio do módulo custos."""


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def save_custo(data, rid=None):
    fields = ['sistema', 'equipamento', 'nr_os', 'descricao_os', 'local', 'manutencao', 'mes', 'empresa_id']
    payload = dict(data)
    payload['mes'] = month_or_current(payload.get('mes', ''))
    vals = [(current_company_id() if k == 'empresa_id' else payload.get(k, '')) for k in fields]
    if rid:
        execute(f"UPDATE custos SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals + [rid])
    else:
        execute(f"INSERT INTO custos({','.join(fields)}) VALUES ({','.join('?' * len(fields))})", vals)


def import_custos_excel(file_storage):
    headers, rows = excel_rows_from_upload(file_storage)
    inserted = 0
    for row in rows:
        payload = {
            'sistema': first_of(row, 'sistema'),
            'equipamento': first_of(row, 'equipamento', 'unidade', 'ativo'),
            'nr_os': first_of(row, 'nr_os', 'os', 'numero_os'),
            'descricao_os': first_of(row, 'descricao_os', 'descricao', 'servico'),
            'local': first_of(row, 'local'),
            'manutencao': first_of(row, 'manutencao', 'manutenção'),
            'mes': first_of(row, 'mes', 'mes_referencia', 'referencia'),
        }
        if not any(payload.values()):
            continue
        save_custo(payload)
        inserted += 1
    return inserted


def ensure_custos_valid_ids():
    return ensure_valid_ids_for_table('custos')

