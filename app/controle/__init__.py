"""Módulo Controle — estoque de bombas."""
from app.controle.routes import register_routes
from app.controle.services import (
    compute_bomba_delivery,
    fetch_bombas_counts,
    import_controle_excel,
    save_bomba,
)


def register_controle(app):
    register_routes(app)


__all__ = [
    'register_controle',
    'compute_bomba_delivery',
    'fetch_bombas_counts',
    'save_bomba',
    'import_controle_excel',
]
