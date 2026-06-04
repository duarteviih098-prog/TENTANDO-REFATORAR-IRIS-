"""Apply Module 8 pagamentos extraction (marker-based)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
PAG = ROOT / 'app' / 'pagamentos'
PAG.mkdir(exist_ok=True)

LEGACY = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)

def br_now():
    return _legacy('br_now')()

def br_money(value):
    return _legacy('br_money')(value)

def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)

def parse_br_date(raw):
    return _legacy('parse_br_date')(raw)

def row_to_dict(row):
    return _legacy('row_to_dict')(row)

def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)

def normalize_month_reference(raw_value):
    return _legacy('normalize_month_reference')(raw_value)

def month_reference_matches_selected(raw_value, selected_reference):
    return _legacy('month_reference_matches_selected')(raw_value, selected_reference)

def payment_status_is_paid(value):
    return _legacy('payment_status_is_paid')(value)

def clear_view_cache(prefix=None):
    return _legacy('clear_view_cache')(prefix)

def backup_company_data(empresa_id=None):
    return _legacy('backup_company_data')(empresa_id=empresa_id)

def now_str():
    return _legacy('now_str')()

def _safe_int_id(value):
    return _legacy('_safe_int_id')(value)

def _payment_month_or_current(value=''):
    from app.pagamentos.services import payment_month_or_current
    return payment_month_or_current(value)

def table_pdf(title, headers, data):
    return _legacy('table_pdf')(title, headers, data)

def excel_file(sheet_name, headers, data):
    return _legacy('excel_file')(sheet_name, headers, data)

def _draw_pdf_header(canvas, doc, title):
    return _legacy('_draw_pdf_header')(canvas, doc, title)

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

'''


def find_def_line(lines, name):
    pat = re.compile(rf'^def {re.escape(name)}\(')
    for i, line in enumerate(lines):
        if pat.match(line):
            return i
    raise ValueError(f'def {name} not found')


def find_block_end(lines, start):
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith('def ') or line.startswith('@app.route(') or line.startswith('@app.post('):
            end = i
            break
        if line.startswith('# =') and i > start + 2:
            end = i
            break
    return end


def find_route_block(lines, path_prefix):
    route_pat = re.compile(rf"^@app\.route\('{re.escape(path_prefix)}")
    start = None
    for i, line in enumerate(lines):
        if route_pat.match(line):
            start = i
            break
    if start is None:
        raise ValueError(f'route {path_prefix} not found')
    def_line = start
    for i in range(start, min(start + 6, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    return start, find_block_end(lines, def_line)


def strip_routes(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    text = re.sub(r'^@app\.route\([^\n]+\)\n', '', text, flags=re.M)
    return text


def grab_def(lines, name):
    start = find_def_line(lines, name)
    end = find_block_end(lines, start)
    return ''.join(lines[start:end]), start, end


SERVICE_NAMES = [
    'prepare_payment_row_for_template',
    'build_payment_attachment_items',
    'import_pagamentos_excel',
    '_payment_month_or_current',
    '_next_pagamento_id',
    'ensure_pagamentos_valid_ids',
    'save_pagamento',
    'pagamentos_query_rows',
    'pagamentos_totais_from_rows',
]

ROUTE_PATHS = [
    '/pagamentos/excel',
    '/pagamentos/pdf',
    '/pagamentos/anexo/<int:rid>/<grupo>/<int:idx>',
    '/pagamentos/relatorios/pdf',
    '/pagamentos/relatorios',
    '/api/pagamentos/aprovacoes/lote',
    '/pagamentos/aprovacoes/aprovar/<int:rid>',
    '/pagamentos/aprovacoes',
    '/pagamentos/fornecedores',
    '/pagamentos/vencimentos',
    '/pagamentos/hub',
    '/api/pagamentos/receber/<int:rid>',
    '/pagamentos/receber/delete',
    '/pagamentos/receber/save',
    '/pagamentos/receber',
    '/api/pagamentos/aprovacoes-recentes',
    '/api/pagamentos/<int:rid>/parcelar',
    '/pagamentos/save',
    '/pagamentos/lancamentos',
    '/pagamentos',
    '/pagamentos/import',
]

PERM_MAP = {
    'pagamentos_import': 'edit_pagamentos',
    'pagamentos_redirect': 'view_pagamentos',
    'pagamentos': 'view_pagamentos',
    'pagamentos_save': 'edit_pagamentos',
    'pagamentos_parcelar': 'edit_pagamentos',
    'pagamentos_aprovacoes_recentes': 'view_pagamentos',
    'pagamentos_receber': 'view_pagamentos',
    'pagamentos_receber_save': 'edit_pagamentos',
    'pagamentos_receber_delete': 'delete_pagamentos',
    'pagamentos_receber_api': 'view_pagamentos',
    'pagamentos_hub': 'view_pagamentos',
    'pagamentos_vencimentos': 'view_pagamentos',
    'pagamentos_fornecedores': 'view_pagamentos',
    'pagamentos_aprovacoes': 'view_pagamentos',
    'pagamentos_aprovar': 'edit_pagamentos',
    'pagamentos_aprovar_lote': 'edit_pagamentos',
    'pagamentos_relatorios': 'view_pagamentos',
    'pagamentos_relatorios_pdf': 'generate_pdf',
    'pagamentos_attachment': 'view_pagamentos',
    'pagamentos_pdf': 'generate_pdf',
    'pagamentos_excel': 'generate_excel',
}


def build_services(lines):
    parts = [
        '"""Regras de negócio do módulo pagamentos."""\n',
        'import json\nimport re\nfrom datetime import datetime\nfrom pathlib import Path\n\n',
        'from werkzeug.utils import secure_filename\n\n',
        'from app.auth import company_where, current_company_id, owned_by_current_company\n',
        'from app.db import (\n',
        '    USE_POSTGRES,\n',
        '    execute,\n',
        '    get_conn,\n',
        '    query_all,\n',
        '    query_one,\n',
        '    reset_postgres_id_sequence,\n',
        '    table_columns,\n',
        ')\n',
        'from app.storage import (\n',
        '    ATTACHMENT_GROUPS,\n',
        '    PAYMENT_STORAGE_FOLDER,\n',
        '    _payment_attachment_relpath,\n',
        '    company_folder_name,\n',
        '    normalize_payment_attachment_list,\n',
        '    tenant_upload_dir,\n',
        '    upload_file_to_supabase,\n',
        ')\n',
        LEGACY.replace('_payment_month_or_current', 'payment_month_or_current').replace(
            'from app.pagamentos.services import payment_month_or_current\n    return payment_month_or_current(value)',
            "return _legacy('_payment_month_or_current')(value)",
        ),
    ]
    # Fix circular ref in LEGACY for services - services define payment_month_or_current from _payment_month_or_current rename
    svc_legacy = LEGACY.replace(
        "def _payment_month_or_current(value=''):\n    from app.pagamentos.services import payment_month_or_current\n    return payment_month_or_current(value)",
        '',
    )
    parts[0] = '"""Regras de negócio do módulo pagamentos."""\n'
    body = [
        '"""Regras de negócio do módulo pagamentos."""\n',
        'import json\nimport re\nfrom datetime import datetime\nfrom pathlib import Path\n\n',
        'from werkzeug.utils import secure_filename\n\n',
        'from app.auth import company_where, current_company_id, owned_by_current_company\n',
        'from app.db import USE_POSTGRES, execute, get_conn, query_all, query_one, reset_postgres_id_sequence, table_columns\n',
        'from app.storage import (\n',
        '    ATTACHMENT_GROUPS,\n',
        '    PAYMENT_STORAGE_FOLDER,\n',
        '    _payment_attachment_relpath,\n',
        '    company_folder_name,\n',
        '    normalize_payment_attachment_list,\n',
        '    tenant_upload_dir,\n',
        '    upload_file_to_supabase,\n',
        ')\n',
        svc_legacy,
    ]
    rename_map = {'_payment_month_or_current': 'payment_month_or_current'}
    for name in SERVICE_NAMES:
        chunk, _, _ = grab_def(lines, name)
        if name in rename_map:
            chunk = chunk.replace(f'def {name}(', f'def {rename_map[name]}(', 1)
        body.append('\n\n' + chunk)
    (PAG / 'services.py').write_text(''.join(body), encoding='utf-8')


def build_routes(lines):
    routes_body = ''
    for path in ROUTE_PATHS:
        try:
            start, end = find_route_block(lines, path)
            routes_body = strip_routes(''.join(lines[start:end])) + '\n\n' + routes_body
        except ValueError:
            pass
    for fn, perm in PERM_MAP.items():
        routes_body = routes_body.replace(f'def {fn}(', f"@require_permission('{perm}')\ndef {fn}(", 1)
    header = '''"""Rotas /pagamentos/* e APIs relacionadas."""
import io
import re
from collections import defaultdict
import calendar

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.auth.decorators import require_permission
from app.pagamentos.services import (
    build_payment_attachment_items,
    ensure_pagamentos_valid_ids,
    import_pagamentos_excel,
    pagamentos_query_rows,
    pagamentos_totais_from_rows,
    payment_month_or_current,
    save_pagamento,
)
from app.storage import ATTACHMENT_GROUPS, missing_attachment_response, storage_or_local_response, sync_payment_attachments

'''
    register = '''
def register_routes(app):
    rules = [
        ('/pagamentos/import', 'pagamentos_import', pagamentos_import, ['POST']),
        ('/pagamentos', 'pagamentos_redirect', pagamentos_redirect, ['GET']),
        ('/pagamentos/lancamentos', 'pagamentos', pagamentos, ['GET']),
        ('/pagamentos/save', 'pagamentos_save', pagamentos_save, ['POST']),
        ('/api/pagamentos/<int:rid>/parcelar', 'pagamentos_parcelar', pagamentos_parcelar, ['POST']),
        ('/api/pagamentos/aprovacoes-recentes', 'pagamentos_aprovacoes_recentes', pagamentos_aprovacoes_recentes, ['GET']),
        ('/pagamentos/receber', 'pagamentos_receber', pagamentos_receber, ['GET']),
        ('/pagamentos/receber/save', 'pagamentos_receber_save', pagamentos_receber_save, ['POST']),
        ('/pagamentos/receber/delete', 'pagamentos_receber_delete', pagamentos_receber_delete, ['POST']),
        ('/api/pagamentos/receber/<int:rid>', 'pagamentos_receber_api', pagamentos_receber_api, ['GET']),
        ('/pagamentos/hub', 'pagamentos_hub', pagamentos_hub, ['GET']),
        ('/pagamentos/vencimentos', 'pagamentos_vencimentos', pagamentos_vencimentos, ['GET']),
        ('/pagamentos/fornecedores', 'pagamentos_fornecedores', pagamentos_fornecedores, ['GET']),
        ('/pagamentos/aprovacoes', 'pagamentos_aprovacoes', pagamentos_aprovacoes, ['GET']),
        ('/pagamentos/aprovacoes/aprovar/<int:rid>', 'pagamentos_aprovar', pagamentos_aprovar, ['POST']),
        ('/api/pagamentos/aprovacoes/lote', 'pagamentos_aprovar_lote', pagamentos_aprovar_lote, ['POST']),
        ('/pagamentos/relatorios', 'pagamentos_relatorios', pagamentos_relatorios, ['GET']),
        ('/pagamentos/relatorios/pdf', 'pagamentos_relatorios_pdf', pagamentos_relatorios_pdf, ['GET']),
        ('/pagamentos/anexo/<int:rid>/<grupo>/<int:idx>', 'pagamentos_attachment', pagamentos_attachment, ['GET']),
        ('/pagamentos/pdf', 'pagamentos_pdf', pagamentos_pdf, ['GET']),
        ('/pagamentos/excel', 'pagamentos_excel', pagamentos_excel, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    (PAG / 'routes.py').write_text(header + LEGACY + routes_body + register, encoding='utf-8')


def remove_from_legacy(lines):
    spans = []
    for name in SERVICE_NAMES:
        try:
            _, start, end = grab_def(lines, name)
            spans.append((start, end))
        except ValueError:
            pass
    for path in ROUTE_PATHS:
        try:
            start, end = find_route_block(lines, path)
            spans.append((start, end))
        except ValueError:
            pass
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]


def wire_legacy(text):
    block = '''
from app.pagamentos import register_pagamentos
from app.pagamentos.services import (
    build_payment_attachment_items,
    ensure_pagamentos_valid_ids,
    import_pagamentos_excel,
    pagamentos_query_rows,
    prepare_payment_row_for_template,
    save_pagamento,
)
'''
    if 'register_pagamentos(app)' in text:
        return text
    text = text.replace(
        'register_combustivel(app)\n',
        'register_combustivel(app)\nregister_pagamentos(app)\n',
        1,
    )
    if 'from app.pagamentos import register_pagamentos' not in text:
        text = text.replace(
            'from app.combustivel.services import ensure_combustivel_valid_ids, import_combustivel_excel, save_combustivel\n',
            'from app.combustivel.services import ensure_combustivel_valid_ids, import_combustivel_excel, save_combustivel\n' + block,
            1,
        )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_pagamentos(app)' in raw:
        print('Module 8 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_services(lines)
    build_routes(lines)
    (PAG / '__init__.py').write_text(
        '''"""Módulo Pagamentos."""
from app.pagamentos.routes import register_routes
from app.pagamentos.services import (
    build_payment_attachment_items,
    ensure_pagamentos_valid_ids,
    import_pagamentos_excel,
    pagamentos_query_rows,
    pagamentos_totais_from_rows,
    prepare_payment_row_for_template,
    save_pagamento,
)


def register_pagamentos(app):
    register_routes(app)


__all__ = [
    'register_pagamentos',
    'prepare_payment_row_for_template',
    'build_payment_attachment_items',
    'save_pagamento',
    'import_pagamentos_excel',
    'ensure_pagamentos_valid_ids',
    'pagamentos_query_rows',
    'pagamentos_totais_from_rows',
]
''',
        encoding='utf-8',
    )
    remove_from_legacy(lines)
    legacy_new = wire_legacy(''.join(lines))
    # routes use payment_month_or_current; legacy helpers used _payment_month_or_current
    legacy_new = legacy_new.replace('_payment_month_or_current', 'payment_month_or_current')
    legacy_path.write_text(legacy_new, encoding='utf-8')
    print('legacy lines:', len(legacy_new.splitlines()))


if __name__ == '__main__':
    main()
