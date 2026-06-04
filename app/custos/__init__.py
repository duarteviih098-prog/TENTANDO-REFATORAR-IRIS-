"""Módulo Custos."""
from app.custos.routes import register_routes
from app.custos.services import ensure_custos_valid_ids, import_custos_excel, save_custo


def register_custos(app):
    register_routes(app)


__all__ = [
    'register_custos',
    'save_custo',
    'import_custos_excel',
    'ensure_custos_valid_ids',
]
