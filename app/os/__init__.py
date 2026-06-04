"""Módulo O.S."""
from app.os.admin import register_admin_routes
from app.os.pdf import register_pdf_routes
from app.os.routes import register_routes
from app.os.services import (
    attach_os_display_numbers,
    ensure_os_tipo_os_column,
    os_is_overdue,
    prepare_os_row_for_template,
    proximo_numero_os,
    renumerar_os_por_mes,
    save_ativo,
    save_os,
)


def register_os(app):
    register_routes(app)
    register_pdf_routes(app)
    register_admin_routes(app)


__all__ = [
    'register_os',
    'prepare_os_row_for_template',
    'ensure_os_tipo_os_column',
    'attach_os_display_numbers',
    'os_is_overdue',
    'save_ativo',
    'save_os',
    'proximo_numero_os',
    'renumerar_os_por_mes',
]
