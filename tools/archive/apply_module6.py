"""Apply Module 6 controle extraction on current legacy.

Uses function/route markers instead of fixed line numbers so re-runs stay safe.
Skips legacy surgery when register_controle is already wired in.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
CTRL = ROOT / 'app' / 'controle'
CTRL.mkdir(exist_ok=True)

PROTECTED_DEFS = frozenset({
    'row_to_dict',
    'fetch_sistemas_map',
    'combustivel_duplicado',
})


def find_def_line(lines, name):
    pat = re.compile(rf'^def {re.escape(name)}\(')
    for i, line in enumerate(lines):
        if pat.match(line):
            return i
    raise ValueError(f'def {name} not found')


def find_block_end(lines, start):
    """End before next top-level def, @app.route, or section banner."""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith('def ') or line.startswith('@app.route('):
            end = i
            break
        if line.startswith('# =') and i > start + 2:
            end = i
            break
    return end


def grab_def(lines, name):
    start = find_def_line(lines, name)
    end = find_block_end(lines, start)
    return ''.join(lines[start:end]), start, end


def find_route_block(lines, path_prefix):
    """Grab from @app.route('/controle...') through end of view function."""
    start = None
    route_pat = re.compile(rf"^@app\.route\('{re.escape(path_prefix)}")
    for i, line in enumerate(lines):
        if route_pat.match(line):
            start = i
            break
    if start is None:
        raise ValueError(f'route {path_prefix} not found')
    # skip decorators until def
    def_line = start
    for i in range(start, min(start + 5, len(lines))):
        if lines[i].startswith('def '):
            def_line = i
            break
    end = find_block_end(lines, def_line)
    return ''.join(lines[start:end]), start, end


def strip_routes(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    return re.sub(r'^@app\.route\([^\n]+\)\n', '', text, flags=re.M)


LEGACY = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)

def br_now():
    return _legacy('br_now')()

def parse_br_date(raw):
    return _legacy('parse_br_date')(raw)

def row_to_dict(row):
    return _legacy('row_to_dict')(row)

def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)

def row_matches_month(*values, month_ref=''):
    return _legacy('row_matches_month')(*values, month_ref=month_ref)

def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

def clear_view_cache(prefix=None):
    return _legacy('clear_view_cache')(prefix)

def list_page(table, order='id DESC', limit=120):
    return _legacy('list_page')(table, order, limit)

def excel_rows_from_upload(file_storage):
    return _legacy('excel_rows_from_upload')(file_storage)

def first_of(row, *keys):
    return _legacy('first_of')(row, *keys)

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)

def company_and(table):
    from app.auth import company_and as fn
    return fn(table)

'''


def build_controle_modules(lines):
    svc_parts = [LEGACY]
    for name in ('compute_bomba_delivery', 'fetch_bombas_counts', 'save_bomba', 'import_controle_excel'):
        body, _, _ = grab_def(lines, name)
        svc_parts.append('\n\n' + body)

    (CTRL / 'services.py').write_text(
        '"""Regras de negócio do estoque de bombas (controle)."""\n'
        'from datetime import datetime, timedelta\n\n'
        'from app.auth import company_and, company_where, current_company_id\n'
        'from app.db import execute, query_all, query_one\n'
        + ''.join(svc_parts),
        encoding='utf-8',
    )

    route_paths = [
        '/controle',
        '/controle/hub',
        '/controle/lista',
        '/controle/mapa',
        '/controle/localizacao',
        '/controle/historico',
        '/controle/api/<int:rid>',
        '/controle/movimentar',
        '/controle/locais',
        '/controle/locais/<int:rid>',
        '/controle/delete',
        '/controle_excel',
        '/controle/save',
        '/controle/import',
    ]
    routes_body = ''
    for path in route_paths:
        block, _, _ = find_route_block(lines, path)
        routes_body += strip_routes(block) + '\n\n'

    perm_map = {
        'controle': 'view_controle',
        'controle_hub': 'view_controle',
        'controle_lista': 'view_controle',
        'controle_mapa': 'view_controle',
        'controle_localizacao': 'view_controle',
        'controle_historico': 'view_controle',
        'controle_api_detail': 'view_controle',
        'controle_movimentar': 'edit_controle',
        'controle_locais': 'view_controle',
        'controle_locais_delete': 'edit_controle',
        'controle_delete': 'delete_controle',
        'controle_excel': 'generate_excel',
        'controle_save': 'edit_controle',
    }
    for fn, perm in perm_map.items():
        routes_body = routes_body.replace(
            f'def {fn}(',
            f"@require_permission('{perm}')\ndef {fn}(",
            1,
        )

    (CTRL / 'routes.py').write_text(
        '"""Rotas /controle/* e exportação Excel."""\n'
        'from datetime import datetime\n'
        'from pathlib import Path\n\n'
        'from flask import flash, jsonify, redirect, render_template, request, send_file, url_for\n\n'
        'from app.auth.decorators import require_permission\n'
        'from app.controle.services import fetch_bombas_counts, import_controle_excel, save_bomba\n'
        'from app.storage.paths import BASE_DIR\n'
        + LEGACY
        + routes_body
        + '''

def register_routes(app):
    rules = [
        ('/controle', 'controle', controle, ['GET']),
        ('/controle/hub', 'controle_hub', controle_hub, ['GET']),
        ('/controle/lista', 'controle_lista', controle_lista, ['GET']),
        ('/controle/mapa', 'controle_mapa', controle_mapa, ['GET']),
        ('/controle/localizacao', 'controle_localizacao', controle_localizacao, ['GET']),
        ('/controle/historico', 'controle_historico', controle_historico, ['GET']),
        ('/controle/api/<int:rid>', 'controle_api_detail', controle_api_detail, ['GET']),
        ('/controle/movimentar', 'controle_movimentar', controle_movimentar, ['POST']),
        ('/controle/locais', 'controle_locais', controle_locais, ['GET', 'POST']),
        ('/controle/locais/<int:rid>', 'controle_locais_delete', controle_locais_delete, ['DELETE']),
        ('/controle/delete', 'controle_delete', controle_delete, ['POST']),
        ('/controle_excel', 'controle_excel', controle_excel, ['GET']),
        ('/controle/save', 'controle_save', controle_save, ['POST']),
        ('/controle/import', 'controle_import', controle_import, ['POST']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
''',
        encoding='utf-8',
    )

    (CTRL / '__init__.py').write_text(
        '''"""Módulo Controle — estoque de bombas."""
from app.controle.routes import register_routes
from app.controle.services import (
    compute_bomba_delivery,
    fetch_bombas_counts,
    import_controle_excel,
    save_bomba,
)


def register_controle(app):
    register_routes(app)


__all__ = [
    'register_controle',
    'compute_bomba_delivery',
    'fetch_bombas_counts',
    'save_bomba',
    'import_controle_excel',
]
''',
        encoding='utf-8',
    )


def remove_from_legacy(lines):
    """Delete controle defs/routes from legacy; never touch PROTECTED_DEFS."""
    spans = []
    for name in ('compute_bomba_delivery', 'fetch_bombas_counts', 'save_bomba', 'import_controle_excel'):
        try:
            _, start, end = grab_def(lines, name)
            spans.append((start, end))
        except ValueError:
            pass

    for path in (
        '/controle/import',
        '/controle/save',
        '/controle_excel',
        '/controle/delete',
        '/controle/locais/<int:rid>',
        '/controle/locais',
        '/controle/movimentar',
        '/controle/api/<int:rid>',
        '/controle/historico',
        '/controle/localizacao',
        '/controle/mapa',
        '/controle/lista',
        '/controle/hub',
        '/controle',
    ):
        try:
            _, start, end = find_route_block(lines, path)
            spans.append((start, end))
        except ValueError:
            pass

    for start, end in sorted(spans, reverse=True):
        if any(find_def_line(lines, p) == start for p in PROTECTED_DEFS if p in ''.join(lines[start:end])):
            raise RuntimeError(f'refusing to delete protected block at line {start + 1}')
        del lines[start:end]


def wire_legacy(text):
    controle_import = '''
from app.controle import register_controle
from app.controle.services import fetch_bombas_counts, import_controle_excel, save_bomba
'''
    if 'register_controle(app)' in text:
        return text
    if 'from app.controle import register_controle' not in text:
        if 'from app.shared import register_shared' in text:
            text = text.replace(
                'from app.shared import register_shared\n',
                'from app.shared import register_shared\n' + controle_import,
                1,
            )
        else:
            text = text.replace(
                'from app.factory import create_app\n',
                'from app.factory import create_app\n' + controle_import,
                1,
            )
    text = text.replace(
        'register_shared(app)\n',
        'register_shared(app)\nregister_controle(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    lines = raw.splitlines(keepends=True)
    already = 'register_controle(app)' in raw

    if not already:
        build_controle_modules(lines)
        remove_from_legacy(lines)
        legacy_new = wire_legacy(''.join(lines))
    else:
        print('register_controle already present — refreshing app/controle/* only')
        build_controle_modules(lines)
        legacy_new = raw

    legacy_path.write_text(legacy_new, encoding='utf-8')
    print('legacy lines:', len(legacy_new.splitlines()))


if __name__ == '__main__':
    main()
