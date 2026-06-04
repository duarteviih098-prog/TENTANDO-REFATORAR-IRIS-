"""Caminhos locais, normalização e URLs públicas."""
import os
import re
from pathlib import Path
from urllib import parse as urllib_parse
from app.db.schema import select_existing_columns
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, now_str
from app.shared.rows import row_to_dict

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

def current_company_id():
    from app.auth import current_company_id as fn
    return fn()

def storage_kind_folder(kind=''):
    kind = str(kind or '').strip().lower().replace('\\', '/').strip('/')
    if kind in ('pagamento', 'pagamentos', 'nf', 'boleto', 'boletos', 'anexos_nf', 'anexos_boleto', 'anexos_orcamento', 'orcamento', 'orcamentos'):
        return PAYMENT_STORAGE_FOLDER
    if kind in ('os', 'o.s', 'ordem_servico', 'ordem-de-servico', 'imagens', 'foto_os', 'arquivo_os'):
        return OS_STORAGE_FOLDER
    return kind or ''

def normalize_storage_path(path, kind='', empresa_id=None):
    """Normaliza qualquer caminho antigo/local para o caminho dentro do bucket.

    Rotas oficiais:
    - O.S.: empresas/<empresa>/os/<arquivo>
    - NF/Boleto/Pagamento: empresas/<empresa>/BOLETO E NF/<arquivo>

    Também corrige URLs públicas antigas do Supabase, em vez de devolvê-las
    cegamente e deixar o navegador cair no 404.
    """
    raw = str(path or '').strip().replace('\\', '/')
    if not raw:
        return ''

    if raw.startswith(('http://', 'https://')):
        marker_public = f"/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/"
        marker_private = f"/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/"
        if marker_public in raw:
            raw = raw.split(marker_public, 1)[1]
        elif marker_private in raw:
            raw = raw.split(marker_private, 1)[1]
        else:
            # URL externa: mantém como está.
            return raw
        raw = urllib_parse.unquote(raw)

    raw = raw.lstrip('/')
    if raw.startswith('static/uploads/'):
        raw = raw.replace('static/uploads/', '', 1)
    if raw.startswith(f'{SUPABASE_STORAGE_BUCKET}/'):
        raw = raw.replace(f'{SUPABASE_STORAGE_BUCKET}/', '', 1)

    # Se já veio com a empresa, não muda a pasta. Isso preserva arquivos antigos
    # que talvez ainda estejam em empresas/<empresa>/pagamentos/<arquivo>.
    if 'empresas/' in raw:
        return raw[raw.index('empresas/'):].strip('/')

    folder_name = storage_kind_folder(kind)
    legacy_roots = (
        'os/', 'pagamentos/', 'pagamento/', 'nf/', 'boleto/', 'boletos/',
        'BOLETO E NF/', 'identidade/', 'backups/', 'documentos/', 'exports/',
        'whatsapp_templates/'
    )

    try:
        company_folder = company_folder_name(empresa_id)
    except Exception:
        company_folder = 'empresa'

    lower_raw = raw.lower()

    # Corrige caminhos antigos sem empresa: os/foto.jpg -> empresas/<empresa>/os/foto.jpg
    if lower_raw.startswith('os/'):
        return f'empresas/{company_folder}/{OS_STORAGE_FOLDER}/{raw.split("/", 1)[1]}'.strip('/')

    # Corrige caminhos antigos de pagamento sem empresa para a pasta única nova.
    if lower_raw.startswith(('pagamentos/', 'pagamento/', 'nf/', 'boleto/', 'boletos/', 'boleto e nf/')):
        filename = Path(raw).name
        return f'empresas/{company_folder}/{PAYMENT_STORAGE_FOLDER}/{filename}'.strip('/')

    # Outras pastas técnicas antigas continuam com a própria raiz.
    if raw.startswith(legacy_roots):
        return f'empresas/{company_folder}/{raw}'.strip('/')

    if folder_name:
        return f'empresas/{company_folder}/{folder_name}/{Path(raw).name}'.strip('/')

    # Fotos do campo e da O.S. sem pasta — adiciona empresa + pasta correta
    lower_name = Path(raw).name.lower()
    if lower_name.startswith('campo_') or lower_name.startswith('foto_os_'):
        return f'empresas/{company_folder}/{OS_STORAGE_FOLDER}/{Path(raw).name}'.strip('/')

    return raw.strip('/')

def get_file_url(path, kind='', empresa_id=None):
    storage_path = normalize_storage_path(
        path,
        kind=kind,
        empresa_id=empresa_id
    )

    if storage_path.startswith(('http://', 'https://')):
        return storage_path

    quoted = urllib_parse.quote(storage_path, safe='/._-~')
    # Bucket público — sempre URL pública, sem autenticação
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{quoted}"
def slugify_company_name(value):
    txt = str(value or '').strip().lower()
    replacements = {'á':'a','à':'a','â':'a','ã':'a','ä':'a','é':'e','è':'e','ê':'e','ë':'e','í':'i','ì':'i','î':'i','ï':'i','ó':'o','ò':'o','ô':'o','õ':'o','ö':'o','ú':'u','ù':'u','û':'u','ü':'u','ç':'c'}
    for a,b in replacements.items():
        txt = txt.replace(a,b)
    txt = re.sub(r'[^a-z0-9]+', '_', txt).strip('_')
    return txt or 'empresa'


def company_folder_name(empresa_id=None):
    try:
        empresa_id = int(empresa_id or current_company_id() or 0)
    except Exception:
        empresa_id = 0
    row = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (empresa_id,))) if empresa_id else None
    base = slugify_company_name((row or {}).get('nome') or f'empresa_{empresa_id or "sem_empresa"}')
    return f'{empresa_id}_{base}' if empresa_id else base


def tenant_upload_dir(kind, empresa_id=None):
    folder = TENANT_UPLOAD_ROOT / company_folder_name(empresa_id) / str(kind or 'arquivos')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def company_identity_dir(empresa_id=None):
    return tenant_upload_dir('identidade', empresa_id)


def company_identity_config_path(empresa_id=None):
    return company_identity_dir(empresa_id) / 'config.json'
def resolve_local_path(raw_path):
    raw = str(raw_path or '').strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    cleaned = raw.lstrip('/\\')
    if cleaned.startswith('static/'):
        return BASE_DIR / cleaned
    if cleaned.startswith('uploads/empresas/'):
        return BASE_DIR / 'static' / cleaned
    if cleaned.startswith('empresas/'):
        return BASE_DIR / 'static' / 'uploads' / cleaned
    return BASE_DIR / cleaned

def resolve_os_upload_path(stored):
    raw = str(stored or '').strip().replace('\\', '/').lstrip('/')
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    try:
        p = p.resolve()
        legacy_root = UPLOAD_OS.resolve()
        tenant_root = TENANT_UPLOAD_ROOT.resolve()
        if not ((legacy_root in p.parents or p == legacy_root) or (tenant_root in p.parents or p == tenant_root)):
            return None
    except Exception:
        return None
    return p
