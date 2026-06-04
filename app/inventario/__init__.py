"""Módulo Inventário."""
from app.inventario.routes import register_routes


def register_inventario(app):
    register_routes(app)


__all__ = ['register_inventario']
