"""Middleware de sessão e handlers globais."""
import time

from flask import current_app, flash, has_request_context, jsonify, redirect, request, session, url_for
from werkzeug.exceptions import HTTPException

from app.auth.csrf import _csrf_validate
from app.auth.decorators import ensure_logged_in
from app.auth.services import permission_denied_redirect
from app.config import SESSION_IDLE_MINUTES


def _render_error(code, title, message, tone='danger'):
    from app.shared.errors import render_error_page
    return render_error_page(code, title, message, tone=tone)

def auth_gate():
    if 'user_id' in session and not request.path.startswith('/static/'):
        if not session.get('_is_permanent', False):
            last_active = session.get('_last_active', 0)
            now_ts = time.time()
            idle_seconds = SESSION_IDLE_MINUTES * 60
            if last_active and (now_ts - last_active) > idle_seconds:
                session.clear()
                flash('Sessão expirada por inatividade. Faça login novamente.', 'warning')
                return redirect(url_for('login', next=request.path))
            session['_last_active'] = now_ts
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        if not _csrf_validate():
            current_app.logger.warning('CSRF bloqueado: IP=%s endpoint=%s', request.remote_addr, request.endpoint)
            if request.path.startswith('/api/'):
                return jsonify({'ok': False, 'error': 'Token de segurança inválido. Recarregue a página.'}), 403
            flash('Token de segurança inválido. Recarregue a página e tente novamente.', 'danger')
            return redirect(request.referrer or url_for('login'))
    return ensure_logged_in()
def handle_not_found(exc):
    path = request.path if has_request_context() else ''

    current_app.logger.warning('404 não encontrado: %s', path)

    if path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Recurso não encontrado.'}), 404

    if path.startswith('/static/'):
        return 'Arquivo estático não encontrado.', 404

    if session.get('user_id'):
        return _render_error(
            404,
            'Página não encontrada',
            'O endereço que você abriu não existe ou foi movido.',
            tone='warn',
        )
    return permission_denied_redirect('Página ou arquivo não encontrado.')


def handle_unexpected_error(exc):
    if isinstance(exc, HTTPException):
        return exc

    current_app.logger.exception('Erro inesperado: %s', exc)
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:
        pass

    path = request.path if has_request_context() else ''

    if path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Erro interno no servidor.'}), 500

    if path.startswith('/os/pdf'):
        flash(f'Não foi possível gerar o PDF: {exc}', 'danger')
        return redirect(url_for('os_page'))

    if path.startswith('/usuarios'):
        flash(f'Não foi possível concluir a ação em usuários: {exc}', 'danger')
        return redirect(url_for('usuarios_page'))

    if session.get('user_id'):
        return _render_error(
            500,
            'Algo deu errado',
            'Ocorreu um erro inesperado. A operação foi interrompida com segurança. Se persistir, contate o suporte.',
            tone='danger',
        )
    return permission_denied_redirect('Ocorreu um erro inesperado. A operação foi interrompida com segurança.')
