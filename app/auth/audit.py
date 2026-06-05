"""Auditoria de ações."""
import json

from flask import has_request_context, request, session

from app.auth.services import get_current_user
from app.db import execute
from app.shared.formatters import now_str


def _audit_empresa_id():
    try:
        from app.auth.tenancy import current_company_id
        return current_company_id()
    except Exception:
        return session.get('empresa_id') if has_request_context() else None


def audit_security_event(acao, entidade='', entidade_id='', detalhes=None, resultado='registrado'):
    """Registra evento de segurança (super-admin, tenant, etc.)."""
    try:
        user = get_current_user() or {}
        payload = detalhes if isinstance(detalhes, str) else json.dumps(detalhes or {}, ensure_ascii=False, default=str)
        execute(
            '''INSERT INTO audit_logs(
                   criado_em, usuario_id, usuario_nome, usuario_email, acao, entidade, entidade_id,
                   metodo, rota, endpoint, resultado, detalhes, empresa_id
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                now_str(),
                user.get('id'),
                user.get('nome', 'Sistema'),
                user.get('email', ''),
                acao,
                entidade,
                str(entidade_id or ''),
                request.method if has_request_context() else '',
                request.path if has_request_context() else '',
                request.endpoint if has_request_context() else '',
                resultado,
                str(payload)[:4500],
                _audit_empresa_id(),
            ),
        )
    except Exception:
        pass


def _safe_audit_payload():
    blocked = {'senha', 'password', 'senha_hash'}
    payload = {}
    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            if isinstance(data, dict):
                payload.update(data)
        else:
            for k in request.form.keys():
                values = request.form.getlist(k)
                payload[k] = values if len(values) > 1 else request.form.get(k)
        if request.files:
            payload['arquivos'] = {k: [f.filename for f in request.files.getlist(k) if getattr(f, 'filename', '')] for k in request.files.keys()}
    except Exception as exc:
        payload = {'erro_payload': str(exc)}
    for k in list(payload.keys()):
        if k.lower() in blocked:
            payload[k] = '***'
    return json.dumps(payload, ensure_ascii=False, default=str)[:4500]

def _audit_action_label(endpoint, method):
    ep = endpoint or ''
    labels = {
        'usuarios_save': 'Salvou usuário/permissões',
        'usuarios_delete': 'Excluiu usuário',
        'os_save': 'Salvou O.S.',
        'os_status': 'Alterou status da O.S.',
        'api_delete': 'Excluiu registro',
        'api_os_attachment_delete': 'Excluiu anexo da O.S.',
        'api_pagamentos_attachment_delete': 'Excluiu anexo de pagamento',
        'pagamentos_save': 'Salvou pagamento',
        'custos_save': 'Salvou custo',
        'combustivel_save': 'Salvou combustível',
        'controle_save': 'Salvou estoque de bombas',
        'os_ativos_save': 'Salvou ativo da O.S.',
    }
    if ep in labels:
        return labels[ep]
    if method in ('POST','PUT','PATCH','DELETE'):
        return f'{method} em {ep or request.path}'
    return ep or request.path

def _audit_entity_from_path():
    parts = request.path.strip('/').split('/')
    entity = parts[0] if parts and parts[0] else ''
    rid = ''
    for part in parts[1:]:
        if str(part).isdigit():
            rid = str(part)
            break
    try:
        rid = rid or str((request.view_args or {}).get('rid') or request.form.get('id') or '')
    except Exception:
        pass
    return entity, rid
def audit_after_request(response):
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-XSS-Protection', '1; mode=block')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(self), camera=(), microphone=()')
    try:
        if request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    except Exception:
        pass
    try:
        if request.method not in ('POST','PUT','PATCH','DELETE'):
            return response
        if request.endpoint in {'login', 'static'} or request.path.startswith('/static/') or request.path.startswith('/iris'):
            return response
        user = get_current_user() or {}
        entidade, entidade_id = _audit_entity_from_path()
        resultado = 'sucesso' if response.status_code < 400 else f'falha {response.status_code}'
        execute('''INSERT INTO audit_logs(criado_em, usuario_id, usuario_nome, usuario_email, acao, entidade, entidade_id, metodo, rota, endpoint, resultado, detalhes, empresa_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (now_str(), user.get('id'), user.get('nome','Sistema'), user.get('email',''), _audit_action_label(request.endpoint, request.method),
                 entidade, entidade_id, request.method, request.path, request.endpoint or '', resultado, _safe_audit_payload(), _audit_empresa_id()))
    except Exception:
        pass
    return response
