"""Usuário logado, permissões e validação de senha."""
import hmac
import os
import time

from flask import g, has_request_context, request, session
from werkzeug.security import check_password_hash

from app.auth.constants import ALL_PERMISSIONS, ROLE_PERMISSIONS, normalize_permissions
from app.auth.tenancy import current_user_is_super_admin
from app.db import query_one
from app.shared.rows import row_to_dict


def get_current_user():
    if has_request_context() and hasattr(g, '_current_user_cached'):
        return g._current_user_cached
    uid = session.get('user_id') if has_request_context() else None
    if not uid:
        return None
    user = row_to_dict(query_one('SELECT id, nome, email, senha_hash, perfil, permissions, empresa_id, ativo, is_super_admin, telefone FROM users WHERE id=? AND ativo=1', (uid,)))
    if not user:
        session.clear()
        if has_request_context():
            g._current_user_cached = None
        return None
    user['permissions'] = normalize_permissions(user.get('permissions'))
    if has_request_context():
        g._current_user_cached = user
    return user

def user_has(permission):
    user = get_current_user()
    if not user:
        return False
    # Empresas, usuários e senhas: só a Super Admin.
    if permission == 'manage_users':
        return current_user_is_super_admin(user)
    if current_user_is_super_admin(user):
        return True
    # Se o usuário tem permissões customizadas salvas, elas têm prioridade absoluta
    # sobre o conjunto padrão do perfil. Isso permite restringir ou ampliar
    # individualmente sem mudar o perfil.
    custom_permissions = normalize_permissions(user.get('permissions'))
    if custom_permissions:
        return permission in custom_permissions
    # Sem permissões customizadas: usa o conjunto padrão do perfil
    perfil = user.get('perfil') or 'campo'
    return permission in ROLE_PERMISSIONS.get(perfil, [])
def module_view_permission(module):
    return {
        'controle': 'view_controle',
        'combustivel': 'view_combustivel',
        'pagamentos': 'view_pagamentos',
        'custos': 'view_custos',
        'os': 'view_os',
        'os_ativos': 'view_os_ativos',
        'inventario': 'view_inventario',
    }.get(module)


LANDING_ROUTES = (
    ('view_dashboard', 'dashboard'),
    ('view_os', 'os_page'),
    ('view_controle', 'controle_hub'),
    ('view_pagamentos', 'pagamentos'),
    ('view_combustivel', 'combustivel'),
    ('view_custos', 'custos'),
    ('view_inventario', 'inventario_page'),
    ('view_outlook', 'outlook_page'),
)


def default_landing_url():
    """Primeira rota acessível ao usuário; evita loop dashboard ↔ os."""
    from flask import url_for

    for perm, endpoint in LANDING_ROUTES:
        if user_has(perm):
            return url_for(endpoint)
    return url_for('login')


def permission_denied_redirect(message='Você não tem permissão para acessar essa área.'):
    """Redireciona ou mostra página 403 quando falta permissão."""
    from flask import flash, redirect, request, session, url_for

    if request.path.startswith('/api/') or (request.is_json and request.method != 'GET'):
        from flask import jsonify
        return jsonify({'ok': False, 'error': message}), 403

    if session.get('user_id'):
        from app.shared.errors import render_error_page
        return render_error_page(
            403,
            'Sem permissão',
            message,
            tone='danger',
            back_label='Voltar ao início',
        )

    flash(message, 'danger')
    landing = default_landing_url()
    if landing != url_for('login'):
        return redirect(landing)
    flash('Sua conta não tem acesso a nenhum módulo. Contate o administrador.', 'warning')
    session.clear()
    return redirect(url_for('login'))


def _get_user_permissions(user):
    """Retorna lista de permissões do usuário atual para o onboarding."""
    if not user:
        return []
    if user.get('is_super_admin') or user.get('perfil') == 'admin':
        return list(ALL_PERMISSIONS) if hasattr(ALL_PERMISSIONS, 'keys') else []
    try:
        perms_raw = user.get('permissions') or ''
        if isinstance(perms_raw, str) and perms_raw.startswith('['):
            import json as _j
            return _j.loads(perms_raw)
        elif isinstance(perms_raw, list):
            return perms_raw
        return [p.strip() for p in str(perms_raw).split(',') if p.strip()]
    except Exception:
        return []



def senha_confere(senha_hash='', senha_digitada=''):
    """Valida senha atual e formatos legados sem derrubar login.

    Alguns cadastros antigos/sincronizados podem ter ficado com senha em texto
    ou com espaços acidentais. O login precisa aceitar o que foi salvo e, se for
    legado, a rota atualiza para hash depois.
    """
    senha_hash = str(senha_hash or '')
    senha_digitada = str(senha_digitada or '')
    tentativas = [senha_digitada]
    senha_strip = senha_digitada.strip()
    if senha_strip != senha_digitada:
        tentativas.append(senha_strip)
    if not senha_hash:
        return False
    for tentativa in tentativas:
        if not tentativa and senha_hash:
            continue
        try:
            if check_password_hash(senha_hash, tentativa):
                return True
        except Exception:
            pass
        if hmac.compare_digest(senha_hash, tentativa):
            return True
    return False



LOGIN_MAX_ATTEMPTS = int(os.getenv('LOGIN_MAX_ATTEMPTS', '5') or 5)
LOGIN_WINDOW_SECONDS = int(os.getenv('LOGIN_WINDOW_SECONDS', '600') or 600)   # 10 min
LOGIN_BLOCK_SECONDS = int(os.getenv('LOGIN_BLOCK_SECONDS', '900') or 900)     # 15 min


def _login_get_ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()


def _login_is_blocked(ip):
    from app.auth.security_store import get_login_attempt

    now = time.time()
    entry = get_login_attempt(ip)
    if not entry:
        return False, 0
    blocked_until = entry.get('blocked_until', 0)
    if blocked_until and now < blocked_until:
        return True, int(blocked_until - now)
    if now - entry.get('first_at', 0) > LOGIN_WINDOW_SECONDS:
        from app.auth.security_store import delete_login_attempt
        delete_login_attempt(ip)
        return False, 0
    return False, 0


def _login_record_failure(ip):
    from app.auth.security_store import get_login_attempt, upsert_login_attempt

    now = time.time()
    entry = get_login_attempt(ip) or {'count': 0, 'first_at': now, 'blocked_until': 0}
    if now - entry.get('first_at', 0) > LOGIN_WINDOW_SECONDS:
        entry = {'count': 0, 'first_at': now, 'blocked_until': 0}
    count = int(entry.get('count') or 0) + 1
    blocked_until = entry.get('blocked_until', 0)
    if count >= LOGIN_MAX_ATTEMPTS:
        blocked_until = now + LOGIN_BLOCK_SECONDS
    upsert_login_attempt(ip, count, entry.get('first_at', now), blocked_until)
    return count, blocked_until


def _login_clear(ip):
    from app.auth.security_store import delete_login_attempt
    delete_login_attempt(ip)

