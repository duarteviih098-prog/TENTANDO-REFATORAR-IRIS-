"""Contexto de empresa (multi-tenant)."""
import re
import threading

from flask import g, has_request_context, session

from app.auth.constants import TENANT_TABLES
from app.db import query_all, query_one, table_has_column
from app.db.schema import select_existing_columns
from app.shared.formatters import now_str
from app.shared.rows import row_to_dict
from app.storage import ensure_company_storage, load_company_identity_config


def execute(sql, params=()):
    from app.db import execute as db_execute
    return db_execute(sql, params)

def normalize_domain(value):
    value = str(value or '').strip().lower()
    value = value.replace('http://', '').replace('https://', '').replace('@', '')
    value = value.split('/')[0].strip()
    return value


def username_from_name(nome):
    txt = str(nome or '').strip().lower()
    replacements = {'á':'a','à':'a','â':'a','ã':'a','ä':'a','é':'e','è':'e','ê':'e','ë':'e','í':'i','ì':'i','î':'i','ï':'i','ó':'o','ò':'o','ô':'o','õ':'o','ö':'o','ú':'u','ù':'u','û':'u','ü':'u','ç':'c','ñ':'n'}
    for a, b in replacements.items():
        txt = txt.replace(a, b)
    parts = [x for x in re.split(r'[^a-z0-9]+', txt) if x]
    if not parts:
        return 'usuario'
    if len(parts) == 1:
        return parts[0]
    return f'{parts[0]}.{parts[-1]}'


def unique_email_for_domain(nome, dominio, ignore_user_id=None):
    dominio = normalize_domain(dominio)
    base = username_from_name(nome)
    candidate = f'{base}@{dominio}' if dominio else f'{base}@empresa.local'
    n = 2
    while True:
        if ignore_user_id:
            row = query_one('SELECT id FROM users WHERE lower(email)=lower(?) AND id<>?', (candidate, ignore_user_id))
        else:
            row = query_one('SELECT id FROM users WHERE lower(email)=lower(?)', (candidate,))
        if not row:
            return candidate
        candidate = f'{base}{n}@{dominio}' if dominio else f'{base}{n}@empresa.local'
        n += 1


def find_company_by_domain_or_name(dominio='', nome=''):
    dominio = normalize_domain(dominio)
    nome = str(nome or '').strip()
    if dominio:
        row = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE lower(dominio_email)=lower(?)', (dominio,)))
        if row:
            return row
    if nome:
        row = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE lower(nome)=lower(?)', (nome,)))
        if row:
            return row
    return None


def create_company_if_needed(nome='', cidade='', dominio=''):
    nome = str(nome or '').strip()
    cidade = str(cidade or '').strip()
    dominio = normalize_domain(dominio)
    empresa = find_company_by_domain_or_name(dominio, nome)
    if empresa:
        # Atualiza domínio/cidade vazios quando a empresa já existe.
        updates = []
        params = []
        if dominio and not str(empresa.get('dominio_email') or '').strip():
            updates.append('dominio_email=?'); params.append(dominio)
        if cidade and not str(empresa.get('cidade') or '').strip():
            updates.append('cidade=?'); params.append(cidade)
        if updates:
            params.append(empresa['id'])
            execute(f"UPDATE empresas SET {', '.join(updates)} WHERE id=?", tuple(params))
            empresa = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (empresa['id'],)))
        ensure_company_storage(empresa.get('id'))
        return empresa, False
    if not nome:
        if dominio:
            nome = dominio.split('.')[0].upper()
        else:
            nome = 'Empresa sem nome'
    try:
        eid = execute('INSERT INTO empresas(nome,cidade,dominio_email,ativo,criado_em) VALUES (?,?,?,?,?)', (nome, cidade, dominio, 1, now_str()))
    except Exception:
        # Se bateu unique por corrida/digitação, tenta recuperar sem estourar o fluxo.
        empresa = find_company_by_domain_or_name(dominio, nome)
        if empresa:
            ensure_company_storage(empresa.get('id'))
            return empresa, False
        raise
    ensure_company_storage(eid)
    return row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (eid,))), True

# Contexto usado por tarefas em background (fora de request/session), como geração de PDF mensal.
_BACKGROUND_COMPANY_CONTEXT = threading.local()

