"""Apply Module 13 — Outlook / e-mail extraction (marker-based, idempotent)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
OUTLOOK_DIR = ROOT / 'app' / 'outlook'
OUTLOOK_DIR.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_auth(app)',
    'register_inventario(app)',
    'def row_to_dict(',
    'def parse_br_date(',
    'def query_all(',
    'maybe_start_monitor_worker()',
)

SERVICE_FUNCS = (
    'config_get',
    'config_set',
    'email_greeting',
    'split_emails',
    'normalize_email_block',
    'digits_only',
    'clean_html_text',
    'extract_email_body_from_message',
    'parse_monitor_event',
    'find_payment_for_monitor_event',
    'apply_monitor_event',
    'simulate_monitor_detection',
    'run_monitor_test_case',
    'built_in_monitor_test_scenarios',
    'monitor_provider_selected',
    'monitor_credentials_ready',
    'fetch_monitor_emails_imap',
    'fetch_monitor_emails_desktop',
    'fetch_monitor_emails',
    'process_monitor_payload',
    'monitor_status_snapshot',
    'list_pending_monitor_alerts',
    'mark_monitor_event_popup',
    'monitor_worker_enabled',
    'monitor_worker_interval_seconds',
    'update_monitor_worker_state',
    'get_monitor_worker_state',
    'run_monitor_cycle',
    'monitor_worker_loop',
    'maybe_start_monitor_worker',
    'extract_pdf_text',
    'extract_boleto_nf_from_email_message',
    'extract_boleto_due_date',
    'classify_attachment',
    'analyze_attachment_set',
    'choose_flow_attachments',
    'load_email_center',
    'default_template_values',
    'build_email_payload',
    'get_default_sender',
    'graph_credentials_ready',
    'smtp_credentials_ready',
    'provider_readiness',
    'resolve_attachment_paths',
    'can_send_payload',
    'build_graph_message',
    'acquire_graph_token',
    'send_via_graph',
    'send_via_smtp',
    'send_via_desktop',
    'send_real_email',
)

ROUTE_PATHS = (
    '/outlook/monitor-events/export',
    '/outlook/monitor-event/<int:event_id>/confirmar-boleto',
    '/outlook/monitor-event/<int:event_id>/dismiss',
    '/outlook/monitor-event/<int:event_id>/prepare',
    '/outlook/contacts/delete/<int:contact_id>',
    '/outlook/contacts/edit/<int:contact_id>',
    '/outlook/history/<int:history_id>/delete',
    '/outlook/history/clear-sent',
    '/outlook/history/clear-all',
    '/outlook/senders/save',
    '/outlook/contacts/save',
    '/outlook/templates/save',
    '/outlook/test-run',
    '/outlook/monitor-test-run',
    '/outlook/monitor-run',
    '/outlook/send-real',
    '/outlook',
)

WORKER_GLOBALS = '''
MONITOR_WORKER_LOCK = threading.Lock()
MONITOR_WORKER_THREAD = None
MONITOR_WORKER_STATE = {
    "enabled": False,
    "interval_seconds": 300,
    "running": False,
    "last_run_at": "",
    "last_status": "Aguardando",
    "last_summary": "Worker ainda não inicializado.",
    "last_error": "",
    "processed_total": 0,
    "applied_total": 0,
    "duplicates_total": 0,
}
'''

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


def now_str():
    return _legacy('now_str')()


def current_company_id():
    from app.auth import current_company_id as fn
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


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)
'''

SERVICES_HEADER = '''"""Outlook / e-mail — envio, monitoramento e integração com Pagamentos."""
import email
import imaplib
import io
import json
import mimetypes
import os
import re
import smtplib
import threading
import time
import urllib.error as urllib_error
import urllib.parse as urllib_parse
import urllib.request as urllib_request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from app.config import PROJECT_ROOT

try:
    import pythoncom  # type: ignore
    import win32com.client as win32_client  # type: ignore
except Exception:
    pythoncom = None
    win32_client = None

BASE_DIR = PROJECT_ROOT

'''

ROUTES_HEADER = '''"""Rotas /outlook/* — centro de e-mail e monitoramento."""
import csv
import io
import json
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, send_file, url_for

from app.auth.decorators import require_permission
from app.db import USE_POSTGRES
from app.outlook.services import (
    analyze_attachment_set,
    build_email_payload,
    built_in_monitor_test_scenarios,
    can_send_payload,
    config_get,
    config_set,
    default_template_values,
    fetch_monitor_emails,
    get_default_sender,
    load_email_center,
    get_monitor_worker_state,
    graph_credentials_ready,
    list_pending_monitor_alerts,
    mark_monitor_event_popup,
    monitor_credentials_ready,
    monitor_provider_selected,
    monitor_status_snapshot,
    normalize_email_block,
    process_monitor_payload,
    provider_readiness,
    resolve_attachment_paths,
    run_monitor_test_case,
    send_real_email,
    smtp_credentials_ready,
)
from app.config import PROJECT_ROOT

BASE_DIR = PROJECT_ROOT

'''

ENDPOINT_BY_PATH = {
    '/outlook/monitor-events/export': 'outlook_monitor_events_export',
    '/outlook/monitor-event/<int:event_id>/confirmar-boleto': 'outlook_monitor_event_confirmar_boleto',
    '/outlook/monitor-event/<int:event_id>/dismiss': 'outlook_monitor_event_dismiss',
    '/outlook/monitor-event/<int:event_id>/prepare': 'outlook_monitor_event_prepare',
    '/outlook/contacts/delete/<int:contact_id>': 'outlook_contact_delete',
    '/outlook/contacts/edit/<int:contact_id>': 'outlook_contact_edit',
    '/outlook/history/<int:history_id>/delete': 'outlook_history_delete',
    '/outlook/history/clear-sent': 'outlook_history_clear_sent',
    '/outlook/history/clear-all': 'outlook_history_clear_all',
    '/outlook/senders/save': 'outlook_sender_save',
    '/outlook/contacts/save': 'outlook_contact_save',
    '/outlook/templates/save': 'outlook_template_save',
    '/outlook/test-run': 'outlook_test_run',
    '/outlook/monitor-test-run': 'outlook_monitor_test_run',
    '/outlook/monitor-run': 'outlook_monitor_run',
    '/outlook/send-real': 'outlook_send_real',
    '/outlook': 'outlook_page',
}

METHODS_BY_ENDPOINT = {
    'outlook_page': ['GET'],
    'outlook_monitor_events_export': ['GET'],
    'outlook_sender_save': ['POST'],
    'outlook_contact_save': ['POST'],
    'outlook_contact_delete': ['GET'],
    'outlook_contact_edit': ['GET'],
    'outlook_template_save': ['POST'],
    'outlook_test_run': ['POST'],
    'outlook_monitor_test_run': ['POST'],
    'outlook_monitor_run': ['POST'],
    'outlook_monitor_event_dismiss': ['POST'],
    'outlook_monitor_event_confirmar_boleto': ['POST'],
    'outlook_monitor_event_prepare': ['POST'],
    'outlook_send_real': ['POST'],
    'outlook_history_delete': ['POST'],
    'outlook_history_clear_sent': ['POST'],
    'outlook_history_clear_all': ['POST'],
}


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
        if re.match(r'^[A-Z_][A-Z0-9_]*\s*=', line) and not line.startswith('MONITOR_'):
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


def find_worker_globals(lines):
    start = next(i for i, l in enumerate(lines) if l.startswith('MONITOR_WORKER_LOCK'))
    end = start + 1
    while end < len(lines) and not lines[end].startswith('CACHE_TTL_SECONDS'):
        end += 1
    return start, end


def assert_safe_delete(text, label):
    for snippet in DELETE_PROTECTED:
        if snippet in text and snippet != 'maybe_start_monitor_worker()':
            raise RuntimeError(f'{label} contains protected snippet {snippet!r}')


def build_services(lines):
    parts = [SERVICES_HEADER, WORKER_GLOBALS.strip(), '\n', LEGACY_HELPERS.strip(), '\n']
    for name in SERVICE_FUNCS:
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    (OUTLOOK_DIR / 'services.py').write_text(''.join(parts), encoding='utf-8')


def build_routes(lines):
    route_body = ''
    for path in ROUTE_PATHS:
        block, _, _ = find_route_block(lines, path)
        route_body += strip_route_decorators(block) + '\n\n'
    route_body = route_body.replace(
        'def outlook_page(',
        "@require_permission('view_outlook')\ndef outlook_page(",
        1,
    )
    if "@require_permission('edit_pagamentos')\ndef outlook_monitor_event_confirmar_boleto" not in route_body:
        route_body = route_body.replace(
            'def outlook_monitor_event_confirmar_boleto(',
            "@require_permission('edit_pagamentos')\ndef outlook_monitor_event_confirmar_boleto(",
            1,
        )
    register = '\ndef register_routes(app):\n    rules = [\n'
    for path in ROUTE_PATHS:
        ep = ENDPOINT_BY_PATH[path]
        methods = METHODS_BY_ENDPOINT[ep]
        register += f"        ({path!r}, {ep!r}, {ep}, {methods!r}),\n"
    register += '    ]\n    for rule, endpoint, view, methods in rules:\n        app.add_url_rule(rule, endpoint, view, methods=methods)\n'
    content = ROUTES_HEADER + LEGACY_HELPERS + route_body + register
    (OUTLOOK_DIR / 'routes.py').write_text(content, encoding='utf-8')


def build_init():
    (OUTLOOK_DIR / '__init__.py').write_text(
        '''"""Módulo Outlook / e-mail."""
from app.outlook.routes import register_routes
from app.outlook.services import (
    list_pending_monitor_alerts,
    maybe_start_monitor_worker,
)


def register_outlook(app):
    register_routes(app)


__all__ = [
    'register_outlook',
    'maybe_start_monitor_worker',
    'list_pending_monitor_alerts',
]
''',
        encoding='utf-8',
    )


def remove_from_legacy(lines):
    spans = []
    try:
        start, end = find_worker_globals(lines)
        spans.append((start, end))
    except StopIteration:
        pass
    for name in SERVICE_FUNCS:
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
    if 'register_outlook(app)' in text:
        return text
    block = '''
from app.outlook import register_outlook
from app.outlook.services import maybe_start_monitor_worker
'''
    if 'from app.outlook import register_outlook' not in text:
        text = text.replace(
            'from app.inventario import register_inventario\n',
            'from app.inventario import register_inventario\n' + block,
            1,
        )
    text = text.replace(
        'register_inventario(app)\n',
        'register_inventario(app)\nregister_outlook(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_outlook(app)' in raw:
        print('Module 13 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_services(lines)
    build_routes(lines)
    build_init()
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 13 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
