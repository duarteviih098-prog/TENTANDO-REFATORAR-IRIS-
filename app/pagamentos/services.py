"""Regras de negócio do módulo pagamentos."""
import json
import re
from datetime import datetime
from pathlib import Path
from app.exports.excel import excel_rows_from_upload
from app.os.pdf import _draw_pdf_header, excel_file, table_pdf
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_money, br_now, now_str, parse_br_date, parse_num
from app.shared.months import month_reference_matches_selected, normalize_month_reference
from app.shared.payments import payment_status_is_paid
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import first_of, row_get_value, row_to_dict
from app.storage import backup_company_data

from werkzeug.utils import secure_filename

from app.auth import company_where, current_company_id, owned_by_current_company
from app.db import USE_POSTGRES, execute, get_conn, query_all, query_one, reset_postgres_id_sequence, table_columns
from app.storage import (
    ATTACHMENT_GROUPS,
    PAYMENT_STORAGE_FOLDER,
    _payment_attachment_relpath,
    company_folder_name,
    normalize_payment_attachment_list,
    tenant_upload_dir,
    upload_file_to_supabase,
)

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

def owned_by_current_company(table, rid):
    from app.auth.tenancy import owned_by_current_company as fn
    return fn(table, rid)

def get_current_user():
    from app.auth import get_current_user as fn
    return fn()

def app_logger():
    from flask import current_app
    return current_app.logger



def prepare_payment_row_for_template(row):
    """Prepara pagamento para a tela, garantindo ID, mês, valor e anexos."""
    row = row_to_dict(row) if row is not None else {}
    if not isinstance(row, dict):
        row = dict(row)

    # Alguns drivers/consultas antigas podem devolver id como string/chave diferente.
    rid = row.get('id') or row.get('pagamento_id') or row.get('rowid') or row.get('ID')
    try:
        rid = int(rid) if str(rid or '').isdigit() else rid
    except Exception:
        pass
    row['id'] = rid

    row['month_ref'] = normalize_month_reference(row.get('pagamento_mes') or row.get('month_ref') or '')
    row['valor_num'] = parse_num(row.get('valor', 0))
    row['status'] = 'Sim' if payment_status_is_paid(row.get('status')) else 'Não'

    try:
        row = sync_payment_attachments(row, persist_db=False)
    except Exception:
        pass

    attachments = build_payment_attachment_items(row)
    row['attachments_all'] = attachments
    row['has_files'] = bool(attachments)
    row['file_types'] = ' '.join(sorted(set(str(a.get('group') or '') for a in attachments if a.get('group'))))
    return row




def build_payment_attachment_items(row):
    items = []
    if row is None:
        return items
    rid = row_get_value(row, 'id')
    for group, key in ATTACHMENT_GROUPS.items():
        label = {'orcamento': 'Orçamento', 'nf': 'NF', 'boleto': 'Boleto'}.get(group, group.title())
        values = row_get_value(row, key, []) or []
        for idx, stored in enumerate(values):
            raw = str(stored or '')
            name = Path(raw.replace('\\', '/')).name or f'{label} {idx+1}'
            ext = Path(name).suffix.lower()
            previewable = ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf'}
            icon = 'bi-file-earmark'
            if ext == '.pdf':
                icon = 'bi-file-earmark-pdf-fill'
            elif ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif'}:
                icon = 'bi-image-fill'
            elif ext in {'.xls', '.xlsx', '.xlsm', '.csv'}:
                icon = 'bi-file-earmark-excel-fill'
            items.append({
                'group': group,
                'group_key': key,
                'label': label,
                'index': idx,
                'path': raw,
                'name': name,
                'previewable': previewable,
                'icon': icon,
                'url': f'/pagamentos/anexo/{rid}/{group}/{idx}' if rid else '#',
            })
    return items



def sync_payment_attachments(row, persist_db=False):
    from app.storage import sync_payment_attachments as fn
    return fn(row, persist_db=persist_db)