def current_company_id():
    """Empresa efetiva do usuário logado, com cache por requisição.

    Evita consultar a tabela users dezenas de vezes no mesmo carregamento.
    Segurança mantida: usuário comum continua preso à empresa cadastrada no banco.
    """
    # Quando o PDF roda em background não existe request/session.
    # Usamos este contexto para manter o isolamento por empresa e carregar logos/dados corretos.
    bg_company_id = getattr(_BACKGROUND_COMPANY_CONTEXT, 'empresa_id', None)
    if bg_company_id:
        try:
            return int(bg_company_id)
        except Exception:
            return bg_company_id

    if has_request_context() and hasattr(g, '_current_company_id'):
        return g._current_company_id

    result = None
    uid = session.get('user_id') if has_request_context() else None
    if uid:
        try:
            row = query_one('SELECT empresa_id, is_super_admin, perfil FROM users WHERE id=? AND ativo=1', (uid,))
            if row:
                if int(row['is_super_admin'] or 0) == 1 or str(row['perfil'] or '').lower() == 'super_admin':
                    selected = session.get('selected_empresa_id') or session.get('empresa_id') or row['empresa_id']
                    result = int(selected) if selected else None
                else:
                    result = int(row['empresa_id']) if row['empresa_id'] else None
        except Exception:
            result = None

    if result is None and has_request_context():
        try:
            value = session.get('empresa_id')
            result = int(value) if value else None
        except Exception:
            result = None

    if has_request_context():
        g._current_company_id = result
    return result

def current_user_is_super_admin(user=None):
    if user is None:
        from app.auth.services import get_current_user
        user = get_current_user()
    return bool(user and (int(user.get('is_super_admin') or 0) == 1 or str(user.get('perfil') or '').lower() == 'super_admin'))



def current_company():
    if has_request_context() and hasattr(g, '_current_company_cached'):
        return g._current_company_cached
    cid = current_company_id()
    company = None
    if cid:
        company = row_to_dict(query_one('SELECT id, nome, cidade, dominio_email, ativo, criado_em FROM empresas WHERE id=?', (cid,)))
    if has_request_context():
        g._current_company_cached = company
    return company
def company_where(table, prefix=' WHERE '):
    if table not in TENANT_TABLES or not table_has_column(table, 'empresa_id'):
        return '', []
    # Mesmo a Super Admin trabalha dentro de uma empresa/contexto para não misturar dados.
    # Se quiser visão global depois, fazemos uma tela separada só para auditoria.
    empresa_id = current_company_id()
    if not empresa_id:
        return f"{prefix} empresa_id IS NULL", []
    return f"{prefix} empresa_id=?", [empresa_id]

def company_and(table):
    return company_where(table, ' AND ')

def owned_by_current_company(table, rid):
    if table not in TENANT_TABLES or not table_has_column(table, 'empresa_id'):
        return True
    empresa_id = current_company_id()
    if not empresa_id:
        return False
    row = query_one(f'SELECT id, empresa_id FROM {table} WHERE id=?', (rid,))
    if not row:
        return False
    row_empresa = int(row['empresa_id'] or 0)
    if row_empresa == int(empresa_id):
        return True
    if current_user_is_super_admin():
        from app.auth.audit import audit_security_event
        audit_security_event(
            'super_admin_acesso_negado_outra_empresa',
            entidade=table,
            entidade_id=rid,
            detalhes={'empresa_contexto': int(empresa_id), 'empresa_registro': row_empresa},
            resultado='bloqueado',
        )
    return False

def list_companies(active_only=False):
    from app.exports.company_pdf import ensure_company_pdf_columns

    ensure_company_pdf_columns()
    cols = select_existing_columns('empresas', [
        'id', 'nome', 'cidade', 'dominio_email', 'ativo', 'criado_em',
        'cliente_pdf', 'contratada_pdf', 'cnpj_pdf', 'cidade_pdf', 'responsavel_pdf',
        'assinatura_esquerda_label', 'assinatura_direita_label'
    ])
    sql = f'SELECT {cols} FROM empresas'
    params = []
    if active_only:
        sql += ' WHERE ativo=1'
    sql += ' ORDER BY nome'
    empresas = [dict(r) for r in query_all(sql, tuple(params))]

    # Carrega os dados persistidos do banco e, se houver backup antigo em JSON, migra para o banco.
    for empresa in empresas:
        try:
            cfg = load_company_identity_config(empresa.get('id')) or {}
        except Exception:
            cfg = {}
        empresa['cliente_pdf'] = cfg.get('cliente') or ''
        empresa['contratada_pdf'] = cfg.get('contratada') or empresa.get('nome') or ''
        empresa['cnpj_pdf'] = cfg.get('cnpj') or ''
        empresa['cidade_pdf'] = cfg.get('cidade') or empresa.get('cidade') or ''
        empresa['responsavel_pdf'] = cfg.get('responsavel') or ''
        empresa['assinatura_esquerda_label'] = cfg.get('assinatura_esquerda_label') or empresa.get('nome') or ''
        empresa['assinatura_direita_label'] = cfg.get('assinatura_direita_label') or ''
        # aliases extras, caso o template use nomes mais diretos
        empresa['cliente'] = empresa['cliente_pdf']
        empresa['contratada'] = empresa['contratada_pdf']
        empresa['cnpj'] = empresa['cnpj_pdf']
        empresa['responsavel'] = empresa['responsavel_pdf']
    return empresas
