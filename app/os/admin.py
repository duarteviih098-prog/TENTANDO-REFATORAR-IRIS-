"""Rotas administrativas de O.S."""
from flask import jsonify
from app.shared.cache import clear_view_cache

from app.auth import current_company_id, current_user_is_super_admin
from app.os.services import renumerar_os_por_mes


def admin_renumerar_os():
    """Renumera todas as OS por mês — só super admin."""
    if not current_user_is_super_admin():
        return jsonify({'ok': False, 'error': 'Sem permissão.'}), 403
    empresa_id = current_company_id()
    ok = renumerar_os_por_mes(empresa_id)
    clear_view_cache()
    return jsonify({'ok': ok, 'message': 'Renumeração concluída.' if ok else 'Falhou.'})


def register_admin_routes(app):
    app.add_url_rule('/admin/renumerar-os', 'admin_renumerar_os', admin_renumerar_os, methods=['POST'])
