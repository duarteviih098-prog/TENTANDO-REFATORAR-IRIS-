"""Módulo Exports — PDF/Excel transversais."""


def register_exports(app):
    from app.exports.routes import register_routes

    register_routes(app)


__all__ = ['register_exports']
