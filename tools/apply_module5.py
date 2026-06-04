"""Apply Module 5 shared UI extraction on current legacy."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
lines = legacy_path.read_text(encoding='utf-8').splitlines(keepends=True)
SHARED = ROOT / 'app' / 'shared'
SHARED.mkdir(exist_ok=True)


def grab(start, end):
    return ''.join(lines[start - 1:end])


def strip_routes(text):
    text = re.sub(r'^@require_permission\([^\n]+\)\n', '', text, flags=re.M)
    return re.sub(r'^@app\.route\([^\n]+\)\n', '', text, flags=re.M)


def strip_context(text):
    return re.sub(
        r'^@app\.context_processor\ndef inject_globals\(\):\n',
        'def inject_globals():\n',
        text,
        flags=re.M,
    )


LEGACY = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)

def br_now():
    return _legacy('br_now')()

def br_money(value):
    return _legacy('br_money')(value)

def normalize_month_reference(raw_value):
    return _legacy('normalize_month_reference')(raw_value)

def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)

def row_to_dict(row):
    return _legacy('row_to_dict')(row)

def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)

def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def select_existing_columns(table, desired, fallback='id'):
    return _legacy('select_existing_columns')(table, desired, fallback)

def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)

def fetch_bombas_counts():
    return _legacy('fetch_bombas_counts')()

def ensure_os_tipo_os_column():
    return _legacy('ensure_os_tipo_os_column')()

def compute_payments_totals(rows, selected_reference=None, end_reference=None):
    return _legacy('compute_payments_totals')(rows, selected_reference, end_reference)

def payment_status_is_paid(value):
    return _legacy('payment_status_is_paid')(value)

def os_is_overdue(row, ref_date=None):
    return _legacy('os_is_overdue')(row, ref_date)

def cached_result(key, producer, ttl=60):
    return _legacy('cached_result')(key, producer, ttl)

def fetch_sistemas_map():
    return _legacy('fetch_sistemas_map')()

'''

(SHARED / 'context.py').write_text(
    '''"""Variáveis globais de template (layout compartilhado)."""
from flask import request

from app.auth import (
    PERMISSION_LABELS,
    current_company,
    current_company_id,
    current_user_is_super_admin,
    get_current_user,
    list_companies,
    user_has,
)
from app.auth.services import _get_user_permissions

'''
    + LEGACY
    + strip_context(grab(2115, 2144)).replace(
        "'comb_vinculos': COMBUSTIVEL_VINCULOS,",
        "'comb_vinculos': __import__('app.legacy', fromlist=['legacy']).legacy.COMBUSTIVEL_VINCULOS,",
    ),
    encoding='utf-8',
)

static_routes = strip_routes(grab(520, 543))
dashboard_route = strip_routes(grab(2191, 2536))

(SHARED / 'routes.py').write_text(
    '''"""Rotas compartilhadas: health, loading, intro e dashboard."""
import re
from datetime import timedelta
from pathlib import Path

from flask import render_template, request, send_from_directory, session

from app.auth.decorators import require_permission
from app.config import PROJECT_ROOT
from app.storage.paths import BASE_DIR

'''
    + LEGACY
    + '''

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def company_where(table, prefix=' WHERE '):
    from app.auth import company_where as fn
    return fn(table, prefix)

'''
    + static_routes
    + '\n\n'
    + dashboard_route
    + '''

def register_routes(app):
    for rule, endpoint, view, methods, options in [
        ('/health', 'health', health, ['GET'], {}),
        ('/favicon.ico', 'favicon_root', favicon_root, ['GET'], {}),
        ('/loading', 'loading', loading, ['GET'], {}),
        ('/campo/loading', 'campo_loading', campo_loading, ['GET'], {}),
        ('/', 'intro', intro, ['GET'], {}),
        ('/home', 'dashboard', dashboard, ['GET'], {}),
    ]:
        app.add_url_rule(rule, endpoint, view, methods=methods, **options)

    app.add_url_rule('/home', 'home_page', dashboard, methods=['GET'])
    app.add_url_rule('/', 'index', intro, methods=['GET'])
''',
    encoding='utf-8',
)

# dashboard needs require_permission - wrap in register or decorator on function
routes_text = (SHARED / 'routes.py').read_text(encoding='utf-8')
routes_text = routes_text.replace(
    'def dashboard():',
    '@require_permission(\'view_dashboard\')\ndef dashboard():',
    1,
)
# favicon uses app.static_folder - fix to use flask current_app
routes_text = routes_text.replace(
    "static_dir = Path(app.static_folder or (BASE_DIR / 'static'))",
    "from flask import current_app\n    static_dir = Path(current_app.static_folder or (BASE_DIR / 'static'))",
    1,
)
(SHARED / 'routes.py').write_text(routes_text, encoding='utf-8')

(SHARED / '__init__.py').write_text(
    '''"""UI compartilhada: layout, dashboard e rotas utilitárias."""
from app.shared.context import inject_globals
from app.shared.routes import register_routes


def register_shared(app):
    register_routes(app)
    app.context_processor(inject_globals)


__all__ = ['register_shared', 'inject_globals']
''',
    encoding='utf-8',
)

for start, end in [
    (2536, 2191),
    (2144, 2115),
    (551, 547),
    (543, 520),
]:
    del lines[end - 1:start]

legacy_new = ''.join(lines)

shared_import = '''
from app.shared import register_shared
'''

legacy_new = re.sub(r'\nfrom app\.shared import register_shared\n', '\n', legacy_new, count=1)
legacy_new = re.sub(r'\nregister_shared\(app\)\n', '\n', legacy_new, count=1)

legacy_new = legacy_new.replace(
    'register_storage(app)\n',
    'register_storage(app)\nregister_shared(app)\n',
    1,
)

if 'from app.shared import register_shared' not in legacy_new:
    legacy_new = legacy_new.replace(
        'from app.auth import (',
        'from app.shared import register_shared\nfrom app.auth import (',
        1,
    )

legacy_path.write_text(legacy_new, encoding='utf-8')

# Move PNG da raiz para static/ (5.4)
for name in ('logo_direita.png', 'logo_esquerda.png', 'iris_icon.png', 'assinatura.png'):
    src = ROOT / name
    dest = ROOT / 'static' / name
    if src.exists() and src.is_file() and not dest.exists():
        shutil.copy2(src, dest)
        print('copied', name, '-> static/')

print('legacy lines:', len(legacy_new.splitlines()))
