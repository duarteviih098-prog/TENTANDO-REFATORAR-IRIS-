"""Rotas de arquivos de empresa e helpers de template."""
from urllib import parse as urllib_parse

from flask import redirect

from app.storage.paths import get_file_url, normalize_storage_path


def os_image_public_url(rid, idx, token=None):
    token_str = str(token or '')
    encoded = urllib_parse.quote(token_str, safe='')
    qs = f'?token={encoded}' if token else ''
    return f'/os/imagem/{int(rid)}/{int(idx)}{qs}'


def inject_storage_helpers():
    return {
        'get_file_url': get_file_url,
        'normalize_storage_path': normalize_storage_path,
        'os_image_public_url': os_image_public_url,
    }

def supabase_empresa_file(storage_path):
    # Permite que caminhos normalizados salvos no banco funcionem direto no navegador.
    return redirect(get_file_url('empresas/' + storage_path))

def supabase_uploads_empresa_file(storage_path):
    return redirect(get_file_url('empresas/' + storage_path))


def register_routes(app):
    app.context_processor(inject_storage_helpers)
    app.add_url_rule('/empresas/<path:storage_path>', 'supabase_empresa_file', supabase_empresa_file)
    app.add_url_rule('/uploads/empresas/<path:storage_path>', 'supabase_uploads_empresa_file', supabase_uploads_empresa_file)
