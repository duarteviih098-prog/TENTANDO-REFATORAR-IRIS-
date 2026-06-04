"""Upload de PDFs prontos para Supabase/local."""
import io
import os
import time
from pathlib import Path
from urllib import error as urllib_error, parse as urllib_parse, request as urllib_request
from app.db.schema import select_existing_columns
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, now_str
from app.shared.rows import row_to_dict

from app.storage import settings
from app.storage.paths import BASE_DIR, get_file_url, normalize_storage_path
from app.storage.supabase import _storage_headers, upload_file_to_supabase

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET
SUPABASE_STORAGE_KEY = settings.SUPABASE_STORAGE_KEY


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



def _public_base_url():
    """Base URL pública para fallback local quando Supabase Storage falhar."""
    try:
        if has_request_context():
            return request.url_root.rstrip('/')
    except Exception:
        pass
    return (
        os.getenv('PUBLIC_BASE_URL')
        or os.getenv('RENDER_EXTERNAL_URL')
        or os.getenv('APP_URL')
        or ''
    ).rstrip('/')


def _save_pdf_bytes_locally(pdf_bytes, storage_path):
    """Fallback de emergência: salva PDF em /static/uploads para não perder o job.

    No Render Free o disco é efêmero, mas isso evita erro imediato quando o problema
    é só upload no Supabase. O caminho fica registrado em storage_path/arquivo_url.
    """
    safe_rel = normalize_storage_path(storage_path, kind='exports', empresa_id=current_company_id()).strip('/')
    if not safe_rel.lower().endswith('.pdf'):
        safe_rel += '.pdf'
    local_rel = f'static/uploads/{safe_rel}'
    local_path = BASE_DIR / local_rel
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(pdf_bytes)

    base = _public_base_url()
    url_path = '/' + local_rel.replace('\\', '/').replace(' ', '%20')
    return (base + url_path) if base else url_path


def _upload_pdf_bytes_to_supabase(pdf_bytes, storage_path):
    """Salva PDF pronto no Supabase Storage e devolve URL pública.

    Melhorias:
    - não falha por ponteiro de BytesIO no final;
    - tenta upload direto e depois fallback pelo helper antigo;
    - registra erro HTTP com corpo;
    - se Supabase falhar, salva fallback local e NÃO derruba o job.
    """
    if hasattr(pdf_bytes, 'getvalue'):
        pdf_bytes = pdf_bytes.getvalue()
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise RuntimeError('PDF inválido: conteúdo não está em bytes.')
    pdf_bytes = bytes(pdf_bytes)
    if not pdf_bytes:
        raise RuntimeError('PDF vazio, nada para enviar.')

    storage_path = normalize_storage_path(storage_path, kind='exports', empresa_id=current_company_id()).strip('/')
    if not storage_path.lower().endswith('.pdf'):
        storage_path += '.pdf'

    if not SUPABASE_STORAGE_KEY:
        fallback_url = _save_pdf_bytes_locally(pdf_bytes, storage_path)
        print('PDF salvo em fallback local: SUPABASE_SERVICE_ROLE_KEY ausente.', fallback_url)
        return fallback_url

    content_type = 'application/pdf'
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{urllib_parse.quote(storage_path, safe='/._-~')}"
    headers = _storage_headers(content_type)

    last_error = ''
    for attempt in range(1, 4):
        try:
            req = urllib_request.Request(url, data=pdf_bytes, headers=headers, method='POST')
            with urllib_request.urlopen(req, timeout=120) as resp:
                if 200 <= int(getattr(resp, 'status', 200)) < 300:
                    return get_file_url(storage_path)
                last_error = f'status inesperado {getattr(resp, "status", None)}'
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8', errors='replace')[:1600]
            except Exception:
                body = ''
            last_error = f'HTTP {exc.code}: {body}'
            print(f'Tentativa {attempt}/3 upload PDF falhou em {storage_path}: {last_error}')
            # 400/401/403 geralmente é configuração/caminho/chave; repetir não ajuda muito.
            if exc.code in (400, 401, 403, 404):
                break
        except Exception as exc:
            last_error = repr(exc)
            print(f'Tentativa {attempt}/3 upload PDF falhou em {storage_path}: {last_error}')
        time.sleep(min(2 * attempt, 5))

    # Segunda tentativa usando o helper antigo, caso alguma diferença de stream/header resolva.
    class _PdfFile:
        filename = Path(storage_path).name or 'relatorio.pdf'
        mimetype = 'application/pdf'
        def __init__(self, data):
            self.stream = io.BytesIO(data)
        def read(self):
            self.stream.seek(0)
            return self.stream.read()

    try:
        if upload_file_to_supabase(_PdfFile(pdf_bytes), storage_path, content_type='application/pdf'):
            return get_file_url(storage_path)
    except Exception as exc:
        last_error = f'{last_error} | helper: {repr(exc)}'

    fallback_url = _save_pdf_bytes_locally(pdf_bytes, storage_path)
    print(f'Upload do PDF para Supabase falhou; usando fallback local. Motivo: {last_error}. URL: {fallback_url}')
    return fallback_url
