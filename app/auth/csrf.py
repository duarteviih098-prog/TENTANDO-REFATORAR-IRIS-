"""Proteção CSRF."""
from flask import request, session


def _csrf_generate():
    import secrets
    token = secrets.token_hex(32)
    session['_csrf_token'] = token
    return token

def _csrf_get():
    if '_csrf_token' not in session:
        _csrf_generate()
    return session['_csrf_token']

def _csrf_validate():
    public_endpoints = {'login', 'static', 'campo_app', 'campo_app_empty', 'campo_login',
                        'esqueci_senha', 'redefinir_senha',
                        'os_pdf_dia', 'os_pdf_mes', 'os_pdf_individual', 'iris_relatorio_wait',
                        'os_pdf_job_status', 'api_os_status_updates',
                        # App de campo — usa token próprio, não sessão de browser
                        'campo_tecnico', 'campo_short_app', 'campo_loading',
                        'api_campo_localizacao', 'api_campo_tecnicos_mapa',
                        'service_worker', 'pwa_manifest', 'asset_links',
                        'push_subscribe', 'push_vapid_public_key'}
    if request.endpoint in public_endpoints:
        return True
    # Todas as rotas /campo/ e /os/*/campo/ usam token próprio
    if request.path.startswith('/static/') or request.path.startswith('/campo/'):
        return True
    if '/campo/' in request.path:
        return True
    if request.path.startswith('/os/pdf') or request.path.startswith('/iris/relatorio'):
        return True
    # APIs JSON com sessão autenticada exigem CSRF no header
    if request.path.startswith('/api/'):
        if request.method == 'GET':
            return True
        if request.args.get('tecnico_token'):
            return True
        if session.get('user_id'):
            token_form = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token') or ''
            token_sess = session.get('_csrf_token') or ''
            if token_form and token_sess:
                import hmac as _hmac
                return _hmac.compare_digest(str(token_form), str(token_sess))
        if session.get('user_id') and request.is_json:
            token_form = request.headers.get('X-CSRF-Token') or ''
            token_sess = session.get('_csrf_token') or ''
            if not token_form or not token_sess:
                return False
            import hmac as _hmac
            return _hmac.compare_digest(str(token_form), str(token_sess))
        if request.is_json:
            return True
    if request.path.startswith('/push/'):
        return True
    token_form = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token') or ''
    token_sess = session.get('_csrf_token') or ''
    if not token_form or not token_sess:
        return False
    import hmac as _hmac
    return _hmac.compare_digest(str(token_form), str(token_sess))


def inject_csrf():
    return {'csrf_token': _csrf_get}
