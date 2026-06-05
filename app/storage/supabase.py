"""Upload e headers Supabase Storage."""
import mimetypes
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from app.storage import settings

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_STORAGE_BUCKET = settings.SUPABASE_STORAGE_BUCKET
SUPABASE_STORAGE_KEY = settings.SUPABASE_STORAGE_KEY

def _storage_headers(content_type='application/octet-stream'):
    headers = {'Content-Type': content_type, 'x-upsert': 'true'}
    if SUPABASE_STORAGE_KEY:
        headers['apikey'] = SUPABASE_STORAGE_KEY
        headers['Authorization'] = f'Bearer {SUPABASE_STORAGE_KEY}'
    return headers

def upload_file_to_supabase(file_obj, storage_path, content_type=None):
    """Sobe arquivo para o Supabase Storage com diagnóstico decente.

    Retorna True/False para manter compatibilidade com o resto do sistema.
    Não apaga arquivo nenhum em caso de falha; apenas registra o motivo no log.
    """
    if not SUPABASE_STORAGE_KEY:
        print('upload_file_to_supabase falhou: SUPABASE_SERVICE_ROLE_KEY/SUPABASE_STORAGE_KEY ausente.')
        return False
    if not file_obj or not storage_path:
        print('upload_file_to_supabase falhou: arquivo ou storage_path vazio.')
        return False
    try:
        try:
            file_obj.stream.seek(0)
        except Exception:
            pass
        data = file_obj.read()
        try:
            file_obj.stream.seek(0)
        except Exception:
            pass
        if not data:
            print('upload_file_to_supabase falhou: conteúdo vazio.')
            return False

        storage_path = str(storage_path or '').strip().lstrip('/')
        content_type = content_type or getattr(file_obj, 'mimetype', None) or mimetypes.guess_type(storage_path)[0] or 'application/octet-stream'
        url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{urllib_parse.quote(storage_path, safe='/._-~')}"
        headers = _storage_headers(content_type)

        req = urllib_request.Request(url, data=data, headers=headers, method='POST')
        try:
            with urllib_request.urlopen(req, timeout=90) as resp:
                ok = 200 <= int(getattr(resp, 'status', 200)) < 300
                if not ok:
                    print('upload_file_to_supabase falhou: status inesperado', getattr(resp, 'status', None), storage_path)
                return ok
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read().decode('utf-8', errors='replace')[:1200]
            except Exception:
                body = ''
            print(f'upload_file_to_supabase HTTP {exc.code} em {storage_path}: {body}')
            return False
    except Exception as exc:
        print('upload_file_to_supabase falhou:', repr(exc))
        return False
