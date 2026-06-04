"""Autenticação, permissões e multi-empresa."""
from app.auth.constants import (
    ALL_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    TENANT_TABLES,
    normalize_permissions,
)
from app.auth.services import (
    current_user_is_super_admin,
    get_current_user,
    module_view_permission,
    senha_confere,
    user_has,
)
from app.auth.tenancy import (
    _BACKGROUND_COMPANY_CONTEXT,
    company_and,
    company_where,
    create_company_if_needed,
    current_company,
    current_company_id,
    find_company_by_domain_or_name,
    list_companies,
    normalize_domain,
    owned_by_current_company,
    unique_email_for_domain,
)


def set_background_company_id(empresa_id):
    _BACKGROUND_COMPANY_CONTEXT.empresa_id = empresa_id


def get_background_company_id():
    return getattr(_BACKGROUND_COMPANY_CONTEXT, 'empresa_id', None)


def register_auth(app):
    from app.auth.audit import audit_after_request
    from app.auth.csrf import inject_csrf
    from app.auth.guards import auth_gate, handle_not_found, handle_unexpected_error
    from app.auth.routes import register_routes

    register_routes(app)
    app.before_request(auth_gate)
    app.context_processor(inject_csrf)
    app.after_request(audit_after_request)
    app.errorhandler(404)(handle_not_found)
    app.errorhandler(Exception)(handle_unexpected_error)


def require_permission(permission):
    from app.auth.decorators import require_permission as _require_permission

    return _require_permission(permission)


__all__ = [
    'register_auth',
    'ALL_PERMISSIONS', 'PERMISSION_LABELS', 'ROLE_LABELS', 'ROLE_PERMISSIONS', 'TENANT_TABLES',
    'normalize_permissions', 'get_current_user', 'user_has', 'senha_confere', 'current_user_is_super_admin',
    'current_company_id', 'current_company', 'company_where', 'company_and', 'owned_by_current_company',
    'list_companies', 'require_permission', 'module_view_permission', 'create_company_if_needed',
    'find_company_by_domain_or_name', 'normalize_domain', 'unique_email_for_domain',
    'set_background_company_id', 'get_background_company_id',
]