def import_pagamentos_excel(file_storage, mes_override=None):
    headers, rows = excel_rows_from_upload(file_storage)
    inserted = 0
    for row in rows:
        pago = first_of(row, 'pago', 'status')
        if pago:
            pago = 'Sim' if pago.strip().lower() in ('sim','s','yes','true','1','pago') else 'Não'
        payload = {
            'fornecedor': first_of(row, 'fornecedor'),
            'descricao_servico': first_of(row, 'descricao_servico', 'descricao', 'servico', 'descricao_servico_objeto'),
            'valor': first_of(row, 'valor', 'valor_total', 'total'),
            'status': pago or 'Não',
            'nf_proposta': first_of(row, 'nf_proposta', 'nf', 'proposta'),
            'acao': first_of(row, 'acao'),
            'pagamento_mes': mes_override or first_of(row, 'pagamento_mes', 'mes', 'mes_referencia', 'referencia'),
            'numero_documento': first_of(row, 'numero_documento', 'sc', 'numero_sc', 'solicitacao_compra'),
            'sc_pedido': first_of(row, 'sc_pedido', 'pedido', 'numero_pedido', 'pd'),
            'aprovado': first_of(row, 'aprovado'),
            'tipo_documento': first_of(row, 'tipo_documento', 'tipo'),
            'fluxo_status': first_of(row, 'fluxo_status', 'fluxo', 'status_fluxo'),
        }
        if not any(payload.values()):
            continue
        save_pagamento(payload, None)
        inserted += 1
    return inserted






def payment_month_or_current(value=''):
    """Normaliza mês de pagamento e usa o mês atual quando vier vazio."""
    ref = normalize_month_reference(value)
    if ref:
        return ref
    agora = br_now()
    return f"{agora.month:02d}/{agora.year:04d}"




def _next_pagamento_id(conn=None):
    """Próximo ID numérico seguro para tabelas antigas com id manual/texto."""
    close_conn = False
    if conn is None:
        conn = get_conn()
        close_conn = True
    try:
        rows = conn.execute('SELECT id FROM pagamentos').fetchall()
        max_id = 0
        for row in rows or []:
            rid = _safe_int_id(row_get_value(row, 'id', ''))
            if rid and rid > max_id:
                max_id = rid
        return max_id + 1
    finally:
        if close_conn:
            try: conn.close()
            except Exception: pass




def ensure_pagamentos_valid_ids():
    """Repara pagamentos antigos sem ID antes de listar/editar/excluir.

    Alguns registros antigos/importados chegaram com id vazio/nulo. Como a tela,
    o modal e as APIs trabalham por ID, isso fazia uma linha virar 'fantasma':
    não editava, não excluía e podia confundir a seleção. Esta função dá um ID
    real e único para cada linha problemática.
    """
    if 'id' not in table_columns('pagamentos'):
        return 0

    conn = get_conn()
    fixed = 0
    try:
        if USE_POSTGRES:
            rows = conn.execute("SELECT ctid, id FROM pagamentos WHERE id IS NULL OR TRIM(id::text)='' OR id::text !~ '^[0-9]+$'").fetchall()
            for row in rows or []:
                new_id = _next_pagamento_id(conn)
                conn.execute('UPDATE pagamentos SET id=? WHERE ctid=?', (new_id, row_get_value(row, 'ctid')))
                fixed += 1
        else:
            rows = conn.execute("SELECT rowid AS _rowid, id FROM pagamentos WHERE id IS NULL OR TRIM(CAST(id AS TEXT))='' OR CAST(id AS TEXT) GLOB '*[^0-9]*'").fetchall()
            for row in rows or []:
                new_id = _next_pagamento_id(conn)
                conn.execute('UPDATE pagamentos SET id=? WHERE rowid=?', (new_id, row_get_value(row, '_rowid')))
                fixed += 1
        conn.commit()
    except Exception as exc:
        try: conn.rollback()
        except Exception: pass
        print('ensure_pagamentos_valid_ids falhou:', exc)
    finally:
        try: conn.close()
        except Exception: pass

    if fixed:
        try:
            reset_postgres_id_sequence('pagamentos')
        except Exception:
            pass
        clear_view_cache()
    return fixed




