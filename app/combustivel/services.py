"""Regras de negócio do módulo combustível."""
import re
from datetime import datetime

from app.auth import company_where, current_company_id
from app.combustivel.constants import COMBUSTIVEL_VINCULOS
from app.db import execute, query_all
from app.exports.excel import excel_rows_from_upload
from app.shared.formatters import parse_num
from app.shared.months import month_or_current
from app.shared.queries import ensure_valid_ids_for_table
from app.shared.rows import first_of, row_to_dict


def _combustivel_payload(data):
    payload = {k: str(data.get(k, '') or '').strip() for k in ['data', 'mes_ref', 'modelo_veiculo', 'placa', 'motorista', 'km', 'custo', 'observacoes']}
    if not payload.get('mes_ref') and payload.get('data'):
        try:
            payload['mes_ref'] = datetime.strptime(payload['data'], '%d/%m/%Y').strftime('%m/%Y')
        except Exception:
            pass
    return payload


def _norm_text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip()).upper()


def _norm_placa(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def _norm_num(value):
    return round(parse_num(value), 2)


def combustivel_duplicado(data, rid=None):
    """Retorna um lançamento existente se os dados principais já estiverem cadastrados."""
    payload = _combustivel_payload(data)
    where_sql, params = company_where('combustivel')
    rows = query_all('SELECT * FROM combustivel' + where_sql, tuple(params))
    for row in rows:
        if rid and str(row['id']) == str(rid):
            continue
        mesmo = (
            _norm_text(row['data']) == _norm_text(payload.get('data')) and
            _norm_text(row['mes_ref']) == _norm_text(payload.get('mes_ref')) and
            _norm_text(row['modelo_veiculo']) == _norm_text(payload.get('modelo_veiculo')) and
            _norm_placa(row['placa']) == _norm_placa(payload.get('placa')) and
            _norm_text(row['motorista']) == _norm_text(payload.get('motorista')) and
            _norm_num(row['km']) == _norm_num(payload.get('km')) and
            _norm_num(row['custo']) == _norm_num(payload.get('custo'))
        )
        if mesmo:
            return row
    return None


def save_combustivel(data, rid=None):
    fields = ['data', 'mes_ref', 'modelo_veiculo', 'placa', 'motorista', 'km', 'custo', 'observacoes', 'empresa_id']
    payload = _combustivel_payload(data)
    payload['mes_ref'] = month_or_current(payload.get('mes_ref') or payload.get('data') or '')
    payload['empresa_id'] = current_company_id()
    vals = [payload.get(k, '') for k in fields]
    if rid:
        execute(f"UPDATE combustivel SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals + [rid])
    else:
        execute(f"INSERT INTO combustivel({','.join(fields)}) VALUES ({','.join('?' * len(fields))})", vals)


def import_combustivel_excel(file_storage):
    headers, rows = excel_rows_from_upload(file_storage)
    inserted = 0
    for row in rows:
        payload = {
            'data': first_of(row, 'data', 'dia', 'data_abastecimento'),
            'mes_ref': first_of(row, 'mes_ref', 'mes', 'mes_referencia', 'referencia'),
            'modelo_veiculo': first_of(row, 'modelo_veiculo', 'modelo', 'veiculo'),
            'placa': first_of(row, 'placa'),
            'motorista': first_of(row, 'motorista', 'condutor'),
            'km': first_of(row, 'km', 'quilometragem'),
            'custo': first_of(row, 'custo', 'valor', 'total', 'valor_total'),
            'observacoes': first_of(row, 'observacoes', 'obs', 'observacao'),
        }
        if not any(payload.values()):
            continue
        if combustivel_duplicado(payload):
            continue
        save_combustivel(payload)
        inserted += 1
    return inserted


def get_comb_vinculos(empresa_id=None):
    """Retorna motoristas/veículos do banco ou fallback na constante."""
    try:
        if empresa_id:
            rows = query_all('SELECT * FROM combustivel_veiculos WHERE empresa_id=? AND ativo=1 ORDER BY motorista', (empresa_id,))
        else:
            rows = query_all('SELECT * FROM combustivel_veiculos WHERE ativo=1 ORDER BY motorista')
        if rows:
            return [row_to_dict(r) for r in rows]
    except Exception:
        pass
    return COMBUSTIVEL_VINCULOS


def ensure_combustivel_valid_ids():
    return ensure_valid_ids_for_table('combustivel')

