"""Identidade da empresa, templates WhatsApp e backup local."""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from app.db.schema import select_existing_columns
from app.shared.cache import clear_view_cache
from app.shared.formatters import br_now, now_str
from app.shared.rows import row_to_dict

from app.auth.constants import TENANT_TABLES
from app.storage.paths import (
    company_identity_config_path,
    company_identity_dir,
    tenant_upload_dir,
)


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

_last_backup_by_company = {}
_backup_lock = threading.Lock()

def ensure_company_storage(empresa_id=None):
    for kind in (OS_STORAGE_FOLDER, PAYMENT_STORAGE_FOLDER, 'pagamentos', 'exports', 'backups', 'identidade', 'whatsapp_templates', 'documentos'):
        tenant_upload_dir(kind, empresa_id)
    cfg = company_identity_config_path(empresa_id)
    if not cfg.exists():
        save_company_identity_config({}, empresa_id=empresa_id)


def company_identity_dir(empresa_id=None):
    return tenant_upload_dir('identidade', empresa_id)


def company_identity_config_path(empresa_id=None):
    return company_identity_dir(empresa_id) / 'config.json'
def _company_identity_from_legacy_json(empresa_id=None):
    try:
        p = company_identity_config_path(empresa_id)
        if p.exists():
            data = json.loads(p.read_text(encoding='utf-8') or '{}')
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _company_identity_payload(data, row=None):
    row = row or {}
    data = data or {}
    nome = row.get('nome') or ''
    cidade = row.get('cidade') or ''
    return {
        'cliente': data.get('cliente') or data.get('cliente_pdf') or row.get('cliente_pdf') or '',
        'contratada': data.get('contratada') or data.get('contratada_pdf') or row.get('contratada_pdf') or nome,
        'cnpj': data.get('cnpj') or data.get('cnpj_pdf') or row.get('cnpj_pdf') or '',
        'cidade': data.get('cidade') or data.get('cidade_pdf') or row.get('cidade_pdf') or cidade,
        'responsavel': data.get('responsavel') or data.get('responsavel_pdf') or row.get('responsavel_pdf') or '',
        'assinatura_esquerda_label': data.get('assinatura_esquerda_label') or row.get('assinatura_esquerda_label') or nome,
        'assinatura_direita_label': data.get('assinatura_direita_label') or row.get('assinatura_direita_label') or '',
        'assinatura_b64': data.get('assinatura_b64') or '',
    }


def load_company_identity_config(empresa_id=None):
    # Carrega os dados de identidade/marca da empresa sem efeito colateral recursivo.
    # Antes esta função podia chamar save_company_identity_config(), enquanto o save
    # chamava load_company_identity_config() de volta. No Render/mobile isso criava
    # recursão infinita, consumo de memória e queda do worker. Agora load só lê.
    empresa_id = empresa_id or current_company_id()

    row = {}
    if empresa_id and ensure_company_pdf_columns():
        try:
            cols = select_existing_columns('empresas', [
                'id', 'nome', 'cidade', 'dominio_email', 'ativo', 'criado_em',
                'cliente_pdf', 'contratada_pdf', 'cnpj_pdf', 'cidade_pdf', 'responsavel_pdf',
                'assinatura_esquerda_label', 'assinatura_direita_label'
            ])
            row = row_to_dict(query_one(f'SELECT {cols} FROM empresas WHERE id=?', (empresa_id,))) or {}
        except Exception as exc:
            print('load_company_identity_config banco falhou:', exc)
            row = {}

    legacy = _company_identity_from_legacy_json(empresa_id)
    return _company_identity_payload(legacy, row or {})