def save_pagamento(data, files=None, rid=None):
    """Cria/atualiza pagamento sempre com ID real, mês normalizado e anexos preservados."""
    rid = _safe_int_id(rid)

    if rid and not owned_by_current_company('pagamentos', rid):
        raise ValueError('Pagamento não encontrado ou sem permissão para editar.')

    existing = row_to_dict(query_one('SELECT * FROM pagamentos WHERE id=?', (rid,))) if rid else None
    existing = existing or {}

    def current_list(key):
        value = existing.get(key, [])
        value = list(value) if isinstance(value, list) else []
        return normalize_payment_attachment_list(value)

    anexos_orc = current_list('anexos_orcamento')
    anexos_nf = current_list('anexos_nf')
    anexos_boleto = current_list('anexos_boleto')

    if files:
        file_groups = {
            'anexos_orcamento': anexos_orc,
            'anexos_nf': anexos_nf,
            'anexos_boleto': anexos_boleto,
        }
        for field_name, bucket in file_groups.items():
            for file in files.getlist(field_name):
                if file and file.filename:
                    fn = secure_filename(file.filename)
                    if not fn:
                        continue
                    unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{fn}"
                    storage_path = _payment_attachment_relpath(unique_name)
                    if upload_file_to_supabase(file, storage_path, getattr(file, 'mimetype', None)):
                        bucket.append(storage_path)
                    else:
                        dest = tenant_upload_dir(PAYMENT_STORAGE_FOLDER) / unique_name
                        file.save(dest)
                        bucket.append(f'static/uploads/empresas/{company_folder_name()}/{PAYMENT_STORAGE_FOLDER}/{dest.name}')

    fields = ['sistema','equipamento','fornecedor','descricao_servico','status','nf_proposta','valor','acao','pagamento_mes','tipo_lancamento','terceiro_nome','data_vencimento','sc_pedido','aprovado','tipo_documento','numero_documento','fluxo_status','popup_dispensado_contabil','anexos_orcamento','anexos_nf','anexos_boleto','empresa_id']
    payload = {k: str(data.get(k, '') or '').strip() for k in fields}
    payload['sistema'] = ''
    payload['equipamento'] = ''
    payload['status'] = 'Sim' if payment_status_is_paid(payload.get('status')) else 'Não'
    payload['tipo_lancamento'] = payload.get('tipo_lancamento') or 'Gasto'
    # Se tipo for Terceiros mas não tiver nome, limpa; se não for Terceiros, limpa o nome
    if payload.get('tipo_lancamento') != 'Terceiros':
        payload['terceiro_nome'] = ''
    payload['pagamento_mes'] = _payment_month_or_current(payload.get('pagamento_mes'))
    payload['anexos_orcamento'] = json.dumps(anexos_orc, ensure_ascii=False)
    payload['anexos_nf'] = json.dumps(anexos_nf, ensure_ascii=False)
    payload['anexos_boleto'] = json.dumps(anexos_boleto, ensure_ascii=False)
    payload['empresa_id'] = current_company_id()
    vals = [payload.get(k, '') for k in fields]

    if rid:
        execute(f"UPDATE pagamentos SET {','.join(f'{f}=?' for f in fields)} WHERE id=?", vals + [rid])
        saved_id = rid
    else:
        saved_id = execute(f"INSERT INTO pagamentos({','.join(fields)}) VALUES ({','.join('?' * len(fields))})", vals)
        saved_id = _safe_int_id(saved_id)
        if not saved_id:
            # Fallback para bancos antigos que não retornam lastrowid corretamente.
            row = query_one(
                """SELECT id FROM pagamentos
                   WHERE empresa_id IS ? AND fornecedor=? AND descricao_servico=? AND valor=? AND pagamento_mes=?
                   ORDER BY id DESC LIMIT 1""",
                (payload.get('empresa_id'), payload.get('fornecedor'), payload.get('descricao_servico'), payload.get('valor'), payload.get('pagamento_mes'))
            )
            saved_id = _safe_int_id(row_get_value(row, 'id', None))
        if not saved_id:
            ensure_pagamentos_valid_ids()
            row = query_one('SELECT id FROM pagamentos ORDER BY id DESC LIMIT 1')
            saved_id = _safe_int_id(row_get_value(row, 'id', None))

    clear_view_cache()
    return saved_id




