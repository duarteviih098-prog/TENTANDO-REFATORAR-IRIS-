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
    # APIs: GET sempre livre, POST JSON ou com tecnico_token livre
    if request.path.startswith('/api/'):
        if request.method == 'GET':
            return True
        if request.is_json:
            return True
        if request.args.get('tecnico_token'):
            return True
    # Rotas internas que recebem JSON também livres de CSRF
    if request.is_json and request.path.startswith('/controle/'):
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
