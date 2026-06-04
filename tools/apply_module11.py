"""Apply Module 11 — Campo / PWA extraction (marker-based, idempotent)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
CAMPO = ROOT / 'app' / 'campo'
CAMPO.mkdir(exist_ok=True)

DELETE_PROTECTED = (
    'app = create_app(',
    'register_auth(app)',
    'register_os(app)',
    'def row_to_dict(',
    'def fetch_sistemas_map(',
    'def list_page(',
)

TOKEN_FUNCS = (
    '_token_expira_str',
    '_token_expirado',
    '_token_renovar',
    '_token_revogar',
)

PUSH_FUNCS = (
    '_ensure_push_subscriptions_table',
    '_send_push',
)

SERVICE_FUNCS = (
    'resumo_curto',
    'campo_token_for',
    'ensure_absolute_url',
    'public_base_url',
    'campo_link_publico',
    'campo_tecnico_token_for',
    'campo_tecnico_app_link',
    'campo_link_com_tecnico',
    'campo_tecnico_por_token',
    'campo_mesmo_tecnico',
    'campo_whatsapp_url',
    'campo_whatsapp_url_para_tecnico',
    'ensure_campo_eventos_table',
    'campo_evento_registrar',
    '_api_campo_guard',
    'ensure_campo_tecnicos_email_column',
    'ensure_campo_tecnicos_sync_columns',
    'perfil_eh_campo',
    'campo_tecnico_row_para_usuario',
    'is_mobile_request',
    'usuario_eh_campo_operacional',
    'campo_token_para_usuario',
    'sincronizar_usuario_campo',
    'sincronizar_tecnico_usuario',
    'campo_numero_visivel',
    'campo_tecnico_for_os_row',
    'campo_flag_atrasada_existente',
    'campo_status_finalizado',
    'campo_status_pausado',
    'campo_status_em_andamento',
    'campo_os_iniciada',
    'campo_os_atrasada',
    '_campo_parse_date',
    '_campo_valid_files',
    '_campo_save_images',
    'get_tecnico_from_token',
)

ROUTE_PATHS = (
    '/push/vapid-public-key',
    '/push/subscribe',
    '/push/unsubscribe',
    '/push/test',
    '/sw.js',
    '/api/campo/feed-state',
    '/api/campo/eventos',
    '/api/campo/eventos/teste',
    '/gestor/app',
    '/api/mobile/pagamentos/save',
    '/api/mobile/combustivel/save',
    '/api/mobile/bomba/save',
    '/campo',
    '/campo/tecnico/save',
    '/campo/tecnico/revogar/<int:rid>',
    '/campo/tecnico/delete/<int:rid>',
    '/campo/templates/save',
    '/c/<token>',
    '/campo/app/',
    '/campo/app/<path:token>',
    '/campo/whatsapp/<int:rid>',
    '/campo/whatsapp/equipe/<int:rid>',
    '/os/<int:rid>/campo/<token>',
    '/api/campo/localizacao',
    '/api/campo/gps-debug',
    '/api/campo/tecnicos-mapa',
    '/api/campo/tecnico/foto',
)

ROUTE_HELPERS = ('api_campo_evento_visto',)

LEGACY_HELPERS = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)


def br_now():
    return _legacy('br_now')()


def parse_br_date(raw):
    return _legacy('parse_br_date')(raw)


def parse_num(s, default=0.0):
    return _legacy('parse_num')(s, default)


def row_to_dict(row):
    return _legacy('row_to_dict')(row)


def row_get_value(row, key, default=None):
    return _legacy('row_get_value')(row, key, default)


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


def list_page(table, order='id DESC', limit=120):
    return _legacy('list_page')(table, order, limit)


def fetch_sistemas_map():
    return _legacy('fetch_sistemas_map')()


def user_has(perm):
    return _legacy('user_has')(perm)


def owned_by_current_company(table, rid):
    return _legacy('owned_by_current_company')(table, rid)


def normalize_phone(raw):
    return _legacy('normalize_phone')(raw)


def format_phone_br(raw):
    return _legacy('format_phone_br')(raw)


def payment_status_is_paid(value):
    return _legacy('payment_status_is_paid')(value)


def _safe_int_id(value):
    return _legacy('_safe_int_id')(value)


def backup_company_data(empresa_id=None):
    return _legacy('backup_company_data')(empresa_id=empresa_id)


def current_company_id():
    from app.auth import current_company_id as fn
    return fn()


def current_company():
    from app.auth import current_company as fn
    return fn()


def current_user_is_super_admin(user=None):
    from app.auth import current_user_is_super_admin as fn
    return fn(user)


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


def get_conn():
    from app.db import get_conn as fn
    return fn()


def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)


def table_columns(table):
    from app.db import table_columns as fn
    return fn(table)


def select_existing_columns(table, desired, fallback='id'):
    from app.db.schema import select_existing_columns as fn
    return fn(table, desired, fallback=fallback)


def ensure_db():
    from app.db import ensure_db as fn
    return fn()


def tenant_upload_dir(kind, empresa_id=None):
    from app.storage import tenant_upload_dir as fn
    return fn(kind, empresa_id=empresa_id)


def company_folder_name(empresa_id=None):
    from app.storage import company_folder_name as fn
    return fn(empresa_id)


def ensure_company_storage(empresa_id=None):
    from app.storage import ensure_company_storage as fn
    return fn(empresa_id)


def load_whatsapp_templates(empresa_id=None):
    from app.storage import load_whatsapp_templates as fn
    return fn(empresa_id)


def save_whatsapp_templates(items, empresa_id=None):
    from app.storage import save_whatsapp_templates as fn
    return fn(items, empresa_id=empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)
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
        if re.match(r'^[A-Z_][A-Z0-9_]*\s*=', line) and not line.startswith('TOKEN_'):
            end = i
            break
        if line.startswith('from app.') or line.startswith('app = create_app'):
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


def grab_token_constants(lines):
    out = []
    for i, line in enumerate(lines):
        if line.startswith('TOKEN_EXPIRY_DAYS'):
            out.append(line)
            break
    return ''.join(out)


def assert_safe_delete(text, label):
    for snippet in DELETE_PROTECTED:
        if snippet in text:
            raise RuntimeError(f'{label} contains protected snippet {snippet!r}')


GET_TECNICO_FROM_TOKEN = '''

def get_tecnico_from_token():
    """Identifica técnico de campo pelo token enviado no header ou query."""
    payload = request.get_json(silent=True) or {}
    token = (
        request.headers.get('X-Tecnico-Token')
        or request.args.get('tecnico_token')
        or payload.get('tecnico_token')
        or ''
    ).strip().strip('/')
    if not token:
        auth = request.headers.get('Authorization', '')
        if auth.lower().startswith('bearer '):
            token = auth[7:].strip()
    if not token:
        return {}
    return campo_tecnico_por_token(token)
'''


def build_services(lines):
    parts = [
        LEGACY_HELPERS.strip(),
        '\n\nimport hashlib\nimport hmac\nimport json\nimport os\nimport re\nimport uuid\nimport urllib.parse as urllib_parse\n',
        'from datetime import timedelta\n\n',
        'from flask import request, session, url_for\n',
        'from werkzeug.security import generate_password_hash\nfrom werkzeug.utils import secure_filename\n\n',
        'from app.db import USE_POSTGRES, ensure_column\n',
        'from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE\n',
        'from app.os.services import os_is_overdue, prepare_os_row_for_template\n',
        'from app.storage import active_whatsapp_template\n\n',
        'def _flask_app():\n    from app import legacy\n    return legacy.app\n\n',
        grab_token_constants(lines),
        '\n',
    ]
    for name in TOKEN_FUNCS + PUSH_FUNCS + SERVICE_FUNCS:
        if name == 'get_tecnico_from_token':
            parts.append(GET_TECNICO_FROM_TOKEN)
            continue
        try:
            body, _, _ = grab_def(lines, name)
            parts.append('\n\n' + body)
        except ValueError:
            pass
    text = '"""Regras de negócio Campo / PWA / Push."""\n' + ''.join(parts)
    text = text.replace('str(app.secret_key', '_flask_app().secret_key')
    text = text.replace('app.logger', '_flask_app().logger')
    text = text.replace('app.static_folder', '_flask_app().static_folder')
    (CAMPO / 'services.py').write_text(text, encoding='utf-8')


def build_push(lines):
    const_block = []
    for line in lines:
        if line.startswith('VAPID_'):
            const_block.append(line)
    routes_body = ''
    for path in ('/push/vapid-public-key', '/push/subscribe', '/push/unsubscribe', '/push/test', '/sw.js'):
        block, _, _ = find_route_block(lines, path)
        routes_body += strip_route_decorators(block) + '\n\n'
    for name in PUSH_FUNCS:
        body, _, _ = grab_def(lines, name)
        routes_body = body + '\n\n' + routes_body
    header = '''"""Web Push — VAPID, subscriptions e service worker."""
import json
import os

from flask import Response, jsonify, request, session

from app.auth.decorators import require_permission

'''
    footer = '''

def register_push_routes(app):
    rules = [
        ('/push/vapid-public-key', 'push_vapid_public_key', push_vapid_public_key, ['GET']),
        ('/push/subscribe', 'push_subscribe', push_subscribe, ['POST']),
        ('/push/unsubscribe', 'push_unsubscribe', push_unsubscribe, ['POST']),
        ('/push/test', 'push_test', require_permission('manage_users')(push_test), ['POST']),
        ('/sw.js', 'service_worker', service_worker, ['GET']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    content = header + ''.join(const_block) + '\n' + LEGACY_HELPERS + routes_body + footer
    (CAMPO / 'push.py').write_text(content, encoding='utf-8')


def build_routes(lines):
    route_body = ''
    skip = {'/push/vapid-public-key', '/push/subscribe', '/push/unsubscribe', '/push/test', '/sw.js'}
    for path in ROUTE_PATHS:
        if path in skip:
            continue
        block, _, _ = find_route_block(lines, path)
        route_body += strip_route_decorators(block) + '\n\n'
    for name in ROUTE_HELPERS:
        body, _, _ = grab_def(lines, name)
        route_body += body + '\n\n'

    perm_map = {
        'campo_page': 'view_os',
        'campo_tecnico_save': 'manage_users',
        'campo_tecnico_revogar_token': 'manage_users',
        'campo_tecnico_delete': 'manage_users',
        'campo_template_save': 'manage_users',
        'campo_whatsapp': 'view_os',
        'campo_whatsapp_equipe': 'view_os',
        'api_mobile_pag_save': 'edit_pagamentos',
        'api_mobile_comb_save': 'edit_combustivel',
        'api_mobile_bomba_save': 'edit_controle',
        'api_campo_gps_debug': 'view_os',
        'api_campo_tecnicos_mapa': 'view_os',
    }
    for fn, perm in perm_map.items():
        route_body = route_body.replace(f'def {fn}(', f"@require_permission('{perm}')\ndef {fn}(", 1)

    header = '''"""Rotas Campo / PWA / gestor mobile."""
import hmac
import io
import json
import os
import re
import uuid
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.auth.decorators import require_permission
from app.campo.services import (
    _api_campo_guard,
    _campo_save_images,
    _campo_valid_files,
    _token_expirado,
    _token_renovar,
    _token_revogar,
    campo_evento_registrar,
    campo_link_com_tecnico,
    campo_link_publico,
    campo_mesmo_tecnico,
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_app_link,
    campo_tecnico_for_os_row,
    campo_tecnico_por_token,
    campo_token_for,
    campo_whatsapp_url,
    campo_whatsapp_url_para_tecnico,
    ensure_campo_eventos_table,
    ensure_cambpo_tecnicos_sync_columns,
    ensure_campo_tecnicos_email_column,
    ensure_campo_tecnicos_sync_columns,
    get_tecnico_from_token,
    perfil_eh_campo,
    resumo_curto,
    sincronizar_tecnico_usuario,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)
from app.combustivel.services import save_combustivel
from app.controle.services import save_bomba
from app.os.services import os_is_overdue, prepare_os_row_for_template
from app.pagamentos.services import save_pagamento
from app.storage import (
    company_folder_name,
    ensure_company_storage,
    load_whatsapp_templates,
    save_whatsapp_templates,
    tenant_upload_dir,
    upload_file_to_supabase,
)

'''
    # fix typo in header
    header = header.replace('ensure_cambpo_tecnicos_sync_columns,\n', '')
    register = '''
def _flask_app():
    from app import legacy
    return legacy.app


def register_routes(app):
    from app.auth.decorators import require_permission
    rules = [
        ('/api/campo/feed-state', 'api_campo_feed_state', api_campo_feed_state, ['GET']),
        ('/api/campo/eventos', 'api_campo_eventos', api_campo_eventos, ['GET']),
        ('/api/campo/eventos/<int:eid>/visto', 'api_campo_evento_visto', api_campo_evento_visto, ['POST']),
        ('/api/campo/eventos/teste', 'api_campo_evento_teste', api_campo_evento_teste, ['POST']),
        ('/gestor/app', 'gestor_app', gestor_app, ['GET']),
        ('/api/mobile/pagamentos/save', 'api_mobile_pag_save', api_mobile_pag_save, ['POST']),
        ('/api/mobile/combustivel/save', 'api_mobile_comb_save', api_mobile_comb_save, ['POST']),
        ('/api/mobile/bomba/save', 'api_mobile_bomba_save', api_mobile_bomba_save, ['POST']),
        ('/campo', 'campo_page', campo_page, ['GET']),
        ('/campo/tecnico/save', 'campo_tecnico_save', campo_tecnico_save, ['POST']),
        ('/campo/tecnico/revogar/<int:rid>', 'campo_tecnico_revogar_token', campo_tecnico_revogar_token, ['POST']),
        ('/campo/tecnico/delete/<int:rid>', 'campo_tecnico_delete', campo_tecnico_delete, ['POST']),
        ('/campo/templates/save', 'campo_template_save', campo_template_save, ['POST']),
        ('/c/<token>', 'campo_short_app', campo_short_app, ['GET', 'POST']),
        ('/campo/app/', 'campo_app_empty', campo_app_empty, ['GET', 'POST']),
        ('/campo/app/<path:token>', 'campo_app', campo_app, ['GET', 'POST']),
        ('/campo/whatsapp/<int:rid>', 'campo_whatsapp', campo_whatsapp, ['GET']),
        ('/campo/whatsapp/equipe/<int:rid>', 'campo_whatsapp_equipe', campo_whatsapp_equipe, ['GET']),
        ('/os/<int:rid>/campo/<token>', 'campo_tecnico', campo_tecnico, ['GET', 'POST']),
        ('/api/campo/localizacao', 'api_campo_localizacao', api_campo_localizacao, ['POST']),
        ('/api/campo/gps-debug', 'api_campo_gps_debug', api_campo_gps_debug, ['GET']),
        ('/api/campo/tecnicos-mapa', 'api_campo_tecnicos_mapa', api_campo_tecnicos_mapa, ['GET']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto', api_campo_tecnico_foto, ['POST']),
        ('/api/campo/tecnico/foto', 'api_campo_tecnico_foto_delete', api_campo_tecnico_foto_delete, ['DELETE']),
    ]
    for rule, endpoint, view, methods in rules:
        app.add_url_rule(rule, endpoint, view, methods=methods)
'''
    content = header + LEGACY_HELPERS + '\n\n' + route_body.replace('app.logger', '_flask_app().logger').replace('app.static_folder', '_flask_app().static_folder') + register
    (CAMPO / 'routes.py').write_text(content, encoding='utf-8')


def build_init():
    (CAMPO / '__init__.py').write_text(
        '''"""Módulo Campo / PWA."""
from app.campo.push import _ensure_push_subscriptions_table, _send_push, register_push_routes
from app.campo.routes import register_routes
from app.campo.services import (
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_for_os_row,
    campo_tecnico_por_token,
    campo_token_for,
    campo_token_para_usuario,
    is_mobile_request,
    perfil_eh_campo,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)


def register_campo(app):
    register_routes(app)
    register_push_routes(app)


__all__ = [
    'register_campo',
    'campo_token_for',
    'campo_token_para_usuario',
    'sincronizar_usuario_campo',
    'usuario_eh_campo_operacional',
    'is_mobile_request',
    'campo_status_finalizado',
    'campo_os_atrasada',
    'campo_numero_visivel',
    'campo_tecnico_for_os_row',
    '_api_campo_guard',
    '_send_push',
    '_ensure_push_subscriptions_table',
]
''',
        encoding='utf-8',
    )


def remove_orphans(lines):
    """Remove known corrupted fragments from prior extractions."""
    spans = []
    for i, line in enumerate(lines):
        if line.strip() == '"""Redireciona /pagamentos para o hub."""':
            spans.append((i - 1 if i > 0 and not lines[i - 1].strip() else i, i + 2))
        if line.strip().startswith('"""Retorna/cria o token do app mobile'):
            spans.append((i, i + 28))
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]