def pagamentos_query_rows(mes_inicio='', mes_fim='', todos=False, ids=None):
    """Carrega pagamentos direto da tabela real, sempre com id.

    Não usa list_page nem cache. Isso evita linha sem data-id na tela.
    """
    ensure_pagamentos_valid_ids()
    where_sql, params = company_where('pagamentos')
    clauses = []
    params = list(params or [])

    ids = [int(x) for x in (ids or []) if str(x).isdigit()]
    if ids:
        placeholders = ','.join(['?'] * len(ids))
        clauses.append(f'id IN ({placeholders})')
        params.extend(ids)

    # Monta WHERE respeitando o prefixo já gerado por company_where.
    sql = f"SELECT * FROM pagamentos{where_sql}"
    if clauses:
        sql += (' AND ' if where_sql else ' WHERE ') + ' AND '.join(clauses)
    sql += ' ORDER BY id DESC'

    raw_rows = query_all(sql, tuple(params))
    rows = []

    def _month_key(ref):
        ref = normalize_month_reference(ref)
        m = re.search(r'(\d{1,2})\s*/\s*(\d{2,4})', ref or '')
        if not m:
            return None
        month = max(1, min(12, int(m.group(1))))
        year = int(m.group(2))
        if year < 100:
            year += 2000
        return year * 100 + month

    mes_inicio_norm = normalize_month_reference(mes_inicio)
    mes_fim_norm = normalize_month_reference(mes_fim)
    start_key = _month_key(mes_inicio_norm)
    end_key = _month_key(mes_fim_norm)

    for raw in (raw_rows or []):
        row = row_to_dict(raw) or {}

        # ID real vindo do banco. Se isto vier vazio, o registro não existe como linha editável.
        rid = row.get('id') or row.get('pagamento_id') or row.get('rowid') or row.get('ID')
        try:
            rid = int(rid) if str(rid or '').isdigit() else rid
        except Exception:
            pass
        row['id'] = rid

        row['status'] = 'Sim' if payment_status_is_paid(row.get('status')) else 'Não'
        row['valor_num'] = parse_num(row.get('valor'))
        row['month_ref'] = normalize_month_reference(row.get('pagamento_mes'))

        try:
            row['attachments_all'] = build_payment_attachment_items(row)
        except Exception:
            row['attachments_all'] = []
        row['attachments_count'] = len(row.get('attachments_all') or [])
        row['has_files'] = bool(row.get('attachments_all'))
        row['file_types'] = ','.join(sorted({str(item.get('group') or '') for item in (row.get('attachments_all') or []) if item.get('group')}))

        if not todos and mes_inicio_norm:
            if mes_fim_norm and start_key and end_key:
                key = _month_key(row.get('month_ref') or row.get('pagamento_mes'))
                lo, hi = min(start_key, end_key), max(start_key, end_key)
                if key is None or key < lo or key > hi:
                    continue
            elif not month_reference_matches_selected(row.get('month_ref') or row.get('pagamento_mes'), mes_inicio_norm):
                continue

        rows.append(row)

    return rows




def pagamentos_totais_from_rows(rows):
    total = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []))
    total_pago = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []) if r.get('status') == 'Sim')
    # Por tipo
    total_gasto      = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []) if (r.get('tipo_lancamento') or 'Gasto') == 'Gasto')
    total_investimento = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []) if (r.get('tipo_lancamento') or '') == 'Investimento')
    total_terceiros  = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []) if (r.get('tipo_lancamento') or '') == 'Terceiros')
    total_a_pagar    = sum(parse_num(r.get('valor_num', r.get('valor'))) for r in (rows or []) if r.get('status') != 'Sim')
    return total, total_pago, total - total_pago, total_gasto, total_investimento, total_terceiros, total_a_pagar

