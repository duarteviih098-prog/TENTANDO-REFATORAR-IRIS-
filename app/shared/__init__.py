"""Pacote shared — helpers em submódulos; registro de rotas aqui."""


def register_shared(app):
    from app.shared.api import register_api_routes
    from app.shared.context import inject_globals
    from app.shared.routes import register_routes

    register_routes(app)
    register_api_routes(app)
    app.context_processor(inject_globals)


__all__ = ['register_shared']
