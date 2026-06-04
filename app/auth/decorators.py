"""Decorators e gate de autenticação."""
from functools import wraps

from flask import current_app, flash, redirect, request, session, url_for

from app.auth.services import permission_denied_redirect, user_has
from app.db import query_one
from app.shared.rows import row_to_dict


def is_mobile_request():
    """Detecta se a requisição vem de um celular."""
    ua = request.headers.get('User-Agent', '').lower()
    return any(x in ua for x in ['android', 'iphone', 'ipad', 'mobile', 'tablet'])


def require_permission(permission):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login', next=request.path))
            if not user_has(permission):
                return permission_denied_redirect()
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def ensure_logged_in():
    public_endpoints = {'login', 'campo_login', 'loading', 'campo_loading', 'static', 'campo_tecnico', 'campo_short_app', 'campo_app', 'campo_app_empty', 'os_imagem_visualizar', 'favicon_root', 'health', 'service_worker', 'push_vapid_public_key', 'push_subscribe', 'esqueci_senha', 'redefinir_senha',
                        'api_campo_localizacao', 'api_campo_tecnicos_mapa', 'api_campo_gps_debug',
                        'pwa_manifest', 'asset_links'}

    if request.path == '/static/favicon.ico':
        return redirect(url_for('favicon_root'))

    if request.endpoint in public_endpoints:
        return None

    if request.path.startswith('/static/'):
        return None

    if request.path == '/favicon.ico':
        return None

    if not session.get('user_id'):
        return redirect(url_for('login', next=request.path))

    try:
        allowed = {'logout', 'campo_app', 'campo_app_empty', 'campo_tecnico', 'campo_short_app', 'static', 'favicon_root', 'health', 'gestor_app'}
        mobile_module_endpoints = {
            'pagamentos', 'pagamentos_save', 'pagamentos_pdf', 'pagamentos_excel',
            'combustivel', 'combustivel_save', 'combustivel_pdf', 'combustivel_excel',
            'controle', 'controle_save', 'custos', 'custos_save',
            'os_page', 'os_save', 'os_action', 'os_pdf_individual', 'os_pdf_dia', 'os_pdf_mes',
            'campo_page', 'campo_tecnico_save', 'campo_whatsapp', 'campo_whatsapp_equipe',
            'outlook_page', 'inventario_page', 'inventario_hub', 'inventario_itens', 'inventario_pedidos_page', 'inventario_movimentacoes', 'inventario_save', 'inventario_delete_bulk',
            'inventario_movimento', 'inventario_pedido_save', 'inventario_pedido_receber',
            'inventario_pedido_cancelar', 'inventario_retirada', 'inventario_mover_para_pedido',
            'inventario_pedido_receber_lote', 'api_inventario_get',
            'api_get', 'api_delete', 'api_os_historico', 'api_campo_eventos',
            'api_campo_feed_state', 'api_pagamentos_vencimentos', 'api_os_status_updates',
            'api_mobile_pag_save', 'api_mobile_comb_save', 'api_mobile_bomba_save',
            'dashboard', 'historico_page', 'usuarios_page',
            'controle_excel', 'custos_import', 'pagamentos_import', 'combustivel_import',
        }
        if request.endpoint not in allowed and request.endpoint not in mobile_module_endpoints:
            from app.campo.services import campo_token_para_usuario, usuario_eh_campo_operacional

            user_row = row_to_dict(query_one('SELECT id, nome, email, telefone, perfil, empresa_id, ativo, is_super_admin FROM users WHERE id=?', (session.get('user_id'),))) or {}
            if usuario_eh_campo_operacional(user_row):
                try:
                    token_campo = campo_token_para_usuario(user_row)
                    if token_campo:
                        return redirect(url_for('campo_app', token=token_campo))
                except Exception:
                    pass
            elif is_mobile_request() and not request.is_json and not request.path.startswith('/api/') and session.get('user_id') and request.endpoint in ('dashboard', 'home_page', 'index'):
                perfil = (user_row.get('perfil') or '').lower()
                is_admin = bool(int(user_row.get('is_super_admin') or 0))
                if is_admin or perfil in ('gestor', 'administrador', 'admin', 'usuario', 'padrão', 'padrao', 'gerente'):
                    return redirect(url_for('gestor_app'))
    except Exception:
        current_app.logger.exception('Falha ao bloquear desktop para usuário de campo')

    return None
