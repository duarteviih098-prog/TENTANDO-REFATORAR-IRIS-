"""Apply Module 10 — OS extraction (marker-based, idempotent).

Lessons from M8: exact route paths, protected bootstrap, stop at section banners.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
OS_DIR = ROOT / 'app' / 'os'
OS_DIR.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_auth(app)',
    'register_custos(app)',
    'def row_to_dict(',
    'def fetch_sistemas_map(',
)

SERVICE_FUNCS = (
    'prepare_os_row_for_template',
    'ensure_os_tipo_os_column',
    'attach_os_display_numbers',
    'os_is_overdue',
    'save_ativo',
    'normalize_os_system_name',
    'proximo_numero_os',
    'renumerar_os_por_mes',
    'save_os',
    '_push_nova_os_async',
)

ROUTE_PATHS = (
    '/os/ativos',
    '/os/ativos/save',
    '/os',
    '/os/lancamentos',
    '/os/lista',
    '/api/os/paradas',
    '/os/hub',
    '/os/kanban',
    '/os/tecnicos',
    '/os/relatorios',
    '/api/os/status-updates',
    '/api/os/<int:rid>/historico',
    '/api/os/<int:rid>',
    '/os/save',
    '/os/imagem/<int:rid>/<int:idx>',
    '/os/orcamento/<int:rid>/<int:idx>',
    '/api/os/attachment/delete',
    '/os/pdf/<int:rid>',
    '/os/download/<int:rid>',
    '/os/<action>/<int:rid>',
)

ROUTE_HELPERS = ('_redirect_pos_os',)

LEGACY_HELPERS = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)


def br_now():
    return _legacy('br_now')()


def br_money(value):
    return _legacy('br_money')(value)


def parse_br_date(raw):
    return _legacy('parse_br_date')(raw)


def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)


def row_to_dict(row):
    return _legacy('row_to_dict')(row)


def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)


def row_matches_month(*values, month_ref=''):
    return _legacy('row_matches_month')(*values, month_ref=month_ref)


def only_time_str(raw):
    return _legacy('only_time_str')(raw)


def time_diff_minutes(start_raw, end_raw=''):
    return _legacy('time_diff_minutes')(start_raw, end_raw)


def elapsed_label(start_raw, end_raw='', accumulated_minutes=0, running=False):
    return _legacy('elapsed_label')(start_raw, end_raw, accumulated_minutes, running)


def now_str():
    return _legacy('now_str')()


def clear_view_cache(prefix=None):
    return _legacy('clear_view_cache')(prefix)


def backup_company_data(empresa_id=None):
    return _legacy('backup_company_data')(empresa_id=empresa_id)


def list_page(table, order='id DESC', limit=120):
    return _legacy('list_page')(table, order, limit)


def fetch_sistemas_map():
    return _legacy('fetch_sistemas_map')()


def is_mobile_request():
    return _legacy('is_mobile_request')()


def user_has(perm):
    return _legacy('user_has')(perm)


def owned_by_current_company(table, rid):
    return _legacy('owned_by_current_company')(table, rid)


def reset_sqlite_sequence_if_empty(table_name):
    return _legacy('reset_sqlite_sequence_if_empty')(table_name)


def normalize_month_reference(raw_value):
    return _legacy('normalize_month_reference')(raw_value)


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
        if line.startswith('def ') or line.startswith('@app.route(') or line.startswith('@app.post(') or line.startswith('@app.get('):
            end = i
            break
        if re.match(r'^[A-Z_][A-Z0-9_]*\s*=', line):
            end = i
            break
        if line.startswith('from app.') or line.startswith('app = create_app'):
            end = i
            break
        if line.startswith('# =') and i > start + 2:
            end = i
            break
        if line.startswith('# ──') and i > start + 2:
            end = i
            break
    return end


def grab_def(lines, name):
    start = find_def_line(lines, name)
    end = find_block_end(lines, start)
    return ''.join(lines[start:end]), start, end


def find_route_block(lines, path):
    escaped = re.escape(path)
    route_pat = re.compile(rf"^@app\.route\(['\"]{escaped}['\"]")
    start = None
    for i, line in enumerate(lines):
        if route_pat.match(line):
            start = i
            break
    if start is None:
        raise ValueError(f'route {path!r} not found')
    def_line = start
    for i in range(start, min(start + 8, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    end = find_block_end(lines, def_line)
    return ''.join(lines[start:end]), start, end


def strip_route_decorators(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    text = re.sub(r'^@app\.(?:route|post|get)\([^\n]+\)\n', '', text, flags=re.M)
    return text


def find_pdf_section(lines):
    start = next(i for i, l in enumerate(lines) if '# PDF PERFORMANCE' in l)
    end = next(i for i, l in enumerate(lines[start + 1:], start + 1) if '# ── IRIS JOBS' in l)
    return start, end


def assert_safe_delete(text, label):
    for snippet in DELETE_PROTECTED:
        if snippet in text:
            raise RuntimeError(f'{label} contains protected snippet {snippet!r}')


def build_services(lines):
    parts = [LEGACY_HELPERS.strip(), '\n\nimport json\nimport os\nimport re\nimport threading\n\nfrom app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE\n']
    parts.append('from app.storage.attachments import normalize_os_attachment_list, save_os_files\n')
    parts.append('from app.auth import get_current_user\n\n')
    for name in SERVICE_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (OS_DIR / 'services.py').write_text(
        '"""Regras de negócio do módulo O.S."""\n' + ''.join(parts),
        encoding='utf-8',
    )


def build_pdf(lines):
    start, end = find_pdf_section(lines)
    pdf_body = ''.join(lines[start:end])
    assert_safe_delete(pdf_body, 'pdf section')
    pdf_routes = ''
    for path in ('/os/pdf/dia', '/os/pdf/mes/sync', '/os/pdf/job/<int:job_id>/status', '/os/pdf/mes/job', '/os/pdf/mes'):
        try:
            block, _, _ = find_route_block(lines, path)
            pdf_routes += strip_route_decorators(block) + '\n\n'
        except ValueError:
            pass
    header = '''"""PDF de O.S. — geração, cache e jobs em background."""
import io
import json
import os
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.auth.decorators import require_permission
from app.os.services import attach_os_display_numbers
from app.storage import (
    _upload_pdf_bytes_to_supabase,
    company_folder_name,
    company_identity_dir,
    company_identity_file,
    load_company_identity_config,
    sync_os_attachments,
)
from app.storage.attachments import resolve_os_upload_path
from app.storage.responses import storage_or_local_response

'''
    footer = '''

def register_pdf_routes(app):
    rules = [
        ('/os/pdf/dia', 'os_pdf_dia', os_pdf_dia, ['GET']),
        ('/os/pdf/mes', 'os_pdf_mes', os_pdf_mes, ['GET']),
        ('/os/pdf/mes/job', 'os_pdf_mes_job', os_pdf_mes_job, ['POST']),
        ('/os/pdf/job/<int:job_id>/status', 'os_pdf_job_status', os_pdf_job_status, ['GET']),
        ('/os/pdf/mes/sync', 'os_pdf_mes_sync', os_pdf_mes_sync, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    content = header + LEGACY_HELPERS + '\n\nfrom app import legacy as _legacy_module\n\napp = _legacy_module.app\n_BACKGROUND_COMPANY_CONTEXT = _legacy_module._BACKGROUND_COMPANY_CONTEXT\n\n' + pdf_body + '\n' + pdf_routes + footer
    (OS_DIR / 'pdf.py').write_text(content, encoding='utf-8')


def build_routes(lines):
    route_body = ''
    for path in ROUTE_PATHS:
        if path.startswith('/os/pdf'):
            continue
        block, _, _ = find_route_block(lines, path)
        route_body += strip_route_decorators(block) + '\n\n'
    for name in ROUTE_HELPERS:
        body, _, _ = grab_def(lines, name)
        route_body += body + '\n\n'

    perm_map = {
        'os_ativos': 'view_os_ativos',
        'os_ativos_save': 'edit_os',
        'os_redirect': 'view_os',
        'os_lancamentos': 'view_os',
        'os_page': 'view_os',
        'os_paradas': 'view_os',
        'os_hub': 'view_os',
        'os_kanban': 'view_os',
        'os_tecnicos': 'view_os',
        'os_relatorios': 'view_os',
        'api_os_detail': 'view_os',
        'api_os_historico': 'view_os',
        'os_save': 'view_os',
        'os_orcamento_download': 'view_budget_files',
        'api_os_attachment_delete': 'edit_os',
        'os_pdf_individual': 'generate_pdf',
        'os_download_pacote': 'download_os',
        'os_action': 'edit_os',
    }
    for fn, perm in perm_map.items():
        route_body = route_body.replace(f'def {fn}(', f"@require_permission('{perm}')\ndef {fn}(", 1)

    header = '''"""Rotas /os/* e APIs de O.S. (exceto Campo/PWA — M11)."""
import hmac
import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for

from app.auth.decorators import require_permission
from app.os.pdf import _build_os_pdf
from app.os.services import (
    attach_os_display_numbers,
    os_is_overdue,
    prepare_os_row_for_template,
    save_ativo,
    save_os,
)
from app.storage import missing_attachment_response, normalize_storage_path, storage_or_local_response, sync_os_attachments
from app.storage.attachments import resolve_os_upload_path

'''
    register = '''
def register_routes(app):
    rules = [
        ('/os/ativos', 'os_ativos', os_ativos, ['GET']),
        ('/os/ativos/save', 'os_ativos_save', os_ativos_save, ['POST']),
        ('/os', 'os_redirect', os_redirect, ['GET']),
        ('/os/lancamentos', 'os_lancamentos', os_lancamentos, ['GET']),
        ('/os/lista', 'os_page', os_page, ['GET']),
        ('/api/os/paradas', 'os_paradas', os_paradas, ['GET']),
        ('/os/hub', 'os_hub', os_hub, ['GET']),
        ('/os/kanban', 'os_kanban', os_kanban, ['GET']),
        ('/os/tecnicos', 'os_tecnicos', os_tecnicos, ['GET']),
        ('/os/relatorios', 'os_relatorios', os_relatorios, ['GET']),
        ('/api/os/status-updates', 'api_os_status_updates', api_os_status_updates, ['GET']),
        ('/api/os/<int:rid>', 'api_os_detail', api_os_detail, ['GET']),
        ('/api/os/<int:rid>/historico', 'api_os_historico', api_os_historico, ['GET']),
        ('/os/save', 'os_save', os_save, ['POST']),
        ('/os/imagem/<int:rid>/<int:idx>', 'os_imagem_visualizar', os_imagem_visualizar, ['GET']),
        ('/os/orcamento/<int:rid>/<int:idx>', 'os_orcamento_download', os_orcamento_download, ['GET']),
        ('/api/os/attachment/delete', 'api_os_attachment_delete', api_os_attachment_delete, ['POST']),
        ('/os/pdf/<int:rid>', 'os_pdf_individual', os_pdf_individual, ['GET']),
        ('/os/download/<int:rid>', 'os_download_pacote', os_download_pacote, ['GET']),
        ('/os/<action>/<int:rid>', 'os_action', os_action, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    (OS_DIR / 'routes.py').write_text(header + LEGACY_HELPERS + route_body + register, encoding='utf-8')


def build_init():
    (OS_DIR / '__init__.py').write_text(
        '''"""Módulo O.S."""
from app.os.pdf import register_pdf_routes
from app.os.routes import register_routes
from app.os.services import (
    attach_os_display_numbers,
    ensure_os_tipo_os_column,
    os_is_overdue,
    prepare_os_row_for_template,
    proximo_numero_os,
    renumerar_os_por_mes,
    save_ativo,
    save_os,
)


def register_os(app):
    register_routes(app)
    register_pdf_routes(app)


__all__ = [
    'register_os',
    'prepare_os_row_for_template',
    'ensure_os_tipo_os_column',
    'attach_os_display_numbers',
    'os_is_overdue',
    'save_ativo',
    'save_os',
    'proximo_numero_os',
    'renumerar_os_por_mes',
]
''',
        encoding='utf-8',
    )


def remove_from_legacy(lines):
    spans = []
    for name in SERVICE_FUNCS:
        try:
            _, start, end = grab_def(lines, name)
            spans.append((start, end))
        except ValueError:
            pass
    for name in ROUTE_HELPERS:
        try:
            _, start, end = grab_def(lines, name)
            spans.append((start, end))
        except ValueError:
            pass
    for path in ROUTE_PATHS:
        try:
            _, start, end = find_route_block(lines, path)
            spans.append((start, end))
        except ValueError:
            pass
    try:
        start, end = find_pdf_section(lines)
        spans.append((start, end))
    except StopIteration:
        pass

    for start, end in sorted(spans, reverse=True):
        block = ''.join(lines[start:end])
        assert_safe_delete(block, f'legacy delete {start + 1}')
        del lines[start:end]


def wire_legacy(text):
    if 'register_os(app)' in text:
        return text
    block = '''
from app.os import register_os
from app.os.services import (
    attach_os_display_numbers,
    ensure_os_tipo_os_column,
    os_is_overdue,
    prepare_os_row_for_template,
    proximo_numero_os,
    renumerar_os_por_mes,
    save_ativo,
    save_os,
)
'''
    if 'from app.os import register_os' not in text:
        text = text.replace(
            'from app.custos.services import ensure_custos_valid_ids, import_custos_excel, save_custo\n',
            'from app.custos.services import ensure_custos_valid_ids, import_custos_excel, save_custo\n' + block,
            1,
        )
    text = text.replace(
        'register_custos(app)\n',
        'register_custos(app)\nregister_os(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_os(app)' in raw:
        print('Module 10 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_services(lines)
    build_pdf(lines)
    build_routes(lines)
    build_init()
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 10 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
