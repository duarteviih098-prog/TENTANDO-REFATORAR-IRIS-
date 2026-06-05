"""Extract auth/tenancy layer from legacy.py (Module 3)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
lines = legacy_path.read_text(encoding='utf-8').splitlines(keepends=True)
AUTH = ROOT / 'app' / 'auth'
AUTH.mkdir(exist_ok=True)


def grab(start, end):
    return ''.join(lines[start - 1:end])


def strip_app_route_decorators(text):
    return re.sub(r'^@app\.route\([^\n]+\)\n', '', text, flags=re.M)


def strip_app_decorators(text):
    text = re.sub(r'^@app\.(route|before_request|after_request|context_processor|errorhandler)\([^\n]*\)\n', '', text, flags=re.M)
    return text


# --- constants ---
(AUTH / 'constants.py').write_text(
    '''"""Permissões, papéis e tabelas multi-empresa."""
import json

'''
    + grab(1203, 1277),
    encoding='utf-8',
)

# --- tenancy ---
tenancy_body = grab(606, 690) + '\n' + grab(1279, 1280) + grab(1282, 1419)
(AUTH / 'tenancy.py').write_text(
    '''"""Contexto de empresa (multi-tenant)."""
import json
import re
import threading

from flask import g, has_request_context, session

from app.db import query_all, query_one, table_has_column
from app.auth.constants import TENANT_TABLES

# Evita import circular com legacy (identidade PDF da empresa).
def _legacy():
    from app import legacy
    return legacy

def row_to_dict(row):
    return _legacy().row_to_dict(row)

def now_str():
    return _legacy().now_str()

def select_existing_columns(table, desired, fallback='id'):
    return _legacy().select_existing_columns(table, desired, fallback)

def ensure_company_pdf_columns():
    return _legacy().ensure_company_pdf_columns()

def load_company_identity_config(empresa_id=None):
    return _legacy().load_company_identity_config(empresa_id)

def ensure_company_storage(empresa_id=None):
    return _legacy().ensure_company_storage(empresa_id)

def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

'''
    + tenancy_body,
    encoding='utf-8',
)

# --- services ---
(AUTH / 'services.py').write_text(
    '''"""Usuário logado, permissões e validação de senha."""
import hmac
import os
import time
import threading

from flask import g, has_request_context, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth.constants import ALL_PERMISSIONS, ROLE_PERMISSIONS, normalize_permissions
from app.auth.tenancy import (
    current_company_id,
    current_user_is_super_admin,
    find_company_by_domain_or_name,
    normalize_domain,
)
from app.db import execute, query_one

def row_to_dict(row):
    from app import legacy
    return legacy.row_to_dict(row)

'''
    + grab(1421, 1479)
    + '\n\n'
    + grab(3237, 3254).replace('ALL_PERMISSIONS.keys()', 'ALL_PERMISSIONS')
    + '\n\n'
    + grab(3291, 3316)
    + '\n\n'
    + grab(3467, 3510),
    encoding='utf-8',
)

# --- decorators ---
decorators_body = grab(1457, 1468) + grab(1481, 1542)
decorators_body = decorators_body.replace('user_has(\'view_dashboard\') else url_for(\'os_page\')',
                                        'user_has(\'view_dashboard\') else url_for(\'os_page\')')
(AUTH / 'decorators.py').write_text(
    '''"""Decorators e gate de autenticação."""
from functools import wraps

from flask import flash, redirect, request, session, url_for

from app.auth.services import get_current_user, user_has

def row_to_dict(row):
    from app import legacy
    return legacy.row_to_dict(row)

def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

'''
    + decorators_body,
    encoding='utf-8',
)

# --- csrf ---
(AUTH / 'csrf.py').write_text(
    '''"""Proteção CSRF."""
from flask import request, session

'''
    + grab(1544, 1595).replace('@app.context_processor\ndef inject_csrf():', 'def inject_csrf():'),
    encoding='utf-8',
)

# --- guards ---
guards_body = grab(1597, 1616).replace('@app.before_request\ndef auth_gate():', 'def auth_gate():')
guards_body += grab(1619, 1656).replace('@app.errorhandler(404)\ndef handle_not_found', 'def handle_not_found')
guards_body = guards_body.replace('@app.errorhandler(Exception)\ndef handle_unexpected_error', 'def handle_unexpected_error')
(AUTH / 'guards.py').write_text(
    '''"""Middleware de sessão, CSRF e handlers globais."""
import time

from flask import flash, has_request_context, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.config import SESSION_IDLE_MINUTES
from app.auth.csrf import _csrf_validate
from app.auth.decorators import ensure_logged_in
from app.auth.services import user_has

'''
    + guards_body,
    encoding='utf-8',
)

# --- audit ---
audit_body = grab(1659, 1736).replace('@app.after_request\ndef audit_after_request', 'def audit_after_request')
(AUTH / 'audit.py').write_text(
    '''"""Auditoria de ações POST/PUT/PATCH/DELETE."""
import json

from flask import request

from app.auth.services import get_current_user
from app.db import execute

def now_str():
    from app import legacy
    return legacy.now_str()

'''
    + audit_body,
    encoding='utf-8',
)

# --- password_reset ---
(AUTH / 'password_reset.py').write_text(
    '''"""Recuperação de senha por e-mail."""
import os
import smtplib
import threading
import time
import uuid
from email.message import EmailMessage

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from app.db import execute, query_one

_PASSWORD_RESET_TOKENS = {}
_PASSWORD_RESET_LOCK = threading.Lock()
PASSWORD_RESET_EXPIRY = 3600

'''
    + grab(3331, 3364)
    + '\n\n'
    + strip_app_route_decorators(grab(3367, 3428)),
    encoding='utf-8',
)

# --- routes ---
routes_src = (
    strip_app_route_decorators(grab(3318, 3320))
    + '\n\n'
    + strip_app_route_decorators(grab(3513, 4028))
)
routes_src = routes_src.replace('return login()', 'from app.auth.routes import login as _login_view\n    return _login_view()')
# Fix campo_login circular - use services login directly
routes_src = routes_src.replace(
    'from app.auth.routes import login as _login_view\n    return _login_view()',
    'return login()',
)
(AUTH / 'routes.py').write_text(
    '''"""Rotas de login, usuários, empresas e auditoria."""
import json
import os
import time

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

from app.auth.constants import ALL_PERMISSIONS, PERMISSION_LABELS, ROLE_LABELS, ROLE_PERMISSIONS, normalize_permissions
from app.auth.decorators import require_permission
from app.auth.services import (
    LOGIN_BLOCK_SECONDS,
    LOGIN_MAX_ATTEMPTS,
    _login_clear,
    _login_get_ip,
    _login_is_blocked,
    _login_record_failure,
    current_user_is_super_admin,
    get_current_user,
    senha_confere,
    user_has,
)
from app.auth.tenancy import (
    create_company_if_needed,
    current_company_id,
    find_company_by_domain_or_name,
    list_companies,
    normalize_domain,
    normalize_phone,
    unique_email_for_domain,
)
from app.db import execute, query_all, query_one, table_has_column

def row_to_dict(row):
    from app import legacy
    return legacy.row_to_dict(row)

def now_str():
    from app import legacy
    return legacy.now_str()

def br_now():
    from app import legacy
    return legacy.br_now()

def clear_view_cache(prefix=None):
    from app import legacy
    return legacy.clear_view_cache(prefix)

def ensure_company_storage(empresa_id=None):
    from app import legacy
    return legacy.ensure_company_storage(empresa_id)

def save_company_identity_config(data, empresa_id=None):
    from app import legacy
    return legacy.save_company_identity_config(data, empresa_id=empresa_id)

def save_company_identity_file(file_obj, filename, empresa_id=None):
    from app import legacy
    return legacy.save_company_identity_file(file_obj, filename, empresa_id=empresa_id)

def load_company_identity_config(empresa_id=None):
    from app import legacy
    return legacy.load_company_identity_config(empresa_id=empresa_id)

def backup_company_data(empresa_id=None):
    from app import legacy
    return legacy.backup_company_data(empresa_id=empresa_id)

def owned_by_current_company(table, rid):
    from app.auth.tenancy import owned_by_current_company as _owned
    return _owned(table, rid)

def usuario_eh_campo_operacional(user):
    from app import legacy
    return legacy.usuario_eh_campo_operacional(user)

def campo_token_para_usuario(user):
    from app import legacy
    return legacy.campo_token_para_usuario(user)

def sincronizar_usuario_campo(*args, **kwargs):
    from app import legacy
    return legacy.sincronizar_usuario_campo(*args, **kwargs)

def is_mobile_request():
    from app import legacy
    return legacy.is_mobile_request()

'''
    + routes_src
    + '''

def register_routes(app):
    """Registra rotas preservando endpoints/url_for originais."""
    from app.auth import password_reset

    rules = [
        ('/campo/login', 'campo_login', campo_login, ['GET', 'POST']),
        ('/login', 'login', login, ['GET', 'POST']),
        ('/logout', 'logout', logout, ['GET']),
        ('/historico/apagar-tudo', 'historico_apagar_tudo', historico_apagar_tudo, ['POST']),
        ('/historico', 'historico_page', historico_page, ['GET']),
        ('/empresa/contexto/<int:empresa_id>', 'empresa_contexto', empresa_contexto, ['GET']),
        ('/visao-global', 'visao_global', visao_global, ['GET']),
        ('/usuarios', 'usuarios_page', usuarios_page, ['GET']),
        ('/empresas/save', 'empresas_save', empresas_save, ['POST']),
        ('/empresas/update/<int:empresa_id>', 'empresas_update', empresas_update, ['POST']),
        ('/usuarios/save', 'usuarios_save', usuarios_save, ['POST']),
        ('/usuarios/delete/<int:rid>', 'usuarios_delete', usuarios_delete, ['POST']),
        ('/esqueci-senha', 'esqueci_senha', password_reset.esqueci_senha, ['GET', 'POST']),
        ('/redefinir-senha/<token>', 'redefinir_senha', password_reset.redefinir_senha, ['GET', 'POST']),
    ]
    for path, endpoint, view, methods in rules:
        app.add_url_rule(path, endpoint, view, methods=methods)
''',
    encoding='utf-8',
)

# Fix campo_login - should call login in same module
routes_text = (AUTH / 'routes.py').read_text(encoding='utf-8')
routes_text = routes_text.replace(
    "def campo_login():\n    return login()",
    "def campo_login():\n    return login()  # mesmo handler",
)
(AUTH / 'routes.py').write_text(routes_text, encoding='utf-8')

# --- __init__.py ---
(AUTH / '__init__.py').write_text(
    '''"""Autenticação, permissões e multi-empresa."""
from app.auth.audit import audit_after_request
from app.auth.constants import (
    ALL_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    TENANT_TABLES,
    normalize_permissions,
)
from app.auth.csrf import inject_csrf
from app.auth.decorators import ensure_logged_in, module_view_permission, require_permission
from app.auth.guards import auth_gate, handle_not_found, handle_unexpected_error
from app.auth.routes import register_routes
from app.auth.services import (
    get_current_user,
    senha_confere,
    user_has,
    current_user_is_super_admin,
)
from app.auth.tenancy import (
    company_and,
    company_where,
    create_company_if_needed,
    current_company,
    current_company_id,
    find_company_by_domain_or_name,
    list_companies,
    normalize_domain,
    owned_by_current_company,
    unique_email_for_domain,
    set_background_company_id,
    get_background_company_id,
)

# Aliases para compatibilidade
def _export_background_helpers():
    from app.auth import tenancy
    return tenancy

def set_background_company_id(empresa_id):
    _export_background_helpers()._BACKGROUND_COMPANY_CONTEXT.empresa_id = empresa_id

def get_background_company_id():
    return getattr(_export_background_helpers()._BACKGROUND_COMPANY_CONTEXT, 'empresa_id', None)


def register_auth(app):
    """Registra rotas e middleware de auth no app Flask."""
    register_routes(app)
    app.before_request(auth_gate)
    app.context_processor(inject_csrf)
    app.after_request(audit_after_request)
    app.errorhandler(404)(handle_not_found)
    app.errorhandler(Exception)(handle_unexpected_error)

__all__ = [
    'register_auth',
    'ALL_PERMISSIONS',
    'PERMISSION_LABELS',
    'ROLE_LABELS',
    'ROLE_PERMISSIONS',
    'TENANT_TABLES',
    'normalize_permissions',
    'get_current_user',
    'user_has',
    'senha_confere',
    'current_user_is_super_admin',
    'current_company_id',
    'current_company',
    'company_where',
    'company_and',
    'owned_by_current_company',
    'list_companies',
    'require_permission',
    'module_view_permission',
    'create_company_if_needed',
    'find_company_by_domain_or_name',
    'normalize_domain',
    'unique_email_for_domain',
    'set_background_company_id',
    'get_background_company_id',
]
''',
    encoding='utf-8',
)

# Fix __init__ - set_background_company_id defined twice badly. Simplify __init__.py

(AUTH / '__init__.py').write_text(
    '''"""Autenticação, permissões e multi-empresa."""
from app.auth.audit import audit_after_request
from app.auth.constants import (
    ALL_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    TENANT_TABLES,
    normalize_permissions,
)
from app.auth.csrf import inject_csrf
from app.auth.decorators import ensure_logged_in, module_view_permission, require_permission
from app.auth.guards import auth_gate, handle_not_found, handle_unexpected_error
from app.auth.routes import register_routes
from app.auth.services import get_current_user, senha_confere, user_has, current_user_is_super_admin
from app.auth.tenancy import (
    _BACKGROUND_COMPANY_CONTEXT,
    company_and,
    company_where,
    create_company_if_needed,
    current_company,
    current_company_id,
    find_company_by_domain_or_name,
    list_companies,
    normalize_domain,
    owned_by_current_company,
    unique_email_for_domain,
)


def set_background_company_id(empresa_id):
    _BACKGROUND_COMPANY_CONTEXT.empresa_id = empresa_id


def get_background_company_id():
    return getattr(_BACKGROUND_COMPANY_CONTEXT, 'empresa_id', None)


def register_auth(app):
    register_routes(app)
    app.before_request(auth_gate)
    app.context_processor(inject_csrf)
    app.after_request(audit_after_request)
    app.errorhandler(404)(handle_not_found)
    app.errorhandler(Exception)(handle_unexpected_error)


__all__ = [
    'register_auth',
    'ALL_PERMISSIONS', 'PERMISSION_LABELS', 'ROLE_LABELS', 'ROLE_PERMISSIONS', 'TENANT_TABLES',
    'normalize_permissions', 'get_current_user', 'user_has', 'senha_confere', 'current_user_is_super_admin',
    'current_company_id', 'current_company', 'company_where', 'company_and', 'owned_by_current_company',
    'list_companies', 'require_permission', 'module_view_permission', 'create_company_if_needed',
    'find_company_by_domain_or_name', 'normalize_domain', 'unique_email_for_domain',
    'set_background_company_id', 'get_background_company_id',
]
''',
    encoding='utf-8',
)

# Remove extracted sections from legacy (reverse order)
remove_ranges = [
    (4028, 3513),   # routes login-usuarios (reversed means 3513-4028)
    (3510, 3467),   # login helpers
    (3428, 3322),   # password reset block including routes - careful includes TOKEN 3432
    (3316, 3291),   # senha_confere
    (3254, 3237),   # _get_user_permissions - keep inject_globals
    (1736, 1659),   # audit helpers + after_request
    (1656, 1544),   # guards csrf auth_gate errors
    (1542, 1481),   # ensure_logged_in only? 1457-1479 require_permission already in services slice
    (1479, 1421),   # get_current_user block - wait need careful ordering
]

# Rebuild remove list properly (high to low line numbers)
remove_ranges = [
    (4028, 3513),
    (3510, 3467),
    (3428, 3322),
    (3320, 3318),
    (3316, 3291),
    (1736, 1593),
    (1656, 1619),  # error handlers included in 1736-1593? overlap
    (1542, 1457),  # ensure_logged_in + require_permission - require in services
    (1419, 1203),  # constants through list_companies
    (690, 606),    # company helpers
]

# Fix: 1736-1593 includes csrf inject, auth_gate, errors, audit - good
# 1542-1457 removes ensure_logged_in and require_permission - but require in services 1421-1479
# Order: delete 1421-1479 as part of 1419-1203? list_companies ends 1419, get_current starts 1421

remove_ranges = [
    (4028, 3318),
    (3510, 3467),
    (1736, 1457),
    (1419, 1203),
    (690, 606),
]

for start, end in remove_ranges:
    del lines[start - 1:end]

legacy_new = ''.join(lines)

import_block = '''
from app.auth import (
    ALL_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    TENANT_TABLES,
    company_and,
    company_where,
    create_company_if_needed,
    current_company,
    current_company_id,
    current_user_is_super_admin,
    find_company_by_domain_or_name,
    get_current_user,
    list_companies,
    module_view_permission,
    normalize_domain,
    normalize_permissions,
    owned_by_current_company,
    register_auth,
    require_permission,
    senha_confere,
    unique_email_for_domain,
    user_has,
    get_background_company_id,
    set_background_company_id,
)
'''

marker = 'app = create_app()'
if 'register_auth(app)' not in legacy_new:
    legacy_new = legacy_new.replace(
        marker,
        marker + '\nregister_auth(app)',
        1,
    )

if 'from app.auth import' not in legacy_new:
    legacy_new = legacy_new.replace(
        'from app.factory import create_app\n\napp = create_app()',
        'from app.factory import create_app\n' + import_block + '\napp = create_app()',
        1,
    )

# inject_globals uses _get_user_permissions
legacy_new = legacy_new.replace(
    '_get_user_permissions(user)',
    '_get_user_permissions_from_auth(user)',
)
legacy_new = legacy_new.replace(
    'from app.auth import (',
    'from app.auth.services import _get_user_permissions as _get_user_permissions_from_auth\nfrom app.auth import (',
    1,
)

legacy_path.write_text(legacy_new, encoding='utf-8')
print('legacy lines:', len(legacy_new.splitlines()))
print('done')
