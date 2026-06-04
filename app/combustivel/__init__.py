"""Módulo Combustível."""
from app.combustivel.constants import COMBUSTIVEL_VINCULOS
from app.combustivel.routes import register_routes
from app.combustivel.services import (
    combustivel_duplicado,
    ensure_combustivel_valid_ids,
    get_comb_vinculos,
    import_combustivel_excel,
    save_combustivel,
)


def register_combustivel(app):
    register_routes(app)


__all__ = [
    'register_combustivel',
    'COMBUSTIVEL_VINCULOS',
    'combustivel_duplicado',
    'ensure_combustivel_valid_ids',
    'get_comb_vinculos',
    'save_combustivel',
    'import_combustivel_excel',
]
