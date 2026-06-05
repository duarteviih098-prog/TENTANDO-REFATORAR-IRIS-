"""Apply Module 12 — Inventário extraction (marker-based, idempotent)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
INV_DIR = ROOT / 'app' / 'inventario'
INV_DIR.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_auth(app)',
    'register_campo(app)',
    'def row_to_dict(',
    'def admin_renumerar_os(',
    'def renumerar_os_por_mes(',
)

ROUTE_PATHS = (
    '/inventario',
    '/inventario/hub',
    '/inventario/itens',
    '/inventario/pedidos',
    '/inventario/movimentacoes',
    '/inventario/save',
    '/inventario/delete',
    '/api/inventario/<int:rid>',
    '/inventario/movimento',
    '/inventario/pedido/save',
    '/inventario/mover-para-pedido',
    '/inventario/pedido/receber-lote',
    '/inventario/retirada',
    '/inventario/pedido/receber/<int:pid>',
    '/inventario/pedido/cancelar/<int:pid>',
)

LEGACY_HELPERS = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)


def br_now():
    return _legacy('br_now')()


def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)


def row_to_dict(row):
    return _legacy('row_to_dict')(row)


def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)


def clear_view_cache(prefix=None):
    return _legacy('clear_view_cache')(prefix)


def _safe_int_id(value):
    return _legacy('_safe_int_id')(value)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def get_current_user():
    from app.auth import get_current_user as fn
    return fn()


def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)


def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)


def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)


def ensure_db():
    from app.db.migrations import ensure_db as fn
    return fn()
'''


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
    for i in range(start, min(start + 10, len(lines))):
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
        if snippet in text:
            raise RuntimeError(f'{label} contains protected snippet {snippet!r}')


PERM_MAP = {
    'inventario_page': 'view_inventario',
    'inventario_hub': 'view_inventario',
    'inventario_itens': 'view_inventario',
    'inventario_pedidos_page': 'view_inventario',
    'inventario_movimentacoes': 'view_inventario',
    'inventario_save': 'edit_inventario',
    'inventario_delete_bulk': 'delete_inventario',
    'api_inventario_get': 'view_inventario',
    'inventario_movimento': 'edit_inventario',
    'inventario_pedido_save': 'edit_inventario',
    'inventario_mover_para_pedido': 'edit_inventario',
    'inventario_pedido_receber_lote': 'edit_inventario',
    'inventario_retirada': 'edit_inventario',
    'inventario_pedido_receber': 'edit_inventario',
    'inventario_pedido_cancelar': 'edit_inventario',
}

METHODS_MAP = {
    'inventario_page': ['GET'],
    'inventario_hub': ['GET'],
    'inventario_itens': ['GET'],
    'inventario_pedidos_page': ['GET'],
    'inventario_movimentacoes': ['GET'],
    'inventario_save': ['POST'],
    'inventario_delete_bulk': ['POST'],
    'api_inventario_get': ['GET'],
    'inventario_movimento': ['POST'],
    'inventario_pedido_save': ['POST'],
    'inventario_mover_para_pedido': ['POST'],
    'inventario_pedido_receber_lote': ['POST'],
    'inventario_retirada': ['POST'],
    'inventario_pedido_receber': ['POST'],
    'inventario_pedido_cancelar': ['POST'],
}


def build_routes(lines):
    route_body = ''
    for path in ROUTE_PATHS:
        block, _, _ = find_route_block(lines, path)
        route_body += strip_route_decorators(block) + '\n\n'

    for fn, perm in PERM_MAP.items():
        route_body = route_body.replace(f'def {fn}(', f"@require_permission('{perm}')\ndef {fn}(", 1)

    header = '''"""Rotas /inventario/* e API de inventário."""
import json

from flask import flash, jsonify, redirect, render_template, request, url_for

from app.auth.decorators import require_permission

'''
    endpoint_by_path = {
        '/inventario': 'inventario_page',
        '/inventario/hub': 'inventario_hub',
        '/inventario/itens': 'inventario_itens',
        '/inventario/pedidos': 'inventario_pedidos_page',
        '/inventario/movimentacoes': 'inventario_movimentacoes',
        '/inventario/save': 'inventario_save',
        '/inventario/delete': 'inventario_delete_bulk',
        '/api/inventario/<int:rid>': 'api_inventario_get',
        '/inventario/movimento': 'inventario_movimento',
        '/inventario/pedido/save': 'inventario_pedido_save',
        '/inventario/mover-para-pedido': 'inventario_mover_para_pedido',
        '/inventario/pedido/receber-lote': 'inventario_pedido_receber_lote',
        '/inventario/retirada': 'inventario_retirada',
        '/inventario/pedido/receber/<int:pid>': 'inventario_pedido_receber',
        '/inventario/pedido/cancelar/<int:pid>': 'inventario_pedido_cancelar',
    }
    register = '\ndef register_routes(app):\n    rules = [\n'
    for path in ROUTE_PATHS:
        ep = endpoint_by_path[path]
        methods = METHODS_MAP[ep]
        register += f"        ({path!r}, {ep!r}, {ep}, {methods!r}),\n"
    register += '    ]\n    for rule, endpoint, view, methods in rules:\n        app.add_url_rule(rule, endpoint, view, methods=methods)\n'

    (INV_DIR / 'routes.py').write_text(header + LEGACY_HELPERS + route_body + register, encoding='utf-8')


def build_init():
    (INV_DIR / '__init__.py').write_text(
        '''"""Módulo Inventário."""
from app.inventario.routes import register_routes


def register_inventario(app):
    register_routes(app)


__all__ = ['register_inventario']
''',
        encoding='utf-8',
    )


def remove_from_legacy(lines):
    spans = []
    for path in ROUTE_PATHS:
        _, start, end = find_route_block(lines, path)
        spans.append((start, end))
    for start, end in sorted(spans, reverse=True):
        block = ''.join(lines[start:end])
        assert_safe_delete(block, f'legacy delete {start + 1}')
        del lines[start:end]


def wire_legacy(text):
    if 'register_inventario(app)' in text:
        return text
    block = '\nfrom app.inventario import register_inventario\n'
    if 'from app.inventario import register_inventario' not in text:
        text = text.replace(
            'from app.campo import register_campo\n',
            'from app.campo import register_campo\n' + block,
            1,
        )
    text = text.replace(
        'register_campo(app)\n',
        'register_campo(app)\nregister_inventario(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_inventario(app)' in raw:
        print('Module 12 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_routes(lines)
    build_init()
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 12 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