def save_company_identity_config(data, empresa_id=None):
    # Salva os dados de identidade/marca da empresa sem chamar load().
    # O save monta o estado atual lendo direto do banco e do JSON legado.
    # Assim não há ciclo load -> save -> load.
    empresa_id = empresa_id or current_company_id()

    row = {}
    if empresa_id:
        try:
            ensure_company_pdf_columns()
            cols = select_existing_columns('empresas', [
                'id', 'nome', 'cidade', 'cliente_pdf', 'contratada_pdf', 'cnpj_pdf',
                'cidade_pdf', 'responsavel_pdf', 'assinatura_esquerda_label',
                'assinatura_direita_label'
            ])
            row = row_to_dict(query_one(f'SELECT {cols} FROM empresas WHERE id=?', (empresa_id,))) or {}
        except Exception as exc:
            print('save_company_identity_config leitura banco falhou:', exc)
            row = {}

    # Base atual = JSON legado/local + colunas persistidas do banco.
    # Os dados recebidos por parâmetro vencem a base.
    base = _company_identity_payload(_company_identity_from_legacy_json(empresa_id), row or {})
    for k, v in (data or {}).items():
        if k in base or k in {
            'cliente_pdf', 'contratada_pdf', 'cnpj_pdf', 'cidade_pdf', 'responsavel_pdf'
        }:
            base[k] = v or ''

    current = _company_identity_payload(base, row or {})

    try:
        p = company_identity_config_path(empresa_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        print('save_company_identity_config fallback local falhou:', exc)

    if empresa_id and ensure_company_pdf_columns():
        try:
            execute("""UPDATE empresas
                       SET cliente_pdf=?, contratada_pdf=?, cnpj_pdf=?, cidade_pdf=?, responsavel_pdf=?,
                           assinatura_esquerda_label=?, assinatura_direita_label=?
                       WHERE id=?""", (
                current.get('cliente') or '',
                current.get('contratada') or '',
                current.get('cnpj') or '',
                current.get('cidade') or '',
                current.get('responsavel') or '',
                current.get('assinatura_esquerda_label') or '',
                current.get('assinatura_direita_label') or '',
                empresa_id,
            ))
        except Exception as exc:
            print('save_company_identity_config banco falhou:', exc)

    clear_view_cache()
    return current

def company_identity_file(filename, empresa_id=None):
    p = company_identity_dir(empresa_id) / filename
    return p if p.exists() else None


def save_company_identity_file(file_obj, filename, empresa_id=None):
    if not file_obj or not getattr(file_obj, 'filename', ''):
        return None
    dest = company_identity_dir(empresa_id) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    file_obj.save(dest)
    return dest


def whatsapp_templates_path(empresa_id=None):
    return tenant_upload_dir('whatsapp_templates', empresa_id) / 'templates.json'


def load_whatsapp_templates(empresa_id=None):
    p = whatsapp_templates_path(empresa_id)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding='utf-8') or '[]')
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return [{
        'nome': 'Nova O.S. para campo',
        'tipo': 'nova_os',
        'ativo': True,
        'texto': (
            '🚨 Nova O.S. #{os_id}\n\n'
            'Sistema: {sistema}\n'
            'Unidade: {unidade}\n'
            'Criticidade: {criticidade}\n\n'
            '📝 Descrição:\n{descricao}\n\n'
            '━━━━━━━━━━━━━━━━━━\n'
            '🟢 ▶️ INICIAR ATENDIMENTO\n'
            '━━━━━━━━━━━━━━━━━━\n'
            '{link}'
        ),
        'imagem': ''
    }]


def save_whatsapp_templates(items, empresa_id=None):
    p = whatsapp_templates_path(empresa_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items or [], ensure_ascii=False, indent=2), encoding='utf-8')


def active_whatsapp_template(tipo='nova_os', empresa_id=None):
    items = load_whatsapp_templates(empresa_id)
    for item in items:
        if str(item.get('tipo') or '') == tipo and item.get('ativo'):
            return item
    return items[0] if items else None






def backup_company_data(empresa_id=None):
    """Grava backup JSON local separado por empresa.

    No Render free isso pode consumir muita RAM porque varre tabelas inteiras.
    Por segurança fica DESLIGADO por padrão. Para religar conscientemente, defina
    ENABLE_LOCAL_BACKUP=1 no ambiente.
    """
    if os.getenv('ENABLE_LOCAL_BACKUP', '0').strip().lower() not in ('1', 'true', 'yes', 'on'):
        return
    try:
        empresa_id = int(empresa_id or current_company_id() or 0)
    except Exception:
        empresa_id = 0
    if not empresa_id:
        return
    # Backup completo é caro no Render/Supabase. Mantém proteção, mas evita rodar
    # uma varredura geral do banco em cada clique de salvar.
    now_ts = time.time()
    with _backup_lock:
        last_ts = _last_backup_by_company.get(empresa_id, 0)
        if now_ts - last_ts < int(os.getenv('BACKUP_THROTTLE_SECONDS', '300') or 300):
            return
        _last_backup_by_company[empresa_id] = now_ts
    try:
        backup_dir = tenant_upload_dir('backups', empresa_id)
        data = {'empresa_id': empresa_id, 'gerado_em': now_str(), 'tabelas': {}}
        for table in sorted(TENANT_TABLES):
            if table_has_column(table, 'empresa_id'):
                data['tabelas'][table] = [dict(r) for r in query_all(f'SELECT * FROM {table} WHERE empresa_id=? ORDER BY id', (empresa_id,))]
        payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        (backup_dir / 'dados_atualizados.json').write_text(payload, encoding='utf-8')
        stamped = backup_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        stamped.write_text(payload, encoding='utf-8')
        backups = sorted(backup_dir.glob('backup_*.json'), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in backups[20:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception as exc:
        print('backup_company_data falhou:', exc)
