"""Leitura, persistência e entrega de anexos."""
import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from flask import redirect, send_file
from werkzeug.utils import secure_filename

from app.shared.rows import row_to_dict
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

def read_attachment_bytes(stored, kind='', empresa_id=None):
    """Lê anexo local ou público no Supabase, usado em PDFs/zips."""
    full = resolve_local_path(stored)

    if full and full.exists() and full.is_file():
        return full.read_bytes(), full.name

    url = get_file_url(
        stored,
        kind=kind,
        empresa_id=empresa_id
    )

    name = Path(
        normalize_storage_path(
            stored,
            kind=kind,
            empresa_id=empresa_id
        )
    ).name or 'arquivo'

    try:
        with urllib_request.urlopen(url, timeout=20) as resp:
            return resp.read(), name
    except Exception as exc:
        print('read_attachment_bytes falhou:', exc)
        return None, name

def storage_or_local_response(stored, as_attachment=False, download_name=None, kind='', empresa_id=None):
    """Entrega arquivo local se existir; caso contrário redireciona para o Supabase."""
    full = resolve_local_path(stored)

    if full and full.exists() and full.is_file():
        return send_file(
            full,
            as_attachment=as_attachment,
            download_name=download_name or full.name,
            conditional=not as_attachment
        )

    return redirect(get_file_url(stored, kind=kind, empresa_id=empresa_id))


ATTACHMENT_GROUPS = {
    'orcamento': 'anexos_orcamento',
    'nf': 'anexos_nf',
    'boleto': 'anexos_boleto',
}


def _payment_attachment_relpath(filename: str, empresa_id=None) -> str:
    """Caminho oficial dos anexos da aba Pagamentos.

    NF e boleto ficam juntos em:
    empresas/<empresa>/BOLETO E NF/<arquivo>
    """
    folder = company_folder_name(empresa_id or current_company_id())
    safe_name = secure_filename(Path(str(filename or 'arquivo')).name) or 'arquivo'
    return f'empresas/{folder}/{PAYMENT_STORAGE_FOLDER}/{safe_name}'


def payment_storage_kind():
    return 'pagamentos'


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


def persist_payment_attachment(raw_path):
    raw = str(raw_path or '').strip()
    if not raw:
        return raw

    # URL/caminho já normalizado: limpa e guarda como caminho de storage.
    if raw.startswith(('http://', 'https://')):
        return normalize_storage_path(raw, kind=payment_storage_kind())
    if raw.startswith(('static/uploads/pagamentos/', 'static/uploads/empresas/', 'uploads/empresas/', 'empresas/', 'uploads/pagamentos/')):
        return normalize_storage_path(raw, kind=payment_storage_kind())

    source = resolve_local_path(raw)
    if not source or not source.exists() or not source.is_file():
        return normalize_storage_path(raw, kind=payment_storage_kind())

    original = secure_filename(source.name) or 'arquivo'
    unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{original}"
    storage_path = _payment_attachment_relpath(unique_name)

    class _LocalFile:
        filename = original
        mimetype = mimetypes.guess_type(original)[0] or 'application/octet-stream'
        def __init__(self, path):
            self.path = path
            self.stream = open(path, 'rb')
        def read(self):
            return self.stream.read()

    try:
        local_obj = _LocalFile(source)
        uploaded = upload_file_to_supabase(local_obj, storage_path, local_obj.mimetype)
        local_obj.stream.close()
        if uploaded:
            return storage_path
    except Exception:
        pass

    dest = tenant_upload_dir(PAYMENT_STORAGE_FOLDER) / unique_name
    if not dest.exists():
        shutil.copy2(source, dest)
    return f'static/uploads/empresas/{company_folder_name()}/{PAYMENT_STORAGE_FOLDER}/{dest.name}'


def normalize_payment_attachment_list(items):
    output = []
    seen = set()
    for item in (items or []):
        stored = persist_payment_attachment(item)
        if stored and stored not in seen:
            output.append(stored)
            seen.add(stored)
    return output


