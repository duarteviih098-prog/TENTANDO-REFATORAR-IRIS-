"""Apply Module 4 storage/uploads extraction on current legacy."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
legacy_path = ROOT / 'app' / 'legacy.py'
lines = legacy_path.read_text(encoding='utf-8').splitlines(keepends=True)
STORAGE = ROOT / 'app' / 'storage'
STORAGE.mkdir(exist_ok=True)


def grab(start, end):
    return ''.join(lines[start - 1:end])


def strip_routes(text):
    return re.sub(r'^@app\.route\([^\n]+\)\n', '', text, flags=re.M)


def strip_context(text):
    return re.sub(r'^@app\.context_processor\ndef inject_storage_helpers\(\):\n', 'def inject_storage_helpers():\n', text, flags=re.M)


LEGACY = '''
def _legacy(name):
    from app import legacy
    return getattr(legacy, name)

def row_to_dict(row):
    return _legacy('row_to_dict')(row)

def query_one(sql, params=()):
    from app.db import query_one as db_query_one
    return db_query_one(sql, params)

def query_all(sql, params=()):
    from app.db import query_all as db_query_all
    return db_query_all(sql, params)

def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

def now_str():
    return _legacy('now_str')()

def clear_view_cache(prefix=None):
    return _legacy('clear_view_cache')(prefix)

def select_existing_columns(table, desired, fallback='id'):
    return _legacy('select_existing_columns')(table, desired, fallback)

def ensure_company_pdf_columns():
    return _legacy('ensure_company_pdf_columns')()

def table_has_column(table, column):
    from app.db import table_has_column as fn
    return fn(table, column)

def br_now():
    return _legacy('br_now')()

'''

(STORAGE / 'settings.py').write_text(
    '''"""Configuração Supabase Storage e pastas oficiais."""
import os

'''
    + grab(62, 75),
    encoding='utf-8',
)

paths_body = grab(77, 171) + grab(311, 335) + grab(344, 349) + grab(879, 894) + grab(3529, 3544)
(STORAGE / 'paths.py').write_text(
    '''"""Caminhos locais, normalização e URLs públicas."""
import os
import re
from pathlib import Path
from urllib import parse as urllib_parse

from app.config import PROJECT_ROOT
from app.db import query_one
from app.storage import settings

BASE_DIR = PROJECT_ROOT
UPLOAD_OS = BASE_DIR / 'static' / 'uploads' / 'os'
UPLOAD_PAG = BASE_DIR / 'static' / 'uploads' / 'pagamentos'
UPLOAD_OS.mkdir(parents=True, exist_ok=True)
UPLOAD_PAG.mkdir(parents=True, exist_ok=True)
TENANT_UPLOAD_ROOT = BASE_DIR / 'static' / 'uploads' / 'empresas'
TENANT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET
PAYMENT_STORAGE_FOLDER = settings.PAYMENT_STORAGE_FOLDER
OS_STORAGE_FOLDER = settings.OS_STORAGE_FOLDER

'''
    + LEGACY
    + '''

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

'''
    + paths_body,
    encoding='utf-8',
)

(STORAGE / 'supabase.py').write_text(
    '''"""Upload e headers Supabase Storage."""
import mimetypes
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request

from app.storage import settings
from app.storage.paths import normalize_storage_path

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET
SUPABASE_STORAGE_KEY = settings.SUPABASE_STORAGE_KEY

'''
    + grab(173, 227),
    encoding='utf-8',
)

attachments_read = grab(229, 256)
attachments_read += grab(258, 270)
attachments_read = attachments_read.replace('resolve_local_path', 'resolve_local_path').replace(
    'from flask import',
    'from flask import',
)
payment_block = grab(857, 987)
os_block = grab(3505, 3673)
fast_block = (
    '_PDF_IMAGE_CACHE = {}\n'
    '_PDF_IMAGE_CACHE_LOCK = threading.Lock()\n'
    'PDF_IMAGE_TIMEOUT_SECONDS = int(os.getenv(\'PDF_IMAGE_TIMEOUT_SECONDS\', \'5\') or 5)\n\n'
    + grab(10633, 10720)
)
(STORAGE / 'attachments.py').write_text(
    '''"""Leitura, persistência e entrega de anexos."""
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request

from flask import redirect, send_file
from werkzeug.utils import secure_filename

from app.storage import settings
from app.storage.paths import (
    BASE_DIR,
    PAYMENT_STORAGE_FOLDER,
    TENANT_UPLOAD_ROOT,
    UPLOAD_OS,
    company_folder_name,
    get_file_url,
    normalize_storage_path,
    resolve_local_path,
    tenant_upload_dir,
)
from app.storage.supabase import upload_file_to_supabase

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET

'''
    + LEGACY
    + '''

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

'''
    + attachments_read
    + '\n\n'
    + payment_block
    + '\n\n'
    + os_block
    + '\n\n'
    + fast_block,
    encoding='utf-8',
)

(STORAGE / 'company.py').write_text(
    '''"""Identidade da empresa, templates WhatsApp e backup local."""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from app.auth.constants import TENANT_TABLES
from app.storage.paths import (
    company_identity_config_path,
    company_identity_dir,
    tenant_upload_dir,
)

'''
    + LEGACY
    + '''

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

_last_backup_by_company = {}
_backup_lock = threading.Lock()

'''
    + grab(336, 349)
    + grab(388, 561)
    + grab(563, 603),
    encoding='utf-8',
)

pdf_block = grab(11405, 11512)
(STORAGE / 'pdf.py').write_text(
    '''"""Upload de PDFs prontos para Supabase/local."""
import io
import os
import time
from pathlib import Path
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request

from app.storage import settings
from app.storage.paths import BASE_DIR, get_file_url, normalize_storage_path
from app.storage.supabase import _storage_headers, upload_file_to_supabase

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET
SUPABASE_STORAGE_KEY = settings.SUPABASE_STORAGE_KEY

'''
    + LEGACY
    + '''

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

'''
    + pdf_block,
    encoding='utf-8',
)

routes_body = '''def os_image_public_url(rid, idx, token=None):
    token_str = str(token or '')
    encoded = urllib_parse.quote(token_str, safe='')
    qs = f'?token={encoded}' if token else ''
    return f'/os/imagem/{int(rid)}/{int(idx)}{qs}'


''' + strip_context(strip_routes(grab(1128, 1143)))
(STORAGE / 'routes.py').write_text(
    '''"""Rotas de arquivos de empresa e helpers de template."""
from urllib import parse as urllib_parse

from flask import redirect

from app.storage.paths import get_file_url, normalize_storage_path

'''
    + routes_body
    + '''

def register_routes(app):
    app.context_processor(inject_storage_helpers)
    app.add_url_rule('/empresas/<path:storage_path>', 'supabase_empresa_file', supabase_empresa_file)
    app.add_url_rule('/uploads/empresas/<path:storage_path>', 'supabase_uploads_empresa_file', supabase_uploads_empresa_file)
''',
    encoding='utf-8',
)

(STORAGE / '__init__.py').write_text(
    '''"""Storage local e Supabase (uploads, anexos, identidade)."""
from app.storage.attachments import (
    ATTACHMENT_GROUPS,
    missing_attachment_response,
    normalize_os_attachment_list,
    normalize_payment_attachment_list,
    persist_os_attachment,
    persist_payment_attachment,
    read_attachment_bytes,
    read_attachment_bytes_fast,
    save_os_files,
    storage_or_local_response,
    sync_os_attachments,
    sync_payment_attachments,
)
from app.storage.company import (
    active_whatsapp_template,
    backup_company_data,
    company_identity_file,
    ensure_company_storage,
    load_company_identity_config,
    load_whatsapp_templates,
    save_company_identity_config,
    save_company_identity_file,
    save_whatsapp_templates,
    whatsapp_templates_path,
)
from app.storage.paths import (
    BASE_DIR,
    OS_STORAGE_FOLDER,
    PAYMENT_STORAGE_FOLDER,
    TENANT_UPLOAD_ROOT,
    UPLOAD_OS,
    UPLOAD_PAG,
    company_folder_name,
    company_identity_config_path,
    company_identity_dir,
    get_file_url,
    normalize_storage_path,
    resolve_local_path,
    resolve_os_upload_path,
    slugify_company_name,
    storage_kind_folder,
    tenant_upload_dir,
)
from app.storage.pdf import _save_pdf_bytes_locally, _upload_pdf_bytes_to_supabase
from app.storage.routes import register_routes
from app.storage.settings import (
    OS_STORAGE_FOLDER as SETTINGS_OS_FOLDER,
    PAYMENT_STORAGE_FOLDER as SETTINGS_PAYMENT_FOLDER,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_STORAGE_KEY,
    SUPABASE_URL,
)
from app.storage.supabase import upload_file_to_supabase


def register_storage(app):
    register_routes(app)


__all__ = [
    'register_storage',
    'SUPABASE_URL', 'SUPABASE_STORAGE_BUCKET', 'SUPABASE_STORAGE_KEY',
    'PAYMENT_STORAGE_FOLDER', 'OS_STORAGE_FOLDER',
    'BASE_DIR', 'UPLOAD_OS', 'UPLOAD_PAG', 'TENANT_UPLOAD_ROOT',
    'storage_kind_folder', 'normalize_storage_path', 'get_file_url',
    'upload_file_to_supabase', 'read_attachment_bytes', 'read_attachment_bytes_fast',
    'storage_or_local_response', 'resolve_local_path', 'resolve_os_upload_path',
    'slugify_company_name', 'company_folder_name', 'tenant_upload_dir',
    'ensure_company_storage', 'company_identity_dir', 'company_identity_config_path',
    'load_company_identity_config', 'save_company_identity_config',
    'company_identity_file', 'save_company_identity_file',
    'whatsapp_templates_path', 'load_whatsapp_templates', 'save_whatsapp_templates',
    'active_whatsapp_template', 'backup_company_data',
    'ATTACHMENT_GROUPS', 'payment_storage_kind', 'persist_payment_attachment',
    'normalize_payment_attachment_list', 'sync_payment_attachments', 'missing_attachment_response',
    '_payment_attachment_relpath', 'save_os_files', '_os_attachment_relpath',
    'persist_os_attachment', 'normalize_os_attachment_list', 'sync_os_attachments',
    '_save_pdf_bytes_locally', '_upload_pdf_bytes_to_supabase',
]
''',
    encoding='utf-8',
)

for start, end in [
    (11512, 11405),
    (10734, 10722),
    (10720, 10633),
    (3673, 3505),
    (1143, 1128),
    (987, 857),
    (603, 563),
    (561, 388),
    (349, 311),
    (308, 301),
    (271, 62),
]:
    del lines[end - 1:start]

legacy_new = ''.join(lines)

storage_import = '''
from app.storage import (
    ATTACHMENT_GROUPS,
    OS_STORAGE_FOLDER,
    PAYMENT_STORAGE_FOLDER,
    SUPABASE_STORAGE_BUCKET,
    SUPABASE_STORAGE_KEY,
    SUPABASE_URL,
    TENANT_UPLOAD_ROOT,
    UPLOAD_OS,
    UPLOAD_PAG,
    _os_attachment_relpath,
    _payment_attachment_relpath,
    _save_pdf_bytes_locally,
    _upload_pdf_bytes_to_supabase,
    active_whatsapp_template,
    backup_company_data,
    company_folder_name,
    company_identity_config_path,
    company_identity_dir,
    company_identity_file,
    ensure_company_storage,
    get_file_url,
    load_company_identity_config,
    load_whatsapp_templates,
    missing_attachment_response,
    normalize_os_attachment_list,
    normalize_payment_attachment_list,
    normalize_storage_path,
    payment_storage_kind,
    persist_os_attachment,
    persist_payment_attachment,
    read_attachment_bytes,
    read_attachment_bytes_fast,
    register_storage,
    resolve_local_path,
    resolve_os_upload_path,
    save_company_identity_config,
    save_company_identity_file,
    save_os_files,
    save_whatsapp_templates,
    slugify_company_name,
    storage_kind_folder,
    storage_or_local_response,
    sync_os_attachments,
    sync_payment_attachments,
    tenant_upload_dir,
    upload_file_to_supabase,
    whatsapp_templates_path,
)
'''

legacy_new = re.sub(
    r'\nfrom app\.storage import \([\s\S]*?\)\n',
    '\n',
    legacy_new,
    count=1,
)
legacy_new = re.sub(r'\nregister_storage\(app\)\n', '\n', legacy_new, count=1)

if 'register_storage(app)' not in legacy_new:
    legacy_new = legacy_new.replace(
        'register_auth(app)\n',
        'register_auth(app)\nregister_storage(app)\n',
        1,
    )

legacy_new = legacy_new.replace(
    'from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE\n',
    'from app.db.schema import _TABLE_COLUMN_CACHE, _TABLE_COLUMNS_CACHE\n' + storage_import + '\n',
    1,
)

legacy_new = legacy_new.replace('_last_backup_by_company = {}\n_backup_lock = threading.Lock()\n\n', '')

legacy_path.write_text(legacy_new, encoding='utf-8')
print('legacy lines:', len(legacy_new.splitlines()))
