"""Apply Module 15 — Integrações (Iris chat / OpenAI / Anthropic)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
INT_DIR = ROOT / 'app' / 'integrations'
INT_DIR.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_exports(app)',
    'def admin_renumerar_os(',
    'def api_delete(',
    'maybe_start_monitor_worker()',
)

IRIS_CHAT_FUNCS = (
    '_iris_month_ref',
    '_iris_mode',
    '_iris_reply',
    '_iris_payment_hay',
    '_iris_detect_subject_terms',
    '_iris_filter_payments_by_terms',
    '_iris_group_sum',
    '_iris_group_count',
    '_iris_cost_subject_answer',
    '_iris_safe_json',
    '_iris_fallback_plan',
    '_iris_context_summary',
    '_iris_ai_plan',
    '_iris_extract_create_params',
    '_iris_search_payments',
    '_iris_answer',
    'iris_chat',
)

ROUTE_PATHS = ('/iris/chat',)

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


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)
'''

IRIS_HEADER = '''"""Iris — assistente conversacional (Claude + OpenAI)."""
import json
import re
from datetime import datetime
from urllib import parse as urllib_parse

from flask import current_app, jsonify, request, session, url_for

from app.exports.iris_ai import _iris_call_ai, _iris_call_claude
from app.exports.iris_data import (
    _iris_collect_context,
    _iris_month_label,
    _iris_normalize,
    _iris_official_finance,
    _iris_parse_br_float,
    _iris_payment_status,
    _iris_rows,
)
from app.exports.iris_reports import (
    _iris_make_ai_pdf,
    _iris_make_monthly_pdf,
    _iris_make_payments_excel,
)
from app.exports.jobs import _create_iris_job, _start_iris_job_thread
from app.os.services import os_is_overdue


def _legacy(name):
    from app import legacy
    return getattr(legacy, name)


def br_money(value):
    return _legacy('br_money')(value)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


'''

WHATSAPP_BODY = '''"""WhatsApp — re-exporta helpers de templates (storage)."""
from app.storage import (
    active_whatsapp_template,
    load_whatsapp_templates,
    save_whatsapp_templates,
    whatsapp_templates_path,
)

__all__ = [
    'active_whatsapp_template',
    'load_whatsapp_templates',
    'save_whatsapp_templates',
    'whatsapp_templates_path',
]
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
        if line.startswith('## ') and i > start + 2:
            end = i
            break
        if line.startswith('# ──') and i > start + 2:
            end = i
            break
        if line.startswith('# =') and 'Iris' not in line and i > start + 2:
            end = i
            break
    return end


def grab_def(lines, name):
    start = find_def_line(lines, name)
    end = find_block_end(lines, start)
    return ''.join(lines[start:end]), start, end


def grab_iris_constants(lines):
    start = next(i for i, l in enumerate(lines) if l.startswith('IRIS_BOMBA_TERMS'))
    end = start + 1
    while end < len(lines) and not lines[end].startswith('def _iris_detect_subject_terms'):
        end += 1
    bomba = ''.join(lines[start:end])
    start2 = next(i for i, l in enumerate(lines) if l.startswith('_IRIS_AI_SYSTEM_PLAN'))
    end2 = start2 + 1
    while end2 < len(lines) and not lines[end2].startswith('def _iris_context_summary'):
        end2 += 1
    plan = ''.join(lines[start2:end2])
    return bomba + '\n' + plan, min(start, start2), max(end, end2)


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
    for i in range(start, min(start + 8, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    end = find_block_end(lines, def_line)
    return ''.join(lines[start:end]), start, end


def strip_route_decorators(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    return re.sub(r'^@app\.(?:route|post|get)\([^\n]+\)\n', '', text, flags=re.M)


def assert_safe_delete(text, label):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('def admin_renumerar_os('):
            raise RuntimeError(f'{label} contains protected route {stripped!r}')
        if stripped.startswith('app = create_app('):
            raise RuntimeError(f'{label} contains protected app bootstrap')
        if 'register_exports(app)' in stripped and stripped.startswith('register_'):
            raise RuntimeError(f'{label} contains protected register_exports call')


def build_iris(lines):
    const_block, _, _ = grab_iris_constants(lines)
    parts = [IRIS_HEADER, const_block, '\n']
    for name in IRIS_CHAT_FUNCS:
        if name == 'iris_chat':
            continue
        body, _, _ = grab_def(lines, name)
        parts.append('\n\n' + body)
    route_body = ''
    for path in ROUTE_PATHS:
        block, _, _ = find_route_block(lines, path)
        body = strip_route_decorators(block)
        body = body.replace('app.logger', 'current_app.logger')
        route_body += body + '\n\n'
    register = '''
def register_iris_routes(app):
    app.add_url_rule('/iris/chat', 'iris_chat', iris_chat, methods=['POST'])
'''
    (INT_DIR / 'iris.py').write_text(''.join(parts) + route_body + register, encoding='utf-8')


def build_whatsapp():
    (INT_DIR / 'whatsapp.py').write_text(WHATSAPP_BODY, encoding='utf-8')


def build_init():
    (INT_DIR / '__init__.py').write_text(
        '''"""Integrações externas — Iris IA, WhatsApp."""
from app.integrations.iris import register_iris_routes


def register_integrations(app):
    register_iris_routes(app)


__all__ = ['register_integrations']
''',
        encoding='utf-8',
    )


def remove_iris_section_header(lines):
    for i, line in enumerate(lines):
        if line.strip() == '# Iris - assistente com API':
            start = i
            while start > 0 and lines[start - 1].strip().startswith('#'):
                start -= 1
            end = i + 1
            while end < len(lines) and lines[end].strip() == '#':
                end += 1
            return start, end
    return None


def remove_from_legacy(lines):
    spans = []
    hdr = remove_iris_section_header(lines)
    if hdr:
        spans.append(hdr)
    try:
        _, start, end = grab_iris_constants(lines)
        spans.append((start, end))
    except StopIteration:
        pass
    for name in IRIS_CHAT_FUNCS:
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
    if 'register_integrations(app)' in text:
        return text
    block = '\nfrom app.integrations import register_integrations\n'
    if 'from app.integrations import register_integrations' not in text:
        text = text.replace(
            'from app.exports.jobs import _create_iris_job, _start_iris_job_thread\n',
            'from app.integrations import register_integrations\n',
            1,
        )
    # Remove iris re-exports no longer needed in legacy bootstrap
    text = re.sub(
        r"from app\.exports\.iris_data import \(\n.*?\)\n",
        '',
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"from app\.exports\.iris_reports import _iris_make_ai_pdf, _iris_make_monthly_pdf, _iris_make_payments_excel\n",
        '',
        text,
        count=1,
    )
    text = re.sub(
        r"from app\.exports\.jobs import _create_iris_job, _start_iris_job_thread\n",
        '',
        text,
        count=1,
    )
    text = text.replace(
        'register_exports(app)\n',
        'register_exports(app)\nregister_integrations(app)\n',
        1,
    )
    # Drop unused OpenAI import from legacy top-level
    text = re.sub(
        r"\ntry:\n    from openai import OpenAI.*?\n    OpenAI = None\n",
        '\n',
        text,
        count=1,
        flags=re.S,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_integrations(app)' in raw:
        print('Module 15 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_iris(lines)
    build_whatsapp()
    build_init()
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 15 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