def sync_payment_attachments(row_or_id, persist_db=True):
    row = row_or_id
    if isinstance(row_or_id, int):
        row = row_to_dict(query_one('SELECT * FROM pagamentos WHERE id=?', (row_or_id,)))
    row = row or {}
    changed = False
    normalized = {}
    for key in ATTACHMENT_GROUPS.values():
        normalized[key] = normalize_payment_attachment_list(row.get(key, []))
        if normalized[key] != list(row.get(key, []) or []):
            changed = True
    if changed and persist_db and row.get('id'):
        from app.auth.tenancy import tenant_scope_sql
        scope_sql, scope_params = tenant_scope_sql('pagamentos')
        execute(
            'UPDATE pagamentos SET anexos_orcamento=?, anexos_nf=?, anexos_boleto=? WHERE id=?' + scope_sql,
            (
                json.dumps(normalized['anexos_orcamento'], ensure_ascii=False),
                json.dumps(normalized['anexos_nf'], ensure_ascii=False),
                json.dumps(normalized['anexos_boleto'], ensure_ascii=False),
                row['id'],
            ) + tuple(scope_params),
        )
    row.update(normalized)
    return row


def missing_attachment_response(path_text=''):
    safe_name = os.path.basename(str(path_text or '').replace('\\', '/')) or 'arquivo'
    html = f"""<!doctype html>
<html lang='pt-br'>
<head><meta charset='utf-8'><title>Anexo não encontrado</title></head>
<body style='font-family:Arial,sans-serif;padding:28px;background:#f7f9fc;color:#1f2937;'>
    <h1 style='margin-top:0;'>Anexo não encontrado</h1>
    <p>Esse arquivo não está mais disponível no caminho original.</p>
    <p><strong>Arquivo:</strong> {safe_name}</p>
    <p>Se ele estava salvo só no seu PC e foi apagado, o sistema não consegue abrir mesmo.</p>
    <p>Daqui para frente, os novos anexos ficam copiados para dentro do programa automaticamente.</p>
</body></html>"""
    return html, 404, {'Content-Type': 'text/html; charset=utf-8'}


def save_os_files(file_list, prefix):
    """Salva vários anexos da O.S. sem sobrescrever arquivos anteriores.

    Quando SUPABASE_SERVICE_ROLE_KEY/SUPABASE_STORAGE_KEY estiver configurada,
    envia direto ao Supabase Storage. Sem chave, mantém fallback local para não quebrar.
    """
    saved = []
    for file in file_list or []:
        if file and file.filename:
            original = secure_filename(file.filename)
            if not original:
                continue
            stem, ext = os.path.splitext(original)
            unique_name = f"{prefix}_{uuid.uuid4().hex}_{stem[:60]}{ext.lower()}"
            storage_path = _os_attachment_relpath(unique_name)
            if upload_file_to_supabase(file, storage_path, getattr(file, 'mimetype', None)):
                saved.append(storage_path)
            else:
                dest = tenant_upload_dir('os') / unique_name
                file.save(dest)
                saved.append(f'static/uploads/empresas/{company_folder_name()}/os/{dest.name}')
    return saved


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





def _os_attachment_relpath(filename: str, empresa_id=None) -> str:
    folder = company_folder_name(empresa_id or current_company_id())
    return f'empresas/{folder}/os/{filename}'