def remove_from_legacy(lines):
    spans = []
    for i, line in enumerate(lines):
        if line.startswith('TOKEN_EXPIRY_DAYS'):
            spans.append((i, i + 1))
    for name in TOKEN_FUNCS + PUSH_FUNCS + SERVICE_FUNCS:
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
    for i, line in enumerate(lines):
        if line.startswith('VAPID_') or (line.startswith('#') and 'WEB PUSH' in line):
            spans.append((i, i + 1))
    for start, end in sorted(spans, reverse=True):
        block = ''.join(lines[start:end])
        assert_safe_delete(block, f'legacy delete {start + 1}')
        del lines[start:end]


def wire_legacy(text):
    if 'register_campo(app)' in text:
        return text
    block = '''
from app.campo import register_campo
from app.campo.push import _ensure_push_subscriptions_table, _send_push
from app.campo.services import (
    _api_campo_guard,
    campo_numero_visivel,
    campo_os_atrasada,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_status_pausado,
    campo_tecnico_for_os_row,
    campo_tecnico_por_token,
    campo_token_for,
    campo_token_para_usuario,
    is_mobile_request,
    perfil_eh_campo,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)
'''
    if 'from app.campo import register_campo' not in text:
        text = text.replace(
            'from app.os.services import (\n',
            block + 'from app.os.services import (\n',
            1,
        )
    text = text.replace(
        'register_os(app)\n',
        'register_os(app)\nregister_campo(app)\n',
        1,
    )
    return text


def main():
    raw = legacy_path.read_text(encoding='utf-8')
    if 'register_campo(app)' in raw:
        print('Module 11 already applied.')
        return
    lines = raw.splitlines(keepends=True)
    build_services(lines)
    build_push(lines)
    build_routes(lines)
    build_init()
    remove_orphans(lines)
    remove_from_legacy(lines)
    text = wire_legacy(''.join(lines))
    legacy_path.write_text(text, encoding='utf-8')
    print('Module 11 applied. legacy lines:', len(text.splitlines()))


if __name__ == '__main__':
    main()
