"""Fase 2 — extrai helpers de legacy.py para app/shared/* e remove _legacy()."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / 'app' / 'shared'
LEGACY = ROOT / 'app' / 'legacy.py'

# símbolo -> (módulo de import, nome exportado)
SYMBOL_SOURCES = {
    'MESES_PT': ('app.shared.constants', 'MESES_PT'),
    'SISTEMAS_E_EQUIPAMENTOS': ('app.shared.constants', 'SISTEMAS_E_EQUIPAMENTOS'),
    'br_now': ('app.shared.formatters', 'br_now'),
    'parse_num': ('app.shared.formatters', 'parse_num'),
    'br_money': ('app.shared.formatters', 'br_money'),
    'parse_br_date': ('app.shared.formatters', 'parse_br_date'),
    'br_date': ('app.shared.formatters', 'br_date'),
    'normalize_phone': ('app.shared.formatters', 'normalize_phone'),
    'format_phone_br': ('app.shared.formatters', 'format_phone_br'),
    'now_str': ('app.shared.formatters', 'now_str'),
    'only_time_str': ('app.shared.formatters', 'only_time_str'),
    'time_diff_minutes': ('app.shared.formatters', 'time_diff_minutes'),
    'minutes_to_label': ('app.shared.formatters', 'minutes_to_label'),
    'elapsed_label': ('app.shared.formatters', 'elapsed_label'),
    'row_get_value': ('app.shared.rows', 'row_get_value'),
    'row_to_dict': ('app.shared.rows', 'row_to_dict'),
    'first_of': ('app.shared.rows', 'first_of'),
    'row_matches_month': ('app.shared.rows', 'row_matches_month'),
    'normalize_month_reference': ('app.shared.months', 'normalize_month_reference'),
    'detect_payments_reference_month': ('app.shared.months', 'detect_payments_reference_month'),
    'month_reference_matches_selected': ('app.shared.months', 'month_reference_matches_selected'),
    'month_reference_matches_current': ('app.shared.months', 'month_reference_matches_current'),
    'current_month_reference': ('app.shared.months', 'current_month_reference'),
    'month_or_current': ('app.shared.months', 'month_or_current'),
    'filter_rows_by_month': ('app.shared.months', 'filter_rows_by_month'),
    'compute_current_month_payments_total': ('app.shared.months', 'compute_current_month_payments_total'),
    'payment_status_is_paid': ('app.shared.payments', 'payment_status_is_paid'),
    'compute_payments_totals': ('app.shared.payments', 'compute_payments_totals'),
    'CACHE_TTL_SECONDS': ('app.shared.cache', 'CACHE_TTL_SECONDS'),
    'clear_view_cache': ('app.shared.cache', 'clear_view_cache'),
    'cached_result': ('app.shared.cache', 'cached_result'),
    'cached_query_all': ('app.shared.cache', 'cached_query_all'),
    'cached_query_one': ('app.shared.cache', 'cached_query_one'),
    'reset_sqlite_sequence_if_empty': ('app.shared.queries', 'reset_sqlite_sequence_if_empty'),
    'list_page': ('app.shared.queries', 'list_page'),
    '_safe_int_id': ('app.shared.queries', 'safe_int_id'),
    'ensure_valid_ids_for_table': ('app.shared.queries', 'ensure_valid_ids_for_table'),
    'fetch_sistemas_map': ('app.shared.queries', 'fetch_sistemas_map'),
    'user_has': ('app.auth', 'user_has'),
    'owned_by_current_company': ('app.auth', 'owned_by_current_company'),
    'is_mobile_request': ('app.auth.decorators', 'is_mobile_request'),
    'backup_company_data': ('app.storage', 'backup_company_data'),
    'ensure_company_storage': ('app.storage', 'ensure_company_storage'),
    'load_company_identity_config': ('app.storage', 'load_company_identity_config'),
    'save_company_identity_config': ('app.storage', 'save_company_identity_config'),
    'save_company_identity_file': ('app.storage', 'save_company_identity_file'),
    'table_pdf': ('app.os.pdf', 'table_pdf'),
    'excel_file': ('app.os.pdf', 'excel_file'),
    '_draw_pdf_header': ('app.os.pdf', '_draw_pdf_header'),
    'excel_rows_from_upload': ('app.exports.excel', 'excel_rows_from_upload'),
    'fetch_bombas_counts': ('app.controle.services', 'fetch_bombas_counts'),
    'ensure_os_tipo_os_column': ('app.os.services', 'ensure_os_tipo_os_column'),
    'os_is_overdue': ('app.os.services', 'os_is_overdue'),
    'select_existing_columns': ('app.db.schema', 'select_existing_columns'),
    '_api_campo_guard': ('app.campo.services', '_api_campo_guard'),
    'campo_status_finalizado': ('app.campo.services', 'campo_status_finalizado'),
    'campo_os_atrasada': ('app.campo.services', 'campo_os_atrasada'),
    'campo_status_pausado': ('app.campo.services', 'campo_status_pausado'),
    'campo_os_iniciada': ('app.campo.services', 'campo_os_iniciada'),
    'campo_numero_visivel': ('app.campo.services', 'campo_numero_visivel'),
    'campo_tecnico_for_os_row': ('app.campo.services', 'campo_tecnico_for_os_row'),
    'campo_token_for': ('app.campo.services', 'campo_token_for'),
    'campo_token_para_usuario': ('app.campo.services', 'campo_token_para_usuario'),
    'usuario_eh_campo_operacional': ('app.campo.services', 'usuario_eh_campo_operacional'),
    '_ensure_push_subscriptions_table': ('app.campo.push', '_ensure_push_subscriptions_table'),
    '_send_push': ('app.campo.push', '_send_push'),
}

CONSUMER_GLOBS = list((ROOT / 'app').rglob('*.py'))
SKIP_FILES = {
    LEGACY,
    ROOT / 'app' / 'legacy.py',
    ROOT / 'app' / 'bootstrap.py',
}


def grab_block(lines: list[str], start_pat: str, end_pat: str | None = None) -> str:
    start = next(i for i, l in enumerate(lines) if l.startswith(start_pat))
    if end_pat:
        end = next(i for i, l in enumerate(lines) if i > start and l.startswith(end_pat))
    else:
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith('def ') and not lines[i].startswith('def _'):
                end = i
                break
            if lines[i].startswith('def _') and 'next_numeric' in lines[i]:
                continue
    return ''.join(lines[start:end])


def extract_legacy_sections(text: str) -> dict[str, str]:
    lines = text.splitlines(keepends=True)

    def between(start, stop):
        a = next(i for i, l in enumerate(lines) if l.strip().startswith(start))
        b = next(i for i, l in enumerate(lines) if i > a and l.strip().startswith(stop))
        return ''.join(lines[a:b])

    constants = between('MESES_PT = {', 'def normalize_month_reference')
    formatters = (
        grab_block(lines, 'def br_now():', None).split('def normalize_month_reference')[0]
        + between('def parse_num(', 'def br_money(')
        + between('def br_money(', 'SISTEMAS_E_EQUIPAMENTOS')
        + between('def br_date(', 'def fetch_sistemas_map')
        + between('def now_str():', 'def fetch_sistemas_map')
    )
    # rebuild formatters cleanly from known functions in legacy
    fmt_parts = []
    for name in (
        'br_now', 'parse_num', 'br_money', 'br_date', 'normalize_phone', 'format_phone_br',
        'now_str', 'parse_br_date', 'only_time_str', 'time_diff_minutes', 'minutes_to_label', 'elapsed_label',
    ):
        fmt_parts.append(grab_def(lines, name))
    formatters = '\n\n'.join(fmt_parts)

    rows = '\n\n'.join(grab_def(lines, n) for n in ('row_get_value', 'first_of', 'row_matches_month', 'row_to_dict'))
    months = '\n\n'.join(
        grab_def(lines, n)
        for n in (
            'normalize_month_reference', 'detect_payments_reference_month', 'month_reference_matches_selected',
            'month_reference_matches_current', 'compute_current_month_payments_total', 'current_month_reference',
            'month_or_current', 'filter_rows_by_month',
        )
    )
    payments = '\n\n'.join(grab_def(lines, n) for n in ('payment_status_is_paid', 'compute_payments_totals'))
    cache = between('CACHE_TTL_SECONDS = 60', 'def reset_sqlite_sequence_if_empty')
    queries = '\n\n'.join(
        grab_def(lines, n)
        for n in (
            'reset_sqlite_sequence_if_empty', 'fetch_sistemas_map', 'list_page', '_safe_int_id',
            '_next_numeric_id_for_table', 'ensure_valid_ids_for_table',
        )
    )
    # rename _safe_int_id export
    queries = queries.replace('def _safe_int_id(', 'def safe_int_id(')

    return {
        'constants.py': CONSTANTS_HEADER + constants.rstrip() + '\n\n' + grab_const_sistemas(lines),
        'formatters.py': FORMATTERS_HEADER + formatters,
        'rows.py': ROWS_HEADER + rows,
        'months.py': MONTHS_HEADER + months,
        'payments.py': PAYMENTS_HEADER + payments,
        'cache.py': CACHE_HEADER + cache,
        'queries.py': QUERIES_HEADER + queries,
    }


def grab_def(lines, name):
    pat = re.compile(rf'^def {re.escape(name)}\(')
    start = next(i for i, l in enumerate(lines) if pat.match(l))
    end = start + 1
    while end < len(lines):
        if lines[end].startswith('def ') and end > start:
            break
        if lines[end].startswith('CACHE_TTL_SECONDS'):
            break
        if lines[end].startswith('SISTEMAS_E_EQUIPAMENTOS'):
            break
        if lines[end].startswith('# --- compat'):
            break
        end += 1
    return ''.join(lines[start:end]).rstrip()


def grab_const_sistemas(lines):
    start = next(i for i, l in enumerate(lines) if l.startswith('SISTEMAS_E_EQUIPAMENTOS'))
    end = start + 1
    while end < len(lines) and not lines[end].startswith('def br_date'):
        end += 1
    return ''.join(lines[start:end])


CONSTANTS_HEADER = '"""Constantes compartilhadas (meses, sistemas/equipamentos)."""\n\n'
FORMATTERS_HEADER = '''"""Formatação de datas, números e telefones."""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from app.config import APP_TIMEZONE

'''
ROWS_HEADER = '''"""Utilitários de linha/dict de query."""
import json

from app.storage import ATTACHMENT_GROUPS, sync_payment_attachments

'''
MONTHS_HEADER = '''"""Referências de mês (MM/AAAA) e filtros."""
import re
from datetime import datetime

from app.shared.constants import MESES_PT
from app.shared.formatters import br_now, parse_num, parse_br_date
from app.shared.rows import row_get_value, row_matches_month

'''
PAYMENTS_HEADER = '''"""Helpers de status/total de pagamentos."""
from app.shared.formatters import parse_num
from app.shared.months import month_reference_matches_selected, normalize_month_reference
from app.shared.rows import row_get_value

'''
CACHE_HEADER = '''"""Cache leve de views/queries."""
import threading
import time

from app.db import query_all, query_one

'''
QUERIES_HEADER = '''"""Queries compartilhadas (list_page, sistemas, IDs)."""
import json
import re

from app.auth import company_and, company_where, current_company_id
from app.db import USE_POSTGRES, execute, get_conn, query_one, table_columns
from app.db.schema import select_existing_columns
from app.shared.cache import cached_query_all, clear_view_cache
from app.shared.constants import SISTEMAS_E_EQUIPAMENTOS
from app.shared.rows import row_get_value, row_to_dict

'''


def write_shared_modules(sections: dict[str, str]):
    SHARED.mkdir(exist_ok=True)
    for name, body in sections.items():
        (SHARED / name).write_text(body.rstrip() + '\n', encoding='utf-8')


def write_shared_init():
    text = '''"""Helpers e utilitários compartilhados entre módulos."""
from app.shared.cache import (
    CACHE_TTL_SECONDS,
    cached_query_all,
    cached_query_one,
    cached_result,
    clear_view_cache,
)
from app.shared.constants import MESES_PT, SISTEMAS_E_EQUIPAMENTOS
from app.shared.formatters import (
    br_date,
    br_money,
    br_now,
    elapsed_label,
    format_phone_br,
    minutes_to_label,
    normalize_phone,
    now_str,
    only_time_str,
    parse_br_date,
    parse_num,
    time_diff_minutes,
)
from app.shared.months import (
    compute_current_month_payments_total,
    current_month_reference,
    detect_payments_reference_month,
    filter_rows_by_month,
    month_or_current,
    month_reference_matches_current,
    month_reference_matches_selected,
    normalize_month_reference,
)
from app.shared.payments import compute_payments_totals, payment_status_is_paid
from app.shared.queries import (
    ensure_valid_ids_for_table,
    fetch_sistemas_map,
    list_page,
    reset_sqlite_sequence_if_empty,
    safe_int_id,
)
from app.shared.rows import first_of, row_get_value, row_matches_month, row_to_dict

__all__ = [
    'CACHE_TTL_SECONDS', 'MESES_PT', 'SISTEMAS_E_EQUIPAMENTOS',
    'br_date', 'br_money', 'br_now', 'cached_query_all', 'cached_query_one', 'cached_result',
    'clear_view_cache', 'compute_current_month_payments_total', 'compute_payments_totals',
    'current_month_reference', 'detect_payments_reference_month', 'elapsed_label',
    'ensure_valid_ids_for_table', 'fetch_sistemas_map', 'filter_rows_by_month', 'first_of',
    'format_phone_br', 'list_page', 'minutes_to_label', 'month_or_current',
    'month_reference_matches_current', 'month_reference_matches_selected',
    'normalize_month_reference', 'normalize_phone', 'now_str', 'only_time_str',
    'parse_br_date', 'parse_num', 'payment_status_is_paid', 'reset_sqlite_sequence_if_empty',
    'row_get_value', 'row_matches_month', 'row_to_dict', 'safe_int_id', 'time_diff_minutes',
]
'''
    init_path = SHARED / '__init__.py'
    existing = init_path.read_text(encoding='utf-8') if init_path.exists() else ''
    register_part = ''
    if 'def register_shared' in existing:
        register_part = existing[existing.index('def register_shared'):]
    header = text.rstrip() + '\n\n\n'
    if register_part:
        (SHARED / '__init__.py').write_text(
            header + 'from app.shared.api import register_api_routes\nfrom app.shared.context import inject_globals\nfrom app.shared.routes import register_routes\n\n\n'
            + register_part,
            encoding='utf-8',
        )
    else:
        (SHARED / '__init__.py').write_text(text, encoding='utf-8')


def write_legacy_shim():
    LEGACY.write_text(
        '"""Shim temporário — use app.shared.* ou imports diretos dos módulos."""\n'
        'from app.shared import *  # noqa: F403\n'
        'from app.shared.queries import safe_int_id as _safe_int_id\n\n'
        'app = None\n',
        encoding='utf-8',
    )


def patch_bootstrap():
    path = ROOT / 'app' / 'bootstrap.py'
    text = path.read_text(encoding='utf-8')
    text = text.replace(
        'from app.legacy import br_date, br_money, format_phone_br, parse_br_date',
        'from app.shared.formatters import br_date, br_money, format_phone_br',
    )
    text = text.replace(
        'import app.legacy as legacy_module\n\nlegacy_module.app = app\n\n',
        '',
    )
    path.write_text(text, encoding='utf-8')


def patch_migrations():
    path = ROOT / 'app' / 'db' / 'migrations.py'
    text = path.read_text(encoding='utf-8')
    text = text.replace(
        'from app.legacy import now_str, row_to_dict',
        'from app.shared.formatters import now_str\n    from app.shared.rows import row_to_dict',
    )
    path.write_text(text, encoding='utf-8')


WRAPPER_START = re.compile(r'^def _legacy\(name\):')
WRAPPER_FUNC = re.compile(
    r'^def (?P<name>[a-zA-Z_][\w]*)\([^)]*\):\n(?:    .*\n)*?    return _legacy\([\'"](?P<sym>[^\'"]+)[\'"]\)',
    re.M,
)


def collect_symbols(text: str) -> set[str]:
    syms = set(re.findall(r"_legacy\(['\"]([^'\"]+)['\"]\)", text))
    syms.discard('app')
    return syms


def remove_legacy_wrappers(text: str) -> tuple[str, set[str]]:
    syms = collect_symbols(text)
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if WRAPPER_START.match(line):
            i += 1
            while i < len(lines) and (lines[i].startswith('    ') or lines[i].strip() == ''):
                i += 1
            continue
        if line.startswith('def ') and i + 1 < len(lines) and '_legacy(' in ''.join(lines[i:i+5]):
            block = ''.join(lines[i:i+6])
            m = re.match(r'^def (\w+)\(', line)
            if m and f"_legacy('{m.group(1)}')" in block.replace('_legacy("_safe_int_id")', ''):
                i += 1
                while i < len(lines) and (lines[i].startswith('    ') or lines[i].strip() == ''):
                    i += 1
                continue
            # wrapper with different name than symbol
            m2 = re.search(r"_legacy\(['\"]([^'\"]+)['\"]\)", block)
            if m2 and lines[i].startswith('def '):
                i += 1
                while i < len(lines) and (lines[i].startswith('    ') or lines[i].strip() == ''):
                    i += 1
                continue
        out.append(line)
        i += 1
    return ''.join(out), syms


def build_imports(symbols: set[str]) -> str:
    by_mod: dict[str, list[str]] = {}
    for sym in sorted(symbols):
        if sym not in SYMBOL_SOURCES:
            continue
        mod, export = SYMBOL_SOURCES[sym]
        by_mod.setdefault(mod, [])
        local = sym.lstrip('_') if sym == '_safe_int_id' else sym
        if export != sym and sym == '_safe_int_id':
            by_mod[mod].append(f'{export} as _safe_int_id')
        elif export != local:
            by_mod[mod].append(f'{export} as {local}')
        else:
            by_mod[mod].append(export)
    lines = []
    for mod in sorted(by_mod):
        names = sorted(set(by_mod[mod]))
        lines.append(f'from {mod} import {", ".join(names)}')
    return '\n'.join(lines) + ('\n' if lines else '')


def insert_imports(text: str, import_block: str) -> str:
    if not import_block.strip():
        return text
    text = re.sub(r'\nfrom app import legacy\n', '\n', text)
    text = re.sub(r'\nimport app\.legacy[^\n]*\n', '\n', text)
    # after module docstring / last import block
    m = re.search(r'(?:^from .+\n|^import .+\n)+', text, re.M)
    if m:
        end = m.end()
        return text[:end] + import_block + text[end:]
    return import_block + text


def patch_os_routes_app_logger(text: str) -> str:
    if "_legacy('app')" not in text:
        return text
    if 'from flask import' in text and 'current_app' not in text:
        text = text.replace('from flask import ', 'from flask import current_app, ', 1)
    text = text.replace("_legacy('app').logger", 'current_app.logger')
    return text


def patch_safe_int_id_calls(text: str) -> str:
    if '_safe_int_id' in text and 'safe_int_id as _safe_int_id' not in text:
        pass  # import handles alias
    return text


def patch_consumer(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    if '_legacy(' not in text and 'def _legacy(' not in text:
        return False
    text, syms = remove_legacy_wrappers(text)
    syms |= collect_symbols(text)
    syms.discard('app')
    imports = build_imports(syms)
    text = insert_imports(text, imports)
    text = patch_os_routes_app_logger(text)
    # direct _legacy calls left in body -> inline imports already cover symbols
    text = re.sub(r"_legacy\(['\"]([^'\"]+)['\"]\)(\.[\w]+)?\(", lambda m: f'{m.group(1).lstrip("_")}{m.group(2) or ""}(', text)
    text = re.sub(r"_legacy\(['\"]([^'\"]+)['\"]\)\.keys\(\)", lambda m: f"{SYMBOL_SOURCES.get(m.group(1), ('x', m.group(1)))[1]}.keys()", text)
    # fix SISTEMAS
    text = text.replace('_legacy(\'SISTEMAS_E_EQUIPAMENTOS\').keys()', 'SISTEMAS_E_EQUIPAMENTOS.keys()')
    path.write_text(text, encoding='utf-8')
    return True


def patch_integrations_iris():
    path = ROOT / 'app' / 'integrations' / 'iris.py'
    text = path.read_text(encoding='utf-8')
    if 'def _legacy(' not in text:
        return
    text, syms = remove_legacy_wrappers(text)
    text = text.replace(
        'def br_money(value):\n    return _legacy(\'br_money\')(value)\n\n\n',
        '',
    )
    if 'from app.shared.formatters import br_money' not in text:
        text = text.replace(
            'from app.os.services import os_is_overdue\n',
            'from app.os.services import os_is_overdue\nfrom app.shared.formatters import br_money\n',
        )
    text = re.sub(r'def _legacy[\s\S]*?return db_query_one[^\n]+\n\n', '', text, count=1)
    path.write_text(text, encoding='utf-8')


def main():
    if (SHARED / 'formatters.py').exists() and LEGACY.read_text(encoding='utf-8').startswith('"""Shim temporário'):
        print('Phase 2 already applied (shared modules + shim exist). Re-run consumers only.')
    else:
        legacy_text = LEGACY.read_text(encoding='utf-8')
        if legacy_text.startswith('"""Shim temporário'):
            print('Cannot extract: legacy is already shim. Restore from git or backup.')
            return
        sections = extract_legacy_sections(legacy_text)
        write_shared_modules(sections)
        write_shared_init()
        write_legacy_shim()
        patch_bootstrap()
        patch_migrations()

    count = 0
    for path in CONSUMER_GLOBS:
        if path in SKIP_FILES or path.name == '__init__.py' and path.parent == SHARED:
            continue
        if patch_consumer(path):
            count += 1
    patch_integrations_iris()
    print(f'Patched {count} consumer files.')
    print('legacy lines:', len(LEGACY.read_text(encoding='utf-8').splitlines()))


if __name__ == '__main__':
    main()