def persist_os_attachment(raw_path, prefix='arquivo_os'):
    """Normaliza ou copia anexos antigos/externos da O.S.

    Caminhos antigos em static/uploads agora viram caminhos de Storage
    (empresas/<empresa>/os/arquivo). Arquivos externos ainda são copiados/enviados.
    """
    raw = str(raw_path or '').strip()
    if not raw:
        return raw

    if raw.startswith(('http://', 'https://')):
        return normalize_storage_path(raw, kind='os')

    # Caminhos locais/legados só viram caminho de Storage quando o arquivo realmente
    # foi enviado para o Supabase. Se o upload falhar e o arquivo existir localmente,
    # mantemos o caminho local para a rota /os/imagem conseguir servir a foto.
    if raw.startswith(('static/uploads/empresas/', 'static/uploads/os/', 'uploads/empresas/')):
        source = resolve_local_path(raw)
        if source and source.exists() and source.is_file():
            original = secure_filename(source.name) or 'arquivo'
            stem, ext = os.path.splitext(original)
            unique_name = f"{prefix}_{uuid.uuid4().hex}_{stem[:60]}{ext.lower()}"
            storage_path = _os_attachment_relpath(unique_name)

            class _LegacyLocalFile:
                filename = original
                mimetype = mimetypes.guess_type(original)[0] or 'application/octet-stream'
                def __init__(self, path):
                    self.stream = open(path, 'rb')
                def read(self):
                    return self.stream.read()

            try:
                local_obj = _LegacyLocalFile(source)
                uploaded = upload_file_to_supabase(local_obj, storage_path, local_obj.mimetype)
                local_obj.stream.close()
                if uploaded:
                    return storage_path
            except Exception as exc:
                print('persist_os_attachment upload legado falhou:', exc)
            return raw
        return normalize_storage_path(raw, kind='os')

    if raw.startswith('empresas/'):
        return normalize_storage_path(raw, kind='os')

    source = resolve_local_path(raw)
    if not source or not source.exists() or not source.is_file():
        return normalize_storage_path(raw, kind='os')

    original = secure_filename(source.name) or 'arquivo'
    stem, ext = os.path.splitext(original)
    unique_name = f"{prefix}_{uuid.uuid4().hex}_{stem[:60]}{ext.lower()}"
    storage_path = _os_attachment_relpath(unique_name)

    class _LocalFile:
        filename = original
        mimetype = mimetypes.guess_type(original)[0] or 'application/octet-stream'
        def __init__(self, path):
            self.path = path
            self.stream = open(path, 'rb')
        def read(self):
            return self.stream.read()
    try:
        local_obj = _LocalFile(source)
        uploaded = upload_file_to_supabase(local_obj, storage_path, local_obj.mimetype)
        local_obj.stream.close()
        if uploaded:
            return storage_path
    except Exception:
        pass

    dest = tenant_upload_dir('os') / unique_name
    shutil.copy2(source, dest)
    return f'static/uploads/empresas/{company_folder_name()}/os/{dest.name}'


def normalize_os_attachment_list(items, prefix='arquivo_os'):
    output = []
    seen = set()
    for item in (items or []):
        stored = persist_os_attachment(item, prefix=prefix)
        if stored and stored not in seen:
            output.append(stored)
            seen.add(stored)
    return output


def sync_os_attachments(row_or_id, persist_db=True):
    row = row_or_id
    if isinstance(row_or_id, int):
        row = row_to_dict(query_one('SELECT * FROM os_ordens WHERE id=?', (row_or_id,)))
    row = row or {}
    if not row:
        return row

    try:
        imagens = json.loads(row.get('imagens') or '[]') if not isinstance(row.get('imagens'), list) else row.get('imagens')
    except Exception:
        imagens = []
    try:
        orcamentos = json.loads(row.get('orcamentos') or '[]') if not isinstance(row.get('orcamentos'), list) else row.get('orcamentos')
    except Exception:
        orcamentos = []

    novas_imagens = normalize_os_attachment_list(imagens, prefix='foto_os')
    novos_orcamentos = normalize_os_attachment_list(orcamentos, prefix='orcamento_os')

    changed = novas_imagens != list(imagens or []) or novos_orcamentos != list(orcamentos or [])
    if changed and persist_db and row.get('id'):
        from app.auth.tenancy import tenant_scope_sql
        scope_sql, scope_params = tenant_scope_sql('os_ordens')
        execute(
            'UPDATE os_ordens SET imagens=?, orcamentos=? WHERE id=?' + scope_sql,
            (
                json.dumps(novas_imagens, ensure_ascii=False),
                json.dumps(novos_orcamentos, ensure_ascii=False),
                row.get('id'),
            ) + tuple(scope_params),
        )

    row = dict(row)
    row['imagens'] = novas_imagens
    row['orcamentos'] = novos_orcamentos
    return row


