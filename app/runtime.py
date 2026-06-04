"""Referências de runtime para workers e jobs em background."""
from types import SimpleNamespace

BACKGROUND_COMPANY_CONTEXT = SimpleNamespace(empresa_id=None)


def flask_app():
    from app.bootstrap import app
    return app
