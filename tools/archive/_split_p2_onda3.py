"""Script one-shot: divide pdf.py e campo/routes.py (P2 onda 3)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slice_lines(path: Path, start: int, end: int) -> str:
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    return ''.join(lines[start - 1:end])


def write(path: Path, header: str, body: str) -> None:
    path.write_text(header.rstrip() + '\n\n' + body.lstrip('\n'), encoding='utf-8')


def split_pdf() -> None:
    src = ROOT / 'app' / 'os' / 'pdf.py'
    common_header = '''"""Helpers compartilhados do módulo PDF de O.S."""
import os
import threading


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


def _flask_app():
    from app.runtime import flask_app
    return flask_app()


def _bg():
    from app.runtime import BACKGROUND_COMPANY_CONTEXT
    return BACKGROUND_COMPANY_CONTEXT


# PDF PERFORMANCE
_PDF_IMAGE_CACHE = {}
_PDF_IMAGE_CACHE_LOCK = threading.Lock()
_PDF_BYTES_CACHE = {}
_PDF_CACHE_LOCK = threading.Lock()
PDF_CACHE_TTL_SECONDS = int(os.getenv('PDF_CACHE_TTL_SECONDS', '600') or 600)
PDF_IMAGE_TIMEOUT_SECONDS = int(os.getenv('PDF_IMAGE_TIMEOUT_SECONDS', '5') or 5)
PDF_IMAGE_SIZE_PX = int(os.getenv('PDF_IMAGE_SIZE_PX', '200') or 200)
PDF_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MAX_IMAGES_PER_OS', '3') or 3)
PDF_MONTH_MAX_IMAGES_PER_OS = int(os.getenv('PDF_MONTH_MAX_IMAGES_PER_OS', '2') or 2)
PDF_MONTH_MAX_OS = int(os.getenv('PDF_MONTH_MAX_OS', '80') or 80)
PDF_MONTH_BATCH_SIZE = int(os.getenv('PDF_MONTH_BATCH_SIZE', '20') or 20)
'''
    write(ROOT / 'app' / 'os' / 'pdf_common.py', common_header, '')

    support_header = '''"""Formatação, cache, imagens e cabeçalho do PDF de O.S."""
import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

from app.os.pdf_common import (
    PDF_IMAGE_SIZE_PX,
    PDF_IMAGE_TIMEOUT_SECONDS,
    PDF_MAX_IMAGES_PER_OS,
    _PDF_BYTES_CACHE,
    _PDF_CACHE_LOCK,
    _PDF_IMAGE_CACHE,
    _PDF_IMAGE_CACHE_LOCK,
    current_company_id,
)
from app.shared.formatters import parse_br_date
from app.storage import company_folder_name, company_identity_dir, company_identity_file, load_company_identity_config
from app.storage.attachments import read_attachment_bytes_fast, resolve_os_upload_path
from app.storage.paths import BASE_DIR, normalize_storage_path
'''
    write(ROOT / 'app' / 'os' / 'pdf_support.py', support_header, slice_lines(src, 143, 605))

    builder_header = '''"""Montagem do PDF de O.S. (dia/mês) e exportações tabulares."""
import io
import json
import os
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.os.pdf_common import current_company_id, current_company
from app.os.pdf_support import (
    _draw_pdf_header,
    _img_square_rlimage,
    _pdf_clean_row,
    _pdf_collect_hist_dates,
    _pdf_collect_os_image_paths,
    _pdf_datetime_label,
    _pdf_fim_label,
    _pdf_hist_needs_detail_rows,
    _pdf_historico_for_display,
    _pdf_para_text,
    _pdf_safe_text,
    _pdf_time_label,
    _prefetch_os_images_parallel,
)
from app.os.services import attach_os_display_numbers
from app.shared.formatters import elapsed_label, parse_br_date
from app.shared.months import normalize_month_reference
from app.shared.rows import row_get_value, row_matches_month, row_to_dict
from app.storage import company_identity_dir, company_identity_file, load_company_identity_config, sync_os_attachments
from app.os.pdf_common import (
    PDF_CACHE_TTL_SECONDS,
    PDF_MONTH_MAX_OS,
    company_where,
    current_company_id,
    query_all,
    select_existing_columns,
    table_columns,
    _pdf_cache_get,
    _pdf_cache_set,
)
from app.os.pdf_support import _pdf_cache_get as _support_cache_get
'''
    # _pdf_cache_get/set live in pdf_support; re-import for builder monthly buffer
    builder_header = builder_header.replace(
        '    _pdf_cache_get,\n    _pdf_cache_set,\n)',
        ')',
    )
    builder_header += '''
from app.os.pdf_support import _pdf_cache_get, _pdf_cache_set
'''
    builder_body = slice_lines(src, 607, 980) + slice_lines(src, 1069, 1149)
    write(ROOT / 'app' / 'os' / 'pdf_builder.py', builder_header, builder_body)

    jobs_header = '''"""Jobs em background para PDF mensal de O.S."""
import os
import threading
import time

from flask import session

from app.os.pdf_builder import _build_os_pdf_mes_buffer
from app.os.pdf_common import (
    PDF_MONTH_BATCH_SIZE,
    _bg,
    _flask_app,
    company_where,
    current_company_id,
    execute,
    query_one,
)
from app.os.pdf_support import _pdf_safe_text
from app.shared.formatters import br_now
from app.shared.months import normalize_month_reference
from app.shared.rows import row_to_dict
from app.storage import _upload_pdf_bytes_to_supabase
'''
    jobs_body = slice_lines(src, 982, 1067) + slice_lines(src, 1151, 1200)
    write(ROOT / 'app' / 'os' / 'pdf_jobs.py', jobs_header, jobs_body)

    routes_header = '''"""Rotas HTTP do PDF de O.S."""
from datetime import datetime

from flask import flash, jsonify, redirect, request, send_file, session, url_for

from app.auth.decorators import require_permission
from app.os.pdf_builder import _build_os_pdf, _build_os_pdf_mes_buffer
from app.os.pdf_common import (
    PDF_MAX_IMAGES_PER_OS,
    company_where,
    current_company_id,
    current_user_is_super_admin,
    query_all,
    select_existing_columns,
    _flask_app,
)
from app.os.pdf_jobs import (
    _create_pdf_job,
    _render_pdf_job_wait_page,
    _start_pdf_job_thread,
)
from app.os.pdf_support import _pdf_cache_get, _pdf_cache_set
from app.os.services import attach_os_display_numbers
from app.shared.formatters import parse_br_date
from app.shared.rows import row_get_value, row_to_dict
from app.storage import sync_os_attachments
'''
    write(ROOT / 'app' / 'os' / 'pdf_routes.py', routes_header, slice_lines(src, 1204, 1334))

    facade = '''"""PDF de O.S. — facade de compatibilidade (imports legados)."""
from app.os.pdf_builder import _build_os_pdf, _build_os_pdf_mes_buffer, excel_file, table_pdf
from app.os.pdf_common import _pdf_job_now
from app.os.pdf_jobs import _create_pdf_job, _gerar_pdf_mensal_job_worker, _start_pdf_job_thread
from app.os.pdf_routes import register_pdf_routes
from app.os.pdf_support import _draw_pdf_header

__all__ = [
    '_build_os_pdf',
    '_build_os_pdf_mes_buffer',
    '_create_pdf_job',
    '_draw_pdf_header',
    '_gerar_pdf_mensal_job_worker',
    '_pdf_job_now',
    '_start_pdf_job_thread',
    'excel_file',
    'register_pdf_routes',
    'table_pdf',
]
'''
    (ROOT / 'app' / 'os' / 'pdf.py').write_text(facade, encoding='utf-8')


def split_campo_routes() -> None:
    src = ROOT / 'app' / 'campo' / 'routes.py'

    common_header = '''"""Helpers compartilhados das rotas Campo."""
from app.auth import owned_by_current_company, user_has


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
    return fn(kind, empresa_id)


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
    return fn(items, empresa_id)


def active_whatsapp_template(tipo, empresa_id=None):
    from app.storage import active_whatsapp_template as fn
    return fn(tipo, empresa_id)


def upload_file_to_supabase(file_storage, storage_path, content_type=None):
    from app.storage import upload_file_to_supabase as fn
    return fn(file_storage, storage_path, content_type)


def pagamentos_query_rows(*args, **kwargs):
    from app.pagamentos.services import pagamentos_query_rows as fn
    return fn(*args, **kwargs)


def _flask_app():
    from app.runtime import flask_app
    return flask_app()
'''
    write(ROOT / 'app' / 'campo' / 'routes_common.py', common_header, '')

    api_header = '''"""APIs Campo / gestor mobile."""
import json
import os
import uuid

from flask import jsonify, request, session

from app.auth.decorators import require_permission
from app.campo.routes_common import (
    _flask_app,
    company_where,
    current_company_id,
    execute,
    get_current_user,
    query_all,
    query_one,
)
from app.campo.services import (
    _api_campo_guard,
    campo_evento_registrar,
    campo_numero_visivel,
    campo_tecnico_por_token,
    ensure_campo_eventos_table,
)
from app.combustivel.services import save_combustivel
from app.controle.services import save_bomba
from app.pagamentos.services import save_pagamento
from app.shared.cache import clear_view_cache
from app.shared.queries import safe_int_id as _safe_int_id
from app.shared.rows import row_to_dict
'''
    api_body = slice_lines(src, 178, 267) + slice_lines(src, 470, 537) + slice_lines(src, 1092, 1299)
    write(ROOT / 'app' / 'campo' / 'routes_api.py', api_header, api_body)

    pages_header = '''"""Páginas Campo / PWA / WhatsApp."""
import json
import os
import re
import uuid
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from app.auth.decorators import require_permission
from app.campo.routes_common import (
    _flask_app,
    active_whatsapp_template,
    company_and,
    company_folder_name,
    company_where,
    current_company,
    current_company_id,
    current_user_is_super_admin,
    ensure_company_storage,
    ensure_db,
    execute,
    get_current_user,
    load_whatsapp_templates,
    pagamentos_query_rows,
    query_all,
    query_one,
    save_whatsapp_templates,
    select_existing_columns,
    table_columns,
    table_has_column,
    tenant_upload_dir,
    upload_file_to_supabase,
)
from app.campo.services import (
    _token_expirado,
    _token_renovar,
    _token_revogar,
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
    campo_token_para_usuario,
    campo_whatsapp_url,
    campo_whatsapp_url_para_tecnico,
    ensure_campo_eventos_table,
    ensure_campo_tecnicos_email_column,
    ensure_campo_tecnicos_sync_columns,
    get_tecnico_from_token,
    perfil_eh_campo,
    resumo_curto,
    sincronizar_tecnico_usuario,
    sincronizar_usuario_campo,
    usuario_eh_campo_operacional,
)
from app.os.services import os_is_overdue, prepare_os_row_for_template
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, elapsed_label, format_phone_br, normalize_phone, now_str, only_time_str, parse_br_date, parse_num, time_diff_minutes
from app.shared.payments import payment_status_is_paid
from app.shared.queries import fetch_sistemas_map, list_page
from app.shared.rows import row_get_value, row_to_dict
from app.storage import backup_company_data
'''
    pages_body = slice_lines(src, 268, 469) + slice_lines(src, 539, 875)
    write(ROOT / 'app' / 'campo' / 'routes_pages.py', pages_header, pages_body)

    tecnico_header = '''"""Rota do técnico em campo (/os/<id>/campo/<token>)."""
import hmac
import json

from flask import render_template, request

from app.campo.routes_common import execute, query_one
from app.campo.services import (
    _campo_save_images,
    _campo_valid_files,
    campo_mesmo_tecnico,
    campo_numero_visivel,
    campo_os_iniciada,
    campo_status_finalizado,
    campo_tecnico_por_token,
    campo_token_for,
    prepare_os_row_for_template,
)
from app.os.services import prepare_os_row_for_template
from app.shared.rows import row_to_dict
'''
    # fix duplicate import in tecnico_header - prepare_os_row only from os.services
    tecnico_header = tecnico_header.replace(
        '    prepare_os_row_for_template,\n)\nfrom app.os.services import prepare_os_row_for_template\n',
        ')\nfrom app.os.services import prepare_os_row_for_template\n',
    )
    write(ROOT / 'app' / 'campo' / 'routes_tecnico.py', tecnico_header, slice_lines(src, 877, 1087))

    register = '''"""Registro das rotas Campo."""
from app.campo.routes_api import (
    api_campo_evento_teste,
    api_campo_evento_visto,
    api_campo_eventos,
    api_campo_feed_state,
    api_campo_gps_debug,
    api_campo_localizacao,
    api_campo_tecnico_foto,
    api_campo_tecnico_foto_delete,
    api_campo_tecnicos_mapa,
    api_mobile_bomba_save,
    api_mobile_comb_save,
    api_mobile_pag_save,
)
from app.campo.routes_pages import (
    campo_app,
    campo_app_empty,
    campo_page,
    campo_short_app,
    campo_template_save,
    campo_tecnico_delete,
    campo_tecnico_revogar_token,
    campo_tecnico_save,
    campo_whatsapp,
    campo_whatsapp_equipe,
    gestor_app,
)
from app.campo.routes_tecnico import campo_tecnico


def register_routes(app):
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
    (ROOT / 'app' / 'campo' / 'routes.py').write_text(register, encoding='utf-8')


def main() -> None:
    split_pdf()
    split_campo_routes()
    print('split ok')


if __name__ == '__main__':
    main()