_PDF_IMAGE_CACHE = {}
_PDF_IMAGE_CACHE_LOCK = threading.Lock()
PDF_IMAGE_TIMEOUT_SECONDS = int(os.getenv('PDF_IMAGE_TIMEOUT_SECONDS', '5') or 5)

def read_attachment_bytes_fast(stored, kind='', empresa_id=None):
    raw = str(stored or '').strip()
    if not raw:
        return None, 'arquivo'

    key = normalize_storage_path(
        raw,
        kind=kind,
        empresa_id=empresa_id
    ) or raw

    cached = None
    with _PDF_IMAGE_CACHE_LOCK:
        cached = _PDF_IMAGE_CACHE.get(key)
    if cached:
        return cached

    full = resolve_local_path(raw)
    if full and full.exists() and full.is_file():
        # Evita carregar imagens absurdamente grandes na RAM.
        try:
            if full.stat().st_size > 10 * 1024 * 1024:
                print('read_attachment_bytes_fast ignorou arquivo grande:', full.name)
                return None, full.name
        except Exception:
            pass
        data_name = (full.read_bytes(), full.name)
    else:
        # Caminhos antigos do Windows/local não existem no Render e viravam URL inválida no Supabase.
        if re.match(r'^[A-Za-z]:[\/]', raw) or raw.startswith('\\'):
            return None, Path(raw.replace('\\', '/')).name or 'arquivo'

        url = get_file_url(
            raw,
            kind=kind,
            empresa_id=empresa_id
        )

        name = Path(
            normalize_storage_path(
                raw,
                kind=kind,
                empresa_id=empresa_id
            )
        ).name or 'arquivo'

        try:
            req = urllib_request.Request(url)
            # Bucket público — sem headers de autenticação
            try:
                with urllib_request.urlopen(req, timeout=PDF_IMAGE_TIMEOUT_SECONDS) as resp:
                    clen = resp.headers.get('Content-Length')
                    if clen and int(clen) > 10 * 1024 * 1024:
                        print('read_attachment_bytes_fast ignorou URL grande:', name)
                        return None, name
                    data = resp.read(10 * 1024 * 1024 + 1)
                    if len(data) > 10 * 1024 * 1024:
                        print('read_attachment_bytes_fast ignorou download grande:', name)
                        return None, name
                    data_name = (data, name)
            except urllib_error.HTTPError as exc:
                if getattr(exc, 'code', 0) == 400:
                    filename = Path(raw).name
                    fallback_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{urllib_parse.quote(filename, safe='._-~')}"
                    try:
                        with urllib_request.urlopen(fallback_url, timeout=PDF_IMAGE_TIMEOUT_SECONDS) as resp2:
                            data = resp2.read(10 * 1024 * 1024 + 1)
                            data_name = (data, name)
                    except Exception:
                        print('read_attachment_bytes_fast pulou anexo HTTP:', getattr(exc, 'code', ''), name)
                        return None, name
                else:
                    print('read_attachment_bytes_fast pulou anexo HTTP:', getattr(exc, 'code', ''), name)
                    return None, name
            except Exception as exc:
                print('read_attachment_bytes_fast falhou:', exc)
                return None, name
        except Exception as exc:
            print('read_attachment_bytes_fast erro externo:', exc)
            return None, name

    # cache pequeno e simples
    if data_name and data_name[0] and len(data_name[0]) <= 8 * 1024 * 1024:
        with _PDF_IMAGE_CACHE_LOCK:
            if len(_PDF_IMAGE_CACHE) > 250:
                _PDF_IMAGE_CACHE.clear()
            _PDF_IMAGE_CACHE[key] = data_name
    return data_name
