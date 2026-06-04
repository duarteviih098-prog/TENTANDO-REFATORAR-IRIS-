"""Módulo Campo / PWA."""


def register_campo(app):
    from app.campo.push import register_push_routes
    from app.campo.routes import register_routes

    register_routes(app)
    register_push_routes(app)


__all__ = ['register_campo']
