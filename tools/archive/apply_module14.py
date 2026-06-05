"""Apply Module 14 — Exports PDF/Excel (marker-based, idempotent)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
EXP_DIR = ROOT / 'app' / 'exports'
EXP_DIR.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_outlook(app)',
    'def row_to_dict(',
    'def iris_chat(',
    'def _iris_answer(',
    'maybe_start_monitor_worker()',
)

EXCEL_FUNCS = ('normalize_import_header', 'excel_rows_from_upload')

IRIS_DATA_FUNCS = (
    '_iris_normalize',
    '_iris_parse_br_float',
    '_iris_rows',
    '_iris_month_number_from_text',
    '_iris_match_month',
    '_iris_payment_is_approved',
    '_iris_official_finance',
    '_iris_payment_status',
    '_iris_collect_context',
    '_iris_month_label',
)

IRIS_AI_FUNCS = (
    '_iris_build_rich_context',
    '_iris_call_claude',
    '_iris_call_openai',
    '_iris_call_ai',
    '_iris_generate_ai_report',
)

IRIS_REPORT_FUNCS = (
    '_iris_make_ai_pdf',
    '_iris_simple_bar_drawing',
    '_iris_make_monthly_pdf',
    '_iris_make_payments_excel',
)

JOB_FUNCS = (
    '_create_iris_job',
    '_gerar_iris_job_worker',
    '_start_iris_job_thread',
    '_render_iris_job_wait_page',
)

ALL_SERVICE_FUNCS = EXCEL_FUNCS + IRIS_DATA_FUNCS + IRIS_AI_FUNCS + IRIS_REPORT_FUNCS + JOB_FUNCS + ('ensure_company_pdf_columns',)

ROUTE_PATHS = (
    '/api/boleto/parse-vencimento',
    '/iris/relatorio/<int:job_id>',
)

LEGACY_HELPERS = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)


def br_now():
    return _legacy('br_now')()


def br_money(value):
    return _legacy('br_money')(value)


def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)


def row_to_dict(row):
    return _legacy('row_to_dict')(row)


def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)


def now_str():
    return _legacy('now_str')()


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin():
    from app.auth import current_user_is_super_admin as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_column(table, column, col_type):
    from app.db import ensure_column as fn
    return fn(table, column, col_type)
'''

EXCEL_HEADER = '''"""Utilitários de importação Excel compartilhados entre módulos."""
from datetime import datetime

from openpyxl import load_workbook

'''

COMPANY_PDF_HEADER = '''"""Colunas persistentes de identidade PDF da empresa."""
from app.db import execute, table_columns
from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE

'''

IRIS_DATA_HEADER = '''"""Coleta e agregação de dados para relatórios exportados."""
import re

from app.auth.constants import TENANT_TABLES

'''

IRIS_AI_HEADER = '''"""Geração de texto IA para relatórios PDF."""
import json
import os

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None

'''

IRIS_REPORT_HEADER = '''"""Geração de PDF/Excel — relatórios Iris e mensais."""
import io
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import PROJECT_ROOT
from app.exports.iris_ai import (
    _iris_build_rich_context,
    _iris_call_ai,
    _iris_generate_ai_report,
)
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_match_month,
    _iris_month_label,
    _iris_official_finance,
    _iris_parse_br_float,
    _iris_payment_is_approved,
    _iris_payment_status,
    _iris_rows,
)
from app.storage import (
    SUPABASE_STORAGE_KEY,
    _upload_pdf_bytes_to_supabase,
    company_folder_name,
    load_company_identity_config,
    slugify_company_name,
)

BASE_DIR = PROJECT_ROOT

'''

JOBS_HEADER = '''"""Jobs em background para relatórios PDF Iris."""
import re
import threading

from app.exports.iris_reports import _iris_make_ai_pdf

'''

ROUTES_HEADER = '''"""Rotas de exportação — relatório Iris e parse de boleto."""
import io
import re

from flask import flash, jsonify, redirect, request, url_for

from app.auth.decorators import require_permission
from app.exports.jobs import _render_iris_job_wait_page

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
        if line.startswith('if __name__'):
            end = i
            break
        if line.startswith('def ') or line.startswith('@app.route(') or line.startswith('@app.post(') or line.startswith('@app.get('):
            end = i
            break
        if re.match(r'^[A-Z_][A-Z0-9_]*\s*=', line) and not line.startswith('COMPANY_PDF'):
            end = i
            break
        if line.startswith('from app.') or line.startswith('app = create_app'):
            end = i
            break
        if line.startswith('## ') and i > start + 2:
            end = i
            break
        if line.startswith('# ──') and i > start + 2:
            end = i
            break
    return end


def grab_def(lines, name):
    start = find_def_line(lines, name)
    end = find_block_end(lines, start)
    body = ''.join(lines[start:end])
    if name == '_iris_make_ai_pdf':
        marker = '    return out, arquivo_url\n'
        pos = body.find(marker)
        if pos >= 0:
            body = body[: pos + len(marker)]
    return body, start, end


def grab_company_pdf_constants(lines):
    start = next(i for i, l in enumerate(lines) if l.startswith('COMPANY_PDF_COLUMNS'))
    end = start + 1
    while end < len(lines) and not lines[end].startswith('def ensure_company_pdf_columns'):
        end += 1
    return ''.join(lines[start:end]), start, end


def find_route_block(lines, path):
    escaped = re.escape(path)
    route_pat = re.compile(rf"^@app\.(?:route|post|get)\(['\"]{escaped}['\"]")
    start = None
    for i, line in enumerate(lines):
        if route_pat.match(line):
            start = i
            break
    if start is None:
        raise ValueError(f'route {path!r} not found')
    def_line = start
    for i in range(start, min(start + 12, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    end = find_block_end(lines, def_line)
    return ''.join(lines[start:end]), start, end


def strip_route_decorators(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    return re.sub(r'^@app\.(?:route|post|get)\([^\n]+\)\n', '', text, flags=re.M)


def assert_safe_delete(text, label):
    for snippet in DELETE_PROTECTED:
        if snippet in text and snippet != 'maybe_start_monitor_worker()':
            raise RuntimeError(f'{label} contains protected snippet {snippet!r}')


def build_excel(lines):
    parts = [EXCEL_HEADER, LEGACY_HELPERS.strip(), '\n']
    for name in EXCEL_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (EXP_DIR / 'excel.py').write_text(''.join(parts), encoding='utf-8')


def build_company_pdf(lines):
    const_block, _, _ = grab_company_pdf_constants(lines)
    body, _, _ = grab_def(lines, 'ensure_company_pdf_columns')
    (EXP_DIR / 'company_pdf.py').write_text(
        COMPANY_PDF_HEADER + const_block + '\n' + body + '\n',
        encoding='utf-8',
    )


def build_iris_data(lines):
    parts = [IRIS_DATA_HEADER, LEGACY_HELPERS.strip(), '\n']
    for name in IRIS_DATA_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (EXP_DIR / 'iris_data.py').write_text(''.join(parts), encoding='utf-8')


def build_iris_ai(lines):
    parts = [IRIS_AI_HEADER, LEGACY_HELPERS.strip(), '\n']
    for name in IRIS_AI_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (EXP_DIR / 'iris_ai.py').write_text(''.join(parts), encoding='utf-8')


def build_iris_reports(lines):
    parts = [IRIS_REPORT_HEADER, LEGACY_HELPERS.strip(), '\n']
    for name in IRIS_REPORT_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (EXP_DIR / 'iris_reports.py').write_text(''.join(parts), encoding='utf-8')


def build_jobs(lines):
    jobs_helpers = LEGACY_HELPERS + '''

def _flask_app():
    from app import legacy as _legacy_module
    return _legacy_module.app


def _bg_context():
    from app import legacy as _legacy_module
    return _legacy_module._BACKGROUND_COMPANY_CONTEXT


app = None
_BACKGROUND_COMPANY_CONTEXT = None


def _lazy_app_refs():
    global app, _BACKGROUND_COMPANY_CONTEXT
    if app is None:
        app = _flask_app()
        _BACKGROUND_COMPANY_CONTEXT = _bg_context()
'''
    parts = [JOBS_HEADER, jobs_helpers.strip(), '\n']
    for name in JOB_FUNCS:
        body, _, _ = grab_def(lines, name)
        if name == '_gerar_iris_job_worker':
            body = body.replace('from app.os.pdf import _pdf_job_now', 'from app.os.pdf import _pdf_job_now')
        parts.append('\n\n' + body)
    footer = '''

def _ensure_app_refs():
    _lazy_app_refs()
'''
    (EXP_DIR / 'jobs.py').write_text(''.join(parts) + footer, encoding='utf-8')


def build_routes(lines):
    route_body = ''
    for path in ROUTE_PATHS:
        block, _, _ = find_route_block(lines, path)
        route_body += strip_route_decorators(block) + '\n\n'
    route_body = route_body.replace(
        'def iris_relatorio_wait(',
        "@require_permission('generate_pdf')\ndef iris_relatorio_wait(",
        1,
    )
    route_body = route_body.replace(
        'def api_boleto_parse_vencimento(',
        "@require_permission('edit_pagamentos')\ndef api_boleto_parse_vencimento(",
        1,
    )
    register = '''
def register_routes(app):
    rules = [
        ('/api/boleto/parse-vencimento', 'api_boleto_parse_vencimento', api_boleto_parse_vencimento, ['POST']),
        ('/iris/relatorio/<int:job_id>', 'iris_relatorio_wait', iris_relatorio_wait, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    (EXP_DIR / 'routes.py').write_text(
        ROUTES_HEADER + LEGACY_HELPERS + route_body + register,
        encoding='utf-8',
    )


def build_init():
    (EXP_DIR / '__init__.py').write_text(
        '''"""Módulo Exports — PDF/Excel transversais."""
from app.exports.company_pdf import COMPANY_PDF_COLUMNS, ensure_company_pdf_columns
from app.exports.excel import excel_rows_from_upload, normalize_import_header
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_month_label,
    _iris_normalize,
    _iris_official_finance,
    _iris_parse_br_float,
    _iris_payment_status,
)
from app.exports.iris_reports import (
    _iris_make_ai_pdf,
    _iris_make_monthly_pdf,
    _iris_make_payments_excel,
)
from app.exports.jobs import _create_iris_job, _render_iris_job_wait_page, _start_iris_job_thread
from app.exports.routes import register_routes


def register_exports(app):
    register_routes(app)


__all__ = [
    'register_exports',
    'excel_rows_from_upload',
    'normalize_import_header',
    'ensure_company_pdf_columns',
    'COMPANY_PDF_COLUMNS',
    '_iris_make_ai_pdf',
    '_iris_make_monthly_pdf',
    '_iris_make_payments_excel',
    '_create_iris_job',
    '_start_iris_job_thread',
    '_iris_collect_context',
    '_iris_official_finance',
    '_iris_month_label',
    '_iris_normalize',
    '_iris_parse_br_float',
    '_iris_payment_status',
]
''',
        encoding='utf-8',
    )


def remove_from_legacy(lines):
    spans = []
    try:
        _, start, end = grab_company_pdf_constants(lines)
        spans.append((start, end))
    except StopIteration:
        pass
    for name in ALL_SERVICE_FUNCS:
        try:
            _, start, end = grab_def(lines, name)
            spans.append((start, end))
        except ValueError:
            pass
    for path in ROUTE_PATHS:
        _, start, end = find_route_block(lines, path)
        spans.append((start, end))
    for start, end in sorted(spans, reverse=True):
        block = ''.join(lines[start:end])
        assert_safe_delete(block, f'legacy delete {start + 1}')
        del lines[start:end]


def wire_legacy(text):
    if 'register_exports(app)' in text:
        return text
    block = '''
from app.exports import register_exports
from app.exports.company_pdf import COMPANY_PDF_COLUMNS, ensure_company_pdf_columns
from app.exports.excel import excel_rows_from_upload, normalize_import_header
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_match_month,
    _iris_month_label,
    _iris_normalize,
    _iris_official_finance,
    _iris_parse_br_float,
    _iris_payment_is_approved,
    _iris_payment_status,
    _iris_rows,
)
from app.exports.iris_reports import _iris_make_ai_pdf, _iris_make_monthly_pdf, _iris_make_payments_excel
from app.exports.jobs import _create_iris_job, _start_iris_job_thread
'''
    if 'from app.exports import register_exports' not in text:
        text = text.replace(
            'from app.outlook.services import maybe_start_monitor_worker\n',
            'from app.outlook.services import maybe_start_monitor_worker\n' + block,
            1,
        )
    text = text.replace(
        'register_outlook(app)\n',
        'register_outlook(app)\nregister_exports(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_exports(app)' in raw:
        print('Module 14 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_excel(lines)
    build_company_pdf(lines)
    build_iris_data(lines)
    build_iris_ai(lines)
    build_iris_reports(lines)
    build_jobs(lines)
    build_routes(lines)
    build_init()
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 14 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
